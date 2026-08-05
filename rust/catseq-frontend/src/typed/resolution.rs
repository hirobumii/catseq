//! Python module imports and source-definition resolution.

use std::collections::HashMap;

use nac3ast::{ExcepthandlerKind, Expr, ExprKind, Stmt, StmtKind};

use super::ast_util::{expression_path, parse_module, push_expression_analysis_children};
use super::model::TypedCheckError;

pub(super) fn module_imports(module_name: &str, statements: &[Stmt]) -> HashMap<String, String> {
    let mut imports = HashMap::new();
    for statement in statements {
        update_visible_imports(module_name, &mut imports, statement);
    }
    imports
}

pub(super) fn update_visible_imports(
    module_name: &str,
    imports: &mut HashMap<String, String>,
    statement: &Stmt,
) {
    match &statement.node {
        StmtKind::Import { names, .. } => {
            for alias in names {
                let imported = alias.name.to_string();
                let (local, resolved) = alias.asname.map_or_else(
                    || {
                        let root = imported.split('.').next().unwrap_or(&imported).to_owned();
                        (root.clone(), root)
                    },
                    |name| (name.to_string(), imported.clone()),
                );
                imports.insert(local, resolved);
            }
        }
        StmtKind::ImportFrom {
            module,
            names,
            level,
            ..
        } => {
            let module = module.map(|name| name.to_string());
            let imported_module = absolute_import_module(module_name, *level, module.as_deref());
            for alias in names {
                let imported_name = alias.name.to_string();
                let local = alias
                    .asname
                    .map_or_else(|| imported_name.clone(), |name| name.to_string());
                let resolved = if imported_module.is_empty() {
                    imported_name
                } else {
                    format!("{imported_module}.{imported_name}")
                };
                imports.insert(local, resolved);
            }
        }
        _ => remove_statement_import_bindings(imports, statement),
    }
}

fn remove_statement_import_bindings(imports: &mut HashMap<String, String>, statement: &Stmt) {
    match &statement.node {
        StmtKind::Import { names, .. } => {
            for alias in names {
                let imported = alias.name.to_string();
                let local = alias.asname.map_or_else(
                    || imported.split('.').next().unwrap_or(&imported).to_owned(),
                    |name| name.to_string(),
                );
                imports.remove(&local);
            }
        }
        StmtKind::ImportFrom { names, .. } => {
            for alias in names {
                let local = alias
                    .asname
                    .map_or_else(|| alias.name.to_string(), |name| name.to_string());
                imports.remove(&local);
            }
        }
        StmtKind::Assign { targets, value, .. } => {
            for target in targets {
                remove_import_bindings(imports, target);
            }
            remove_expression_import_bindings(imports, value);
        }
        StmtKind::AnnAssign { target, value, .. } => {
            remove_import_bindings(imports, target);
            if let Some(value) = value {
                remove_expression_import_bindings(imports, value);
            }
        }
        StmtKind::AugAssign { target, value, .. } => {
            remove_import_bindings(imports, target);
            remove_expression_import_bindings(imports, value);
        }
        StmtKind::Delete { targets, .. } => {
            for target in targets {
                remove_import_bindings(imports, target);
            }
        }
        StmtKind::FunctionDef {
            name,
            args,
            decorator_list,
            returns,
            ..
        }
        | StmtKind::AsyncFunctionDef {
            name,
            args,
            decorator_list,
            returns,
            ..
        } => {
            imports.remove(name.to_string().as_str());
            remove_function_header_import_bindings(
                imports,
                args,
                decorator_list,
                returns.as_deref(),
            );
        }
        StmtKind::ClassDef {
            name,
            bases,
            keywords,
            decorator_list,
            ..
        } => {
            imports.remove(name.to_string().as_str());
            for expression in decorator_list.iter().chain(bases) {
                remove_expression_import_bindings(imports, expression);
            }
            for keyword in keywords {
                remove_expression_import_bindings(imports, &keyword.node.value);
            }
        }
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            remove_expression_import_bindings(imports, test);
            remove_suite_import_bindings(imports, body);
            remove_suite_import_bindings(imports, orelse);
        }
        StmtKind::For {
            target,
            iter,
            body,
            orelse,
            ..
        }
        | StmtKind::AsyncFor {
            target,
            iter,
            body,
            orelse,
            ..
        } => {
            remove_import_bindings(imports, target);
            remove_expression_import_bindings(imports, iter);
            remove_suite_import_bindings(imports, body);
            remove_suite_import_bindings(imports, orelse);
        }
        StmtKind::With { items, body, .. } | StmtKind::AsyncWith { items, body, .. } => {
            for item in items {
                remove_expression_import_bindings(imports, &item.context_expr);
                if let Some(target) = &item.optional_vars {
                    remove_import_bindings(imports, target);
                }
            }
            remove_suite_import_bindings(imports, body);
        }
        StmtKind::Try {
            body,
            handlers,
            orelse,
            finalbody,
            ..
        } => {
            remove_suite_import_bindings(imports, body);
            for handler in handlers {
                let ExcepthandlerKind::ExceptHandler { type_, name, body } = &handler.node;
                if let Some(type_) = type_ {
                    remove_expression_import_bindings(imports, type_);
                }
                if let Some(name) = name {
                    imports.remove(name.to_string().as_str());
                }
                remove_suite_import_bindings(imports, body);
            }
            remove_suite_import_bindings(imports, orelse);
            remove_suite_import_bindings(imports, finalbody);
        }
        StmtKind::Expr { value, .. } => remove_expression_import_bindings(imports, value),
        StmtKind::Assert { test, msg, .. } => {
            remove_expression_import_bindings(imports, test);
            if let Some(msg) = msg {
                remove_expression_import_bindings(imports, msg);
            }
        }
        StmtKind::Raise { exc, cause, .. } => {
            if let Some(exc) = exc {
                remove_expression_import_bindings(imports, exc);
            }
            if let Some(cause) = cause {
                remove_expression_import_bindings(imports, cause);
            }
        }
        StmtKind::Return { value, .. } => {
            if let Some(value) = value {
                remove_expression_import_bindings(imports, value);
            }
        }
        StmtKind::Global { .. }
        | StmtKind::Nonlocal { .. }
        | StmtKind::Pass { .. }
        | StmtKind::Break { .. }
        | StmtKind::Continue { .. } => {}
    }
}

fn remove_suite_import_bindings(imports: &mut HashMap<String, String>, statements: &[Stmt]) {
    for statement in statements {
        remove_statement_import_bindings(imports, statement);
    }
}

fn remove_function_header_import_bindings(
    imports: &mut HashMap<String, String>,
    arguments: &nac3ast::Arguments,
    decorators: &[Expr],
    returns: Option<&Expr>,
) {
    for expression in decorators
        .iter()
        .chain(arguments.defaults.iter())
        .chain(arguments.kw_defaults.iter().flatten().map(Box::as_ref))
    {
        remove_expression_import_bindings(imports, expression);
    }
    for argument in arguments
        .posonlyargs
        .iter()
        .chain(&arguments.args)
        .chain(&arguments.kwonlyargs)
        .chain(arguments.vararg.iter().map(Box::as_ref))
        .chain(arguments.kwarg.iter().map(Box::as_ref))
    {
        if let Some(annotation) = &argument.node.annotation {
            remove_expression_import_bindings(imports, annotation);
        }
    }
    if let Some(returns) = returns {
        remove_expression_import_bindings(imports, returns);
    }
}

fn remove_expression_import_bindings(imports: &mut HashMap<String, String>, expression: &Expr) {
    let mut pending = vec![expression];
    while let Some(expression) = pending.pop() {
        if matches!(&expression.node, ExprKind::Lambda { .. }) {
            continue;
        }
        if let ExprKind::NamedExpr { target, .. } = &expression.node {
            remove_import_bindings(imports, target);
        }
        push_expression_analysis_children(expression, &mut pending);
    }
}

fn remove_import_bindings(imports: &mut HashMap<String, String>, target: &Expr) {
    match &target.node {
        ExprKind::Name { id, .. } => {
            imports.remove(id.to_string().as_str());
        }
        ExprKind::Tuple { elts, .. } | ExprKind::List { elts, .. } => {
            for element in elts {
                remove_import_bindings(imports, element);
            }
        }
        ExprKind::Starred { value, .. } => remove_import_bindings(imports, value),
        _ => {}
    }
}

fn absolute_import_module(current: &str, level: usize, module: Option<&str>) -> String {
    if level == 0 {
        return module.unwrap_or_default().to_owned();
    }
    let mut package: Vec<_> = current.split('.').collect();
    package.pop();
    for _ in 1..level {
        package.pop();
    }
    if let Some(module) = module {
        package.extend(module.split('.'));
    }
    package.join(".")
}

pub(crate) fn resolve_call_path(
    current_module: &str,
    imports: &HashMap<String, String>,
    call: &str,
) -> String {
    let mut segments = call.split('.');
    let first = segments.next().unwrap_or(call);
    if let Some(imported) = imports.get(first) {
        let remainder = segments.collect::<Vec<_>>().join(".");
        if remainder.is_empty() {
            imported.clone()
        } else {
            format!("{imported}.{remainder}")
        }
    } else {
        format!("{current_module}.{call}")
    }
}

pub(super) fn resolve_self_call(current_definition: &str, call: &str) -> String {
    let Some(method) = call.strip_prefix("self.") else {
        return call.to_owned();
    };
    let Some((class_name, _)) = current_definition.rsplit_once('.') else {
        return call.to_owned();
    };
    format!("{class_name}.{method}")
}

pub(super) fn load_source_module<F>(
    module: &str,
    sources: &mut HashMap<String, String>,
    loader: &mut F,
) -> Result<bool, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    if sources.contains_key(module) {
        return Ok(true);
    }
    let source = loader(module).map_err(|message| TypedCheckError::SourceLoad {
        module: module.to_owned(),
        message,
    })?;
    if let Some(source) = source {
        sources.insert(module.to_owned(), source);
        Ok(true)
    } else {
        Ok(false)
    }
}

pub(super) fn locate_source_definition<F>(
    resolved: &str,
    sources: &mut HashMap<String, String>,
    loader: &mut F,
) -> Result<Option<(String, String)>, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    for (separator, _) in resolved.rmatch_indices('.') {
        let module = &resolved[..separator];
        if load_source_module(module, sources, loader)? {
            return Ok(Some((
                module.to_owned(),
                resolved[separator + 1..].to_owned(),
            )));
        }
    }
    Ok(None)
}

pub(super) fn resolve_compile_instance_call<F>(
    sources: &mut HashMap<String, String>,
    parsed: &mut HashMap<String, Vec<Stmt>>,
    loader: &mut F,
    resolved: &str,
) -> Result<(String, Option<String>), TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let Some((module_name, lexical_name)) = locate_source_definition(resolved, sources, loader)?
    else {
        return Ok((resolved.to_owned(), None));
    };
    let Some((instance_name, method_name)) = lexical_name.split_once('.') else {
        return Ok((resolved.to_owned(), None));
    };
    if !parsed.contains_key(&module_name) {
        let source = &sources[&module_name];
        parsed.insert(module_name.clone(), parse_module(&module_name, source)?);
    }
    let suite = &parsed[&module_name];
    let imports = module_imports(&module_name, suite);
    let Some(class_path) =
        module_compile_instances(&module_name, suite, &imports).remove(instance_name)
    else {
        return Ok((resolved.to_owned(), None));
    };
    Ok((
        format!("{class_path}.{method_name}"),
        Some(format!("{module_name}.{instance_name}")),
    ))
}

fn module_compile_instances(
    module_name: &str,
    statements: &[Stmt],
    imports: &HashMap<String, String>,
) -> HashMap<String, String> {
    let mut instances = HashMap::new();
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
        let ExprKind::Call { func, .. } = &value.node else {
            continue;
        };
        let Some(class_path) = expression_path(func) else {
            continue;
        };
        instances.insert(
            id.to_string(),
            resolve_call_path(module_name, imports, &class_path),
        );
    }
    instances
}
