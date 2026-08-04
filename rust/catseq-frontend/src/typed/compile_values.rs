//! Compile-time class fields and normalized static values.

use std::collections::{HashMap, HashSet};

use nac3ast::{Expr, ExprKind, Operator, Stmt, StmtKind};

use super::ast_util::expression_path;
use super::model::SourceType;
use super::resolution::resolve_call_path;

#[derive(Default)]
pub(super) struct ClassFields {
    pub(super) types: HashMap<String, SourceType>,
    pub(super) values: HashMap<String, String>,
    pub(super) properties: HashSet<String>,
    pub(super) property_elements: HashMap<String, Vec<String>>,
}

pub(super) fn class_fields(
    statements: &[Stmt],
    module: &str,
    imports: &HashMap<String, String>,
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
                if let Some(source_type) = class_annotation_type(annotation) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(value) = value {
                    if let Some(normalized) =
                        normalized_compile_expression_in(value, module, imports)
                    {
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
                if let Some(source_type) = inferred_compile_value_type(value, module, imports) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(normalized) = normalized_compile_expression_in(value, module, imports) {
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
        ExprKind::Call { func, .. } => expression_path(func).map(|path| {
            let resolved = resolve_call_path(module, imports, &path);
            let leaf = path.rsplit('.').next().unwrap_or(&path);
            if resolved == "catseq.time_utils.cycles" {
                SourceType::Duration
            } else {
                SourceType::NativeRecord(leaf.to_owned())
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

pub(super) fn normalized_compile_expression(expression: &Expr) -> Option<String> {
    normalized_compile_expression_with_context(expression, None)
}

pub(super) fn normalized_compile_expression_in(
    expression: &Expr,
    module: &str,
    imports: &HashMap<String, String>,
) -> Option<String> {
    normalized_compile_expression_with_context(expression, Some((module, imports)))
}

fn normalized_compile_expression_with_context(
    expression: &Expr,
    context: Option<(&str, &HashMap<String, String>)>,
) -> Option<String> {
    match &expression.node {
        ExprKind::Constant { value, .. } => Some(format!("constant:{value:?}")),
        ExprKind::Name { id, .. } => {
            let name = id.to_string();
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
            normalized_compile_expression_with_context(left, context)?,
            normalized_compile_expression_with_context(right, context)?
        )),
        ExprKind::UnaryOp { op, operand } => Some(format!(
            "unary:{op:?}({})",
            normalized_compile_expression_with_context(operand, context)?
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
                .map(|argument| normalized_compile_expression_with_context(argument, context))
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
                        normalized_compile_expression_with_context(&keyword.node.value, context)?
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
                .map(|element| normalized_compile_expression_with_context(element, context))
                .collect::<Option<Vec<_>>>()?;
            Some(format!("aggregate:[{}]", values.join(",")))
        }
        _ => None,
    }
}

pub(super) fn class_annotation_type(annotation: &Expr) -> Option<SourceType> {
    if let ExprKind::Subscript { value, slice, .. } = &annotation.node {
        let container = expression_path(value)?;
        let leaf = container.rsplit('.').next().unwrap_or(&container);
        return match leaf {
            "ClassVar" => class_annotation_type(slice),
            "ExpParam" | "ScanParam" => {
                class_annotation_type(slice).map(|inner| SourceType::ScanParam(Box::new(inner)))
            }
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
        schema => Some(SourceType::NativeRecord(schema.to_owned())),
    }
}
