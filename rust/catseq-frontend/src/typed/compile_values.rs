//! Compile-time class fields and normalized static values.

use std::collections::{HashMap, HashSet};

use nac3ast::{Expr, ExprKind, Stmt, StmtKind};

use super::ast_util::expression_path;
use super::model::SourceType;

#[derive(Default)]
pub(super) struct ClassFields {
    pub(super) types: HashMap<String, SourceType>,
    pub(super) values: HashMap<String, String>,
    pub(super) properties: HashSet<String>,
    pub(super) property_elements: HashMap<String, Vec<String>>,
}

pub(super) fn class_fields(statements: &[Stmt]) -> ClassFields {
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
                    if let Some(normalized) = normalized_compile_expression(value) {
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
                if let Some(source_type) = inferred_compile_value_type(value) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(normalized) = normalized_compile_expression(value) {
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

pub(super) fn inferred_compile_value_type(expression: &Expr) -> Option<SourceType> {
    match &expression.node {
        ExprKind::Constant { value, .. } => match value {
            nac3ast::Constant::Bool(_) => Some(SourceType::Bool),
            nac3ast::Constant::Int(_) => Some(SourceType::Int64),
            nac3ast::Constant::Float(_) => Some(SourceType::Float64),
            nac3ast::Constant::Str(_) => Some(SourceType::String),
            _ => None,
        },
        ExprKind::Call { func, .. } => expression_path(func).map(|path| {
            SourceType::NativeRecord(path.rsplit('.').next().unwrap_or(&path).to_owned())
        }),
        ExprKind::Tuple { .. } | ExprKind::List { .. } => Some(SourceType::FixedAggregate),
        _ => None,
    }
}

pub(super) fn normalized_compile_expression(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Constant { value, .. } => Some(format!("constant:{value:?}")),
        ExprKind::Name { id, .. } => Some(format!("name:{id}")),
        ExprKind::Attribute { .. } => {
            expression_path(expression).map(|path| format!("path:{path}"))
        }
        ExprKind::BinOp { left, op, right } => Some(format!(
            "bin:{op:?}({},{})",
            normalized_compile_expression(left)?,
            normalized_compile_expression(right)?
        )),
        ExprKind::UnaryOp { op, operand } => Some(format!(
            "unary:{op:?}({})",
            normalized_compile_expression(operand)?
        )),
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            let function = expression_path(func)?;
            let args = args
                .iter()
                .map(normalized_compile_expression)
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
                        normalized_compile_expression(&keyword.node.value)?
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
                .map(normalized_compile_expression)
                .collect::<Option<Vec<_>>>()?;
            Some(format!("aggregate:[{}]", values.join(",")))
        }
        _ => None,
    }
}

fn class_annotation_type(annotation: &Expr) -> Option<SourceType> {
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
