//! Compile-instance discovery and compile-attribute normalization.

use std::collections::HashMap;

use nac3ast::{Expr, ExprKind, Stmt, StmtKind};

use crate::source_hir::SourceHirKind;

use super::ast_util::{expression_path, parse_module};
use super::compile_values::{
    class_fields, inferred_compile_value_type, normalized_compile_expression,
};
use super::model::{SourceType, TypedCheckError, TypedDefinition};
use super::resolution::{locate_source_definition, module_imports, resolve_call_path};

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
        for node in definition.hir().nodes() {
            if node.kind() != &SourceHirKind::Name {
                continue;
            }
            let Some(imported) = node.symbol().and_then(|name| imports.get(name)) else {
                continue;
            };
            if !references.contains(imported) {
                references.push(imported.clone());
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
    let mut singleton_classes = HashMap::<String, String>::new();
    let mut global_symbols = HashMap::<String, SourceType>::new();
    let mut global_attributes = HashMap::<String, (SourceType, String)>::new();
    for (module, statements) in parsed {
        let imports = module_imports(module, statements);
        for statement in statements {
            let StmtKind::Assign { targets, value, .. } = &statement.node else {
                continue;
            };
            let [target] = targets.as_slice() else {
                continue;
            };
            let ExprKind::Name { id, .. } = &target.node else {
                continue;
            };
            if let (Some(source_type), Some(normalized)) = (
                inferred_compile_value_type(value),
                normalized_compile_expression(value),
            ) {
                global_attributes.insert(format!("{module}.{id}"), (source_type, normalized));
            }
            let ExprKind::Call { func, .. } = &value.node else {
                continue;
            };
            let Some(class) = expression_path(func) else {
                continue;
            };
            match class.rsplit('.').next() {
                Some("Channel") => {
                    let canonical = format!("{module}.{id}");
                    global_symbols.insert(canonical.clone(), SourceType::Channel);
                    if let Some(local_id) = channel_local_id(value) {
                        global_attributes.insert(
                            format!("{canonical}.local_id"),
                            (SourceType::Int64, local_id),
                        );
                    }
                }
                Some("Board") => {
                    global_symbols.insert(format!("{module}.{id}"), SourceType::Board);
                }
                _ => {}
            }
            singleton_classes.insert(
                format!("{module}.{id}"),
                resolve_call_path(module, &imports, &class),
            );
        }
    }
    let mut class_values = HashMap::<String, HashMap<String, (SourceType, String)>>::new();
    for (module, statements) in parsed {
        let imports = module_imports(module, statements);
        let module_attributes = visible_global_attributes(module, &imports, &global_attributes);
        for statement in statements {
            let StmtKind::ClassDef { name, body, .. } = &statement.node else {
                continue;
            };
            let fields = class_fields(body);
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
                    fields
                        .types
                        .get(&field)
                        .cloned()
                        .map(|source_type| (field, (source_type, value)))
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
        }
        for (local, imported) in imports {
            if let Some(source_type) = global_symbols.get(&imported) {
                symbols.insert(local.clone(), (source_type.clone(), imported.clone()));
            }
            let Some(class) = singleton_classes.get(&imported) else {
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
    attributes: &HashMap<String, (SourceType, String)>,
) -> HashMap<String, (SourceType, String)> {
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
    attributes: &HashMap<String, (SourceType, String)>,
) -> String {
    let mut resolved = value.to_owned();
    let mut names = fields.iter().collect::<Vec<_>>();
    names.sort_by_key(|(name, _)| std::cmp::Reverse(name.len()));
    for (name, replacement) in names {
        resolved = resolved.replace(&format!("name:{name}"), replacement);
    }
    let mut paths = attributes.iter().collect::<Vec<_>>();
    paths.sort_by_key(|(path, _)| std::cmp::Reverse(path.len()));
    for (path, (_, replacement)) in paths {
        resolved = resolved.replace(&format!("path:{path}"), replacement);
    }
    resolved
}
