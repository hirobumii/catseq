//! Compile-instance discovery and compile-attribute normalization.

use std::collections::{HashMap, HashSet};

use nac3ast::{Expr, ExprKind, Stmt, StmtKind};

use crate::{intrinsics, source_hir::SourceHirKind};

use super::ast_util::{expression_path, parse_module};
use super::compile_values::{
    checked_compile_annotation_type, class_annotation_type, class_fields,
    inferred_compile_aggregate_element_types, inferred_compile_value_type_with_known,
    normalized_compile_expression, normalized_compile_expression_in_with_known,
};
use super::model::{SourceType, TypedCheckError, TypedDefinition};
use super::resolution::{locate_source_definition, module_imports, resolve_call_path};

type CompileAttribute = (SourceType, String, Vec<SourceType>);

pub(super) fn load_referenced_compile_modules<F>(
    definitions: &[TypedDefinition],
    sources: &mut HashMap<String, String>,
    parsed: &mut HashMap<String, Vec<Stmt>>,
    loader: &mut F,
) -> Result<(), TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let mut references = Vec::new();
    for definition in definitions {
        let Some(statements) = parsed.get(definition.module()) else {
            continue;
        };
        let imports = module_imports(definition.module(), statements);
        for (node, fact) in definition
            .hir()
            .nodes()
            .iter()
            .zip(definition.hir().facts())
        {
            if !matches!(node.kind(), SourceHirKind::Name | SourceHirKind::Attribute) {
                continue;
            }
            if fact.module_binding_shadowed() {
                continue;
            }
            let Some(symbol) = node.symbol() else {
                continue;
            };
            if !symbol
                .split('.')
                .next()
                .is_some_and(|root| imports.contains_key(root))
            {
                continue;
            }
            let resolved = resolve_call_path(definition.module(), &imports, symbol);
            if !references.contains(&resolved) {
                references.push(resolved);
            }
        }
    }
    for reference in references {
        let Some((module, _name)) = locate_source_definition(&reference, sources, loader)? else {
            continue;
        };
        if !parsed.contains_key(&module) {
            let source = &sources[&module];
            parsed.insert(module.clone(), parse_module(&module, source)?);
        }
    }
    Ok(())
}

pub(super) fn resolve_bundle_compile_attributes(
    parsed: &HashMap<String, Vec<Stmt>>,
    definitions: &mut [TypedDefinition],
) {
    let source_definitions = definitions
        .iter()
        .map(|definition| definition.qualified_name().to_owned())
        .collect::<HashSet<_>>();
    let mut singleton_classes = HashMap::<String, String>::new();
    let mut global_symbols = HashMap::<String, SourceType>::new();
    let mut global_attributes = HashMap::<String, CompileAttribute>::new();
    let mut module_compile_values = HashMap::<String, HashMap<String, String>>::new();
    for (module, statements) in parsed {
        let imports = module_imports(module, statements);
        let function_return_types = same_module_function_return_types(statements, module, &imports);
        let mut module_values = HashMap::<String, String>::new();
        let mut module_types = HashMap::<String, SourceType>::new();
        let mut module_aggregate_element_types = HashMap::<String, Vec<SourceType>>::new();
        for statement in statements {
            if let StmtKind::FunctionDef { name, .. } = &statement.node {
                // Module-level functions may be referenced as opaque host
                // callables without becoming reachable CatSeq definitions.
                // Unit is sufficient here: the black-box special form reads
                // only the stable resolved definition identity.
                let canonical = format!("{module}.{name}");
                if !source_definitions.contains(&canonical) {
                    global_symbols.insert(canonical, SourceType::Unit);
                }
                continue;
            }
            if let StmtKind::AnnAssign {
                target,
                annotation,
                value: Some(value),
                ..
            } = &statement.node
            {
                if let ExprKind::Name { id, .. } = &target.node {
                    let normalized = normalized_compile_expression_in_with_known(
                        value,
                        module,
                        &imports,
                        &module_values,
                    );
                    let element_types = inferred_compile_aggregate_element_types(
                        value,
                        module,
                        &imports,
                        &module_types,
                        &module_aggregate_element_types,
                    );
                    if let (Some(source_type), Some(normalized)) = (
                        checked_compile_annotation_type(
                            annotation,
                            Some(value),
                            module,
                            &imports,
                            &module_values,
                        ),
                        normalized.clone(),
                    ) {
                        global_attributes.insert(
                            format!("{module}.{id}"),
                            (
                                source_type.clone(),
                                normalized,
                                element_types.clone().unwrap_or_default(),
                            ),
                        );
                        module_types.insert(id.to_string(), source_type);
                    }
                    if let Some(element_types) = element_types {
                        module_aggregate_element_types.insert(id.to_string(), element_types);
                    }
                    if let Some(normalized) = normalized {
                        module_values.insert(id.to_string(), normalized);
                    }
                }
                continue;
            }
            let StmtKind::Assign { targets, value, .. } = &statement.node else {
                continue;
            };
            let [target] = targets.as_slice() else {
                continue;
            };
            let ExprKind::Name { id, .. } = &target.node else {
                continue;
            };
            let normalized = normalized_compile_expression_in_with_known(
                value,
                module,
                &imports,
                &module_values,
            );
            let source_type =
                inferred_compile_value_type_with_known(value, module, &imports, &module_types)
                    .or_else(|| {
                        inferred_same_module_call_type(
                            value,
                            module,
                            &imports,
                            &function_return_types,
                        )
                    });
            let element_types = inferred_compile_aggregate_element_types(
                value,
                module,
                &imports,
                &module_types,
                &module_aggregate_element_types,
            );
            if let (Some(source_type), Some(normalized)) = (source_type.clone(), normalized.clone())
            {
                global_attributes.insert(
                    format!("{module}.{id}"),
                    (
                        source_type,
                        normalized,
                        element_types.clone().unwrap_or_default(),
                    ),
                );
            }
            if let Some(source_type) = source_type {
                module_types.insert(id.to_string(), source_type);
            }
            if let Some(element_types) = element_types {
                module_aggregate_element_types.insert(id.to_string(), element_types);
            }
            if let Some(normalized) = normalized {
                module_values.insert(id.to_string(), normalized);
            }
            let ExprKind::Call { func, .. } = &value.node else {
                continue;
            };
            let Some(class) = expression_path(func) else {
                continue;
            };
            let resolved_class = resolve_call_path(module, &imports, &class);
            match class.rsplit('.').next() {
                Some("Channel") => {
                    let canonical = format!("{module}.{id}");
                    global_symbols.insert(canonical.clone(), SourceType::Channel);
                    if let Some(local_id) = channel_local_id(value) {
                        global_attributes.insert(
                            format!("{canonical}.local_id"),
                            (SourceType::Int64, local_id, Vec::new()),
                        );
                    }
                }
                Some("Board") if intrinsics::is_board_constructor(&resolved_class) => {
                    global_symbols.insert(format!("{module}.{id}"), SourceType::Board);
                }
                _ => {}
            }
            singleton_classes.insert(format!("{module}.{id}"), resolved_class);
        }
        module_compile_values.insert(module.clone(), module_values);
    }
    let mut class_values = HashMap::<String, HashMap<String, CompileAttribute>>::new();
    for (module, statements) in parsed {
        let imports = module_imports(module, statements);
        let module_attributes = visible_global_attributes(module, &imports, &global_attributes);
        for statement in statements {
            let StmtKind::ClassDef { name, body, .. } = &statement.node else {
                continue;
            };
            let fields = class_fields(
                body,
                module,
                &imports,
                module_compile_values
                    .get(module)
                    .expect("module values were collected above"),
            );
            let mut normalized_fields = fields.values.clone();
            for _ in 0..=normalized_fields.len() {
                let previous = normalized_fields.clone();
                for value in normalized_fields.values_mut() {
                    *value =
                        substitute_normalized_compile_names(value, &previous, &module_attributes);
                }
                if normalized_fields == previous {
                    break;
                }
            }
            let values = normalized_fields
                .into_iter()
                .filter_map(|(field, value)| {
                    fields.types.get(&field).cloned().map(|source_type| {
                        let element_types = fields
                            .aggregate_element_types
                            .get(&field)
                            .cloned()
                            .unwrap_or_default();
                        (field, (source_type, value, element_types))
                    })
                })
                .collect();
            class_values.insert(format!("{module}.{name}"), values);
        }
    }
    for definition in definitions {
        let Some(statements) = parsed.get(definition.module()) else {
            continue;
        };
        let imports = module_imports(definition.module(), statements);
        let mut attributes =
            visible_global_attributes(definition.module(), &imports, &global_attributes);
        if let Some((owner, _method)) = definition.qualified_name().rsplit_once('.')
            && let Some(fields) = class_values.get(owner)
        {
            for (field, value) in fields {
                attributes.insert(format!("self.{field}"), value.clone());
            }
        }
        let mut symbols = HashMap::new();
        for (canonical, source_type) in &global_symbols {
            if let Some(local) = canonical.strip_prefix(&format!("{}.", definition.module()))
                && !local.contains('.')
            {
                symbols.insert(local.to_owned(), (source_type.clone(), canonical.clone()));
            }
            for (alias, imported) in &imports {
                if let Some(suffix) = canonical.strip_prefix(&format!("{imported}.")) {
                    symbols.insert(
                        format!("{alias}.{suffix}"),
                        (source_type.clone(), canonical.clone()),
                    );
                }
            }
        }
        for (local, imported) in &imports {
            if let Some(source_type) = global_symbols.get(imported) {
                symbols.insert(local.clone(), (source_type.clone(), imported.clone()));
            }
            let Some(class) = singleton_classes.get(imported) else {
                continue;
            };
            let Some(fields) = class_values.get(class) else {
                continue;
            };
            for (field, value) in fields {
                attributes.insert(format!("{local}.{field}"), value.clone());
            }
        }
        definition.hir.resolve_compile_attributes(&attributes);
        definition.hir.resolve_global_symbols(&symbols);
    }
}

fn same_module_function_return_types(
    statements: &[Stmt],
    module: &str,
    imports: &HashMap<String, String>,
) -> HashMap<String, SourceType> {
    statements
        .iter()
        .filter_map(|statement| {
            let StmtKind::FunctionDef {
                name,
                returns: Some(returns),
                ..
            } = &statement.node
            else {
                return None;
            };
            class_annotation_type(returns, module, imports)
                .map(|source_type| (format!("{module}.{name}"), source_type))
        })
        .collect()
}

fn inferred_same_module_call_type(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
    function_return_types: &HashMap<String, SourceType>,
) -> Option<SourceType> {
    let ExprKind::Call { func, .. } = &expression.node else {
        return None;
    };
    let path = expression_path(func)?;
    function_return_types
        .get(&resolve_call_path(module, imports, &path))
        .cloned()
}

fn channel_local_id(expression: &Expr) -> Option<String> {
    let ExprKind::Call { args, keywords, .. } = &expression.node else {
        return None;
    };
    let value = keywords
        .iter()
        .find(|keyword| {
            keyword
                .node
                .arg
                .is_some_and(|name| name.to_string() == "local_id")
        })
        .map(|keyword| keyword.node.value.as_ref())
        .or_else(|| args.get(1))?;
    normalized_compile_expression(value)
}

fn visible_global_attributes(
    module: &str,
    imports: &HashMap<String, String>,
    attributes: &HashMap<String, CompileAttribute>,
) -> HashMap<String, CompileAttribute> {
    let mut visible = HashMap::new();
    let prefix = format!("{module}.");
    for (canonical, value) in attributes {
        if let Some(local) = canonical.strip_prefix(&prefix) {
            visible.insert(local.to_owned(), value.clone());
        }
        for (alias, imported) in imports {
            if canonical == imported {
                visible.insert(alias.clone(), value.clone());
            }
            if let Some(suffix) = canonical.strip_prefix(&format!("{imported}.")) {
                visible.insert(format!("{alias}.{suffix}"), value.clone());
            }
        }
    }
    visible
}

fn substitute_normalized_compile_names(
    value: &str,
    fields: &HashMap<String, String>,
    attributes: &HashMap<String, CompileAttribute>,
) -> String {
    let mut resolved = value.to_owned();
    let mut names = fields.iter().collect::<Vec<_>>();
    names.sort_by_key(|(name, _)| std::cmp::Reverse(name.len()));
    for (name, replacement) in names {
        resolved = resolved.replace(&format!("name:{name}"), replacement);
    }
    let mut paths = attributes.iter().collect::<Vec<_>>();
    paths.sort_by_key(|(path, _)| std::cmp::Reverse(path.len()));
    for (path, (_, replacement, _)) in paths {
        resolved = resolved.replace(&format!("path:{path}"), replacement);
    }
    resolved
}
