//! Compile-time class fields and normalized static values.

use std::collections::{HashMap, HashSet};

use nac3ast::{Expr, ExprKind, Operator, Stmt, StmtKind};

use crate::native_records;

use super::ast_util::expression_path;
use super::model::SourceType;
use super::resolution::resolve_call_path;

#[derive(Default)]
pub(super) struct ClassFields {
    pub(super) types: HashMap<String, SourceType>,
    pub(super) values: HashMap<String, String>,
    pub(super) aggregate_element_types: HashMap<String, Vec<SourceType>>,
    pub(super) properties: HashSet<String>,
    pub(super) property_elements: HashMap<String, Vec<String>>,
}

pub(super) fn module_compile_values(
    statements: &[Stmt],
    module: &str,
    imports: &HashMap<String, String>,
) -> HashMap<String, String> {
    let mut values = HashMap::new();
    for statement in statements {
        let (target, value) = match &statement.node {
            StmtKind::Assign { targets, value, .. } => {
                let [target] = targets.as_slice() else {
                    continue;
                };
                (target, value.as_ref())
            }
            StmtKind::AnnAssign {
                target,
                value: Some(value),
                ..
            } => (target.as_ref(), value.as_ref()),
            _ => continue,
        };
        let ExprKind::Name { id, .. } = &target.node else {
            continue;
        };
        if let Some(normalized) =
            normalized_compile_expression_in_with_known(value, module, imports, &values)
        {
            values.insert(id.to_string(), normalized);
        }
    }
    values
}

pub(super) fn class_fields(
    statements: &[Stmt],
    module: &str,
    imports: &HashMap<String, String>,
    module_values: &HashMap<String, String>,
) -> ClassFields {
    let mut fields = ClassFields::default();
    for statement in statements {
        match &statement.node {
            StmtKind::AnnAssign {
                target,
                annotation,
                value,
                ..
            } => {
                let ExprKind::Name { id, .. } = &target.node else {
                    continue;
                };
                let mut known_values = module_values.clone();
                known_values.extend(fields.values.clone());
                if let Some(source_type) = checked_compile_annotation_type(
                    annotation,
                    value.as_deref(),
                    module,
                    imports,
                    &known_values,
                ) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(value) = value {
                    if let Some(element_types) = inferred_compile_aggregate_element_types(
                        value,
                        module,
                        imports,
                        &fields.types,
                        &fields.aggregate_element_types,
                    ) {
                        fields
                            .aggregate_element_types
                            .insert(id.to_string(), element_types);
                    }
                    if let Some(normalized) = normalized_compile_expression_in_with_known(
                        value,
                        module,
                        imports,
                        &known_values,
                    ) {
                        fields.values.insert(id.to_string(), normalized);
                    }
                }
            }
            StmtKind::Assign { targets, value, .. } => {
                let [target] = targets.as_slice() else {
                    continue;
                };
                let ExprKind::Name { id, .. } = &target.node else {
                    continue;
                };
                let mut known_values = module_values.clone();
                known_values.extend(fields.values.clone());
                if let Some(source_type) =
                    inferred_compile_value_type_with_known(value, module, imports, &fields.types)
                {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(element_types) = inferred_compile_aggregate_element_types(
                    value,
                    module,
                    imports,
                    &fields.types,
                    &fields.aggregate_element_types,
                ) {
                    fields
                        .aggregate_element_types
                        .insert(id.to_string(), element_types);
                }
                if let Some(normalized) = normalized_compile_expression_in_with_known(
                    value,
                    module,
                    imports,
                    &known_values,
                ) {
                    fields.values.insert(id.to_string(), normalized);
                }
            }
            StmtKind::FunctionDef {
                name,
                body,
                decorator_list,
                ..
            } if decorator_list.iter().any(|decorator| {
                expression_path(decorator)
                    .is_some_and(|path| path.rsplit('.').next() == Some("property"))
            }) =>
            {
                fields.properties.insert(name.to_string());
                if let Some(elements) = returned_static_elements(body) {
                    fields.property_elements.insert(name.to_string(), elements);
                }
            }
            _ => {}
        }
    }
    fields
}

fn returned_static_elements(body: &[Stmt]) -> Option<Vec<String>> {
    let value = body.iter().find_map(|statement| match &statement.node {
        StmtKind::Return {
            value: Some(value), ..
        } => Some(value.as_ref()),
        _ => None,
    })?;
    let elements = match &value.node {
        ExprKind::List { elts, .. } | ExprKind::Tuple { elts, .. } => elts,
        _ => return None,
    };
    elements.iter().map(expression_path).collect()
}

pub(super) fn inferred_compile_value_type(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
) -> Option<SourceType> {
    match &expression.node {
        ExprKind::Constant { value, .. } => match value {
            nac3ast::Constant::Bool(_) => Some(SourceType::Bool),
            nac3ast::Constant::Int(_) => Some(SourceType::Int64),
            nac3ast::Constant::Float(_) => Some(SourceType::Float64),
            nac3ast::Constant::Str(_) => Some(SourceType::String),
            _ => None,
        },
        ExprKind::Call { func, .. } => expression_path(func).and_then(|path| {
            let resolved = resolve_call_path(module, imports, &path);
            if resolved == "catseq.time_utils.cycles" {
                Some(SourceType::Duration)
            } else {
                native_records::schema_for_constructor(&resolved)
                    .map(|schema| SourceType::NativeRecord(schema.name().to_owned()))
            }
        }),
        ExprKind::Name { id, .. }
            if matches!(
                resolve_call_path(module, imports, id.to_string().as_str()).as_str(),
                "catseq.time_utils.s"
                    | "catseq.time_utils.ms"
                    | "catseq.time_utils.us"
                    | "catseq.time_utils.ns"
            ) =>
        {
            Some(SourceType::Duration)
        }
        ExprKind::Attribute { .. }
            if expression_path(expression)
                .map(|path| resolve_call_path(module, imports, &path))
                .is_some_and(|resolved| {
                    matches!(
                        resolved.as_str(),
                        "catseq.time_utils.s"
                            | "catseq.time_utils.ms"
                            | "catseq.time_utils.us"
                            | "catseq.time_utils.ns"
                    )
                }) =>
        {
            Some(SourceType::Duration)
        }
        ExprKind::BinOp { left, op, right } => {
            let left = inferred_compile_value_type(left, module, imports)?;
            let right = inferred_compile_value_type(right, module, imports)?;
            match (op, &left, &right) {
                (Operator::Add | Operator::Sub, SourceType::Duration, SourceType::Duration)
                | (Operator::Mult, SourceType::Duration, SourceType::Int64 | SourceType::Float64)
                | (Operator::Mult, SourceType::Int64 | SourceType::Float64, SourceType::Duration)
                | (Operator::Div, SourceType::Duration, SourceType::Int64 | SourceType::Float64) => {
                    Some(SourceType::Duration)
                }
                (Operator::Div, SourceType::Duration, SourceType::Duration) => {
                    Some(SourceType::Float64)
                }
                (_, SourceType::Float64, SourceType::Int64 | SourceType::Float64)
                | (_, SourceType::Int64, SourceType::Float64) => Some(SourceType::Float64),
                (_, SourceType::Int64, SourceType::Int64) => Some(SourceType::Int64),
                _ => None,
            }
        }
        ExprKind::UnaryOp { operand, .. } => inferred_compile_value_type(operand, module, imports),
        ExprKind::Tuple { .. } | ExprKind::List { .. } => Some(SourceType::FixedAggregate),
        _ => None,
    }
}

pub(super) fn inferred_compile_value_type_with_known(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
    known_types: &HashMap<String, SourceType>,
) -> Option<SourceType> {
    if let ExprKind::Name { id, .. } = &expression.node
        && let Some(source_type) = known_types.get(&id.to_string())
    {
        return Some(source_type.clone());
    }
    inferred_compile_value_type(expression, module, imports)
}

pub(super) fn inferred_compile_aggregate_element_types(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
    known_types: &HashMap<String, SourceType>,
    known_aggregate_element_types: &HashMap<String, Vec<SourceType>>,
) -> Option<Vec<SourceType>> {
    let elements = match &expression.node {
        ExprKind::Tuple { elts, .. } | ExprKind::List { elts, .. } => elts,
        ExprKind::Name { id, .. } => {
            return known_aggregate_element_types.get(&id.to_string()).cloned();
        }
        _ => return None,
    };
    elements
        .iter()
        .map(|element| {
            inferred_compile_value_type_with_known(element, module, imports, known_types).or_else(
                || {
                    matches!(
                        element.node,
                        ExprKind::Constant {
                            value: nac3ast::Constant::None,
                            ..
                        }
                    )
                    .then_some(SourceType::Unit)
                },
            )
        })
        .collect()
}

pub(super) fn normalized_compile_expression(expression: &Expr) -> Option<String> {
    normalized_compile_expression_with_context(expression, None, None)
}

pub(super) fn normalized_compile_expression_in(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
) -> Option<String> {
    normalized_compile_expression_with_context(expression, Some((module, imports)), None)
}

pub(super) fn normalized_compile_expression_in_with_known(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
    known_values: &HashMap<String, String>,
) -> Option<String> {
    normalized_compile_expression_with_context(
        expression,
        Some((module, imports)),
        Some(known_values),
    )
}

fn normalized_compile_expression_with_context(
    expression: &Expr,
    context: Option<(&str, &HashMap<String, String>)>,
    known_values: Option<&HashMap<String, String>>,
) -> Option<String> {
    match &expression.node {
        ExprKind::Constant { value, .. } => Some(format!("constant:{value:?}")),
        ExprKind::Name { id, .. } => {
            let name = id.to_string();
            if let Some(value) = known_values.and_then(|values| values.get(&name)) {
                return Some(value.clone());
            }
            let name = context.map_or(name.clone(), |(module, imports)| {
                let resolved = resolve_call_path(module, imports, &name);
                if matches!(
                    resolved.as_str(),
                    "catseq.time_utils.s"
                        | "catseq.time_utils.ms"
                        | "catseq.time_utils.us"
                        | "catseq.time_utils.ns"
                ) {
                    resolved
                } else {
                    name.clone()
                }
            });
            Some(format!("name:{name}"))
        }
        ExprKind::Attribute { .. } => expression_path(expression).map(|path| {
            let resolved =
                context.map(|(module, imports)| resolve_call_path(module, imports, &path));
            if resolved.as_deref().is_some_and(|resolved| {
                matches!(
                    resolved,
                    "catseq.time_utils.s"
                        | "catseq.time_utils.ms"
                        | "catseq.time_utils.us"
                        | "catseq.time_utils.ns"
                )
            }) {
                format!("name:{}", resolved.expect("checked above"))
            } else {
                format!("path:{path}")
            }
        }),
        ExprKind::BinOp { left, op, right } => Some(format!(
            "bin:{op:?}({},{})",
            normalized_compile_expression_with_context(left, context, known_values)?,
            normalized_compile_expression_with_context(right, context, known_values)?
        )),
        ExprKind::UnaryOp { op, operand } => Some(format!(
            "unary:{op:?}({})",
            normalized_compile_expression_with_context(operand, context, known_values)?
        )),
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            let function = expression_path(func)?;
            let function = context.map_or(function.clone(), |(module, imports)| {
                resolve_call_path(module, imports, &function)
            });
            let args = args
                .iter()
                .map(|argument| {
                    normalized_compile_expression_with_context(argument, context, known_values)
                })
                .collect::<Option<Vec<_>>>()?;
            let keywords = keywords
                .iter()
                .map(|keyword| {
                    Some(format!(
                        "{}={}",
                        keyword
                            .node
                            .arg
                            .map_or("**".to_owned(), |arg| arg.to_string()),
                        normalized_compile_expression_with_context(
                            &keyword.node.value,
                            context,
                            known_values,
                        )?
                    ))
                })
                .collect::<Option<Vec<_>>>()?;
            Some(format!(
                "call:{function}({};{})",
                args.join(","),
                keywords.join(",")
            ))
        }
        ExprKind::Tuple { elts, .. } | ExprKind::List { elts, .. } => {
            let values = elts
                .iter()
                .map(|element| {
                    normalized_compile_expression_with_context(element, context, known_values)
                })
                .collect::<Option<Vec<_>>>()?;
            Some(format!("aggregate:[{}]", values.join(",")))
        }
        _ => None,
    }
}

pub(super) fn class_annotation_type(
    annotation: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
) -> Option<SourceType> {
    if let ExprKind::Subscript { value, slice, .. } = &annotation.node {
        let container = expression_path(value)?;
        let leaf = container.rsplit('.').next().unwrap_or(&container);
        return match leaf {
            "ClassVar" => class_annotation_type(slice, module, imports),
            "ExpParam" | "ScanParam" => class_annotation_type(slice, module, imports)
                .map(|inner| SourceType::ScanParam(Box::new(inner))),
            "tuple" | "Tuple" | "list" | "List" => Some(SourceType::FixedAggregate),
            _ => None,
        };
    }
    let path = expression_path(annotation)?;
    match path.rsplit('.').next().unwrap_or(&path) {
        "bool" | "Bool" => Some(SourceType::Bool),
        "int" | "Int64" => Some(SourceType::Int64),
        "float" | "Float64" => Some(SourceType::Float64),
        "Duration" => Some(SourceType::Duration),
        "str" | "String" => Some(SourceType::String),
        "Morphism" => Some(SourceType::Morphism),
        "MorphismDef" | "MorphismTemplate" => Some(SourceType::MorphismTemplate),
        "Channel" => Some(SourceType::Channel),
        "Board" => Some(SourceType::Board),
        _ => {
            let resolved = resolve_call_path(module, imports, &path);
            native_records::schema_for_constructor(&resolved)
                .map(|schema| SourceType::NativeRecord(schema.name().to_owned()))
        }
    }
}

pub(super) fn checked_compile_annotation_type(
    annotation: &Expr,
    initializer: Option<&Expr>,
    module: &str,
    imports: &HashMap<String, String>,
    known_values: &HashMap<String, String>,
) -> Option<SourceType> {
    let annotated = class_annotation_type(annotation, module, imports)?;
    if matches!(annotated, SourceType::NativeRecord(_)) {
        match initializer.map_or(CompileConstructor::NotConstructor, |initializer| {
            compile_constructor(initializer, module, imports, known_values)
        }) {
            CompileConstructor::Registered(found) if found != annotated => return None,
            CompileConstructor::Unregistered => return None,
            _ => {}
        }
    }
    Some(annotated)
}

enum CompileConstructor {
    NotConstructor,
    Registered(SourceType),
    Unregistered,
}

fn compile_constructor(
    initializer: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
    known_values: &HashMap<String, String>,
) -> CompileConstructor {
    let Some(normalized) = normalized_compile_expression_in(initializer, module, imports) else {
        return CompileConstructor::NotConstructor;
    };
    normalized_compile_constructor(&normalized, known_values, &mut HashSet::new())
}

fn normalized_compile_constructor(
    normalized: &str,
    known_values: &HashMap<String, String>,
    visited: &mut HashSet<String>,
) -> CompileConstructor {
    if let Some(name) = normalized.strip_prefix("name:") {
        if !visited.insert(name.to_owned()) {
            return CompileConstructor::NotConstructor;
        }
        return known_values
            .get(name)
            .map_or(CompileConstructor::NotConstructor, |value| {
                normalized_compile_constructor(value, known_values, visited)
            });
    }
    let Some(call) = normalized.strip_prefix("call:") else {
        return CompileConstructor::NotConstructor;
    };
    let Some(open) = call.find('(') else {
        return CompileConstructor::Unregistered;
    };
    native_records::schema_for_constructor(&call[..open])
        .map_or(CompileConstructor::Unregistered, |schema| {
            CompileConstructor::Registered(SourceType::NativeRecord(schema.name().to_owned()))
        })
}
