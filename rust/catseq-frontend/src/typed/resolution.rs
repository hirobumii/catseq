//! Python module imports and source-definition resolution.

use std::collections::HashMap;

use nac3ast::{ExprKind, Stmt, StmtKind};

use super::ast_util::{expression_path, parse_module};
use super::model::TypedCheckError;

pub(super) fn module_imports(module_name: &str, statements: &[Stmt]) -> HashMap<String, String> {
    let mut imports = HashMap::new();
    for statement in statements {
        match &statement.node {
            StmtKind::Import { names, .. } => {
                for alias in names {
                    let imported = alias.name.to_string();
                    let local = alias.asname.map_or_else(
                        || imported.split('.').next().unwrap_or(&imported).to_owned(),
                        |name| name.to_string(),
                    );
                    imports.insert(local, imported);
                }
            }
            StmtKind::ImportFrom {
                module,
                names,
                level,
                ..
            } => {
                let module = module.map(|name| name.to_string());
                let imported_module =
                    absolute_import_module(module_name, *level, module.as_deref());
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
            _ => {}
        }
    }
    imports
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

pub(super) fn resolve_call_path(
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
) -> Result<String, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let Some((module_name, lexical_name)) = locate_source_definition(resolved, sources, loader)?
    else {
        return Ok(resolved.to_owned());
    };
    let Some((instance_name, method_name)) = lexical_name.split_once('.') else {
        return Ok(resolved.to_owned());
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
        return Ok(resolved.to_owned());
    };
    Ok(format!("{class_path}.{method_name}"))
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
