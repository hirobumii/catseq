//! Function signature and annotation type analysis.

use nac3ast::{Arg, Arguments, Expr, ExprKind, Stmt};

use super::ast_util::{
    expression_path, push_expression_analysis_children, push_statement_analysis_children,
};
use super::compile_values::normalized_compile_expression;
use super::model::{SourceType, TypeSignature, TypedCheckError, TypedParameter};

pub(super) fn signature(
    file_name: &str,
    definition: &str,
    class_name: Option<&str>,
    arguments: &Arguments,
    body: &[Stmt],
    returns: Option<&Expr>,
) -> Result<TypeSignature, TypedCheckError> {
    let mut parameters = Vec::new();
    let positional = arguments
        .posonlyargs
        .iter()
        .chain(&arguments.args)
        .collect::<Vec<_>>();
    let default_start = positional.len().saturating_sub(arguments.defaults.len());
    for (index, argument) in positional.into_iter().enumerate() {
        let default = index
            .checked_sub(default_start)
            .and_then(|index| arguments.defaults.get(index));
        if let Some(parameter) =
            parameter(file_name, definition, class_name, argument, body, default)?
        {
            parameters.push(parameter);
        }
    }
    for (argument, default) in arguments.kwonlyargs.iter().zip(&arguments.kw_defaults) {
        if let Some(parameter) = parameter(
            file_name,
            definition,
            class_name,
            argument,
            body,
            default.as_deref(),
        )? {
            parameters.push(parameter);
        }
    }
    let return_type = match returns {
        Some(annotation) => annotation_type(file_name, definition, annotation)?,
        None => SourceType::Unit,
    };
    Ok(TypeSignature {
        parameters,
        return_type,
    })
}

fn parameter(
    file_name: &str,
    definition: &str,
    class_name: Option<&str>,
    argument: &Arg,
    body: &[Stmt],
    default: Option<&Expr>,
) -> Result<Option<TypedParameter>, TypedCheckError> {
    let name = argument.node.arg.to_string();
    let source_type = match argument.node.annotation.as_deref() {
        Some(annotation) if is_legacy_state_annotation(annotation) => return Ok(None),
        Some(annotation) => annotation_type(file_name, definition, annotation)?,
        None if name == "self" => {
            SourceType::Instance(class_name.unwrap_or("<unknown>").to_owned())
        }
        // In 0.2 this conventional parameter threaded a Python OASM assembler
        // solely to `repeat_morphism`.  The 0.3 frontend normalizes that call to
        // a native Loop Region, so the migration-only handle must disappear
        // before Typed Source HIR instead of acquiring an arbitrary-object type.
        None if is_legacy_sequence_handle(&name, body) => return Ok(None),
        None if infer_unannotated_parameter(&name, body).is_some() => {
            infer_unannotated_parameter(&name, body).expect("checked above")
        }
        None => {
            return Err(TypedCheckError::MissingAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                parameter: name,
            });
        }
    };
    Ok(Some(TypedParameter {
        name,
        source_type,
        default_value: default.and_then(normalized_compile_expression),
    }))
}

fn infer_unannotated_parameter(name: &str, body: &[Stmt]) -> Option<SourceType> {
    let mut statements: Vec<_> = body.iter().collect();
    let mut expressions = Vec::<&Expr>::new();
    while let Some(statement) = statements.pop() {
        push_statement_analysis_children(statement, &mut statements, &mut expressions);
    }
    while let Some(expression) = expressions.pop() {
        match &expression.node {
            ExprKind::BinOp {
                left, op, right, ..
            } if !matches!(op, nac3ast::Operator::RShift | nac3ast::Operator::BitOr) => {
                let is_parameter = |expression: &Expr| {
                    matches!(&expression.node, ExprKind::Name { id, .. } if id.to_string() == name)
                };
                if is_parameter(left) || is_parameter(right) {
                    return Some(SourceType::Float64);
                }
            }
            ExprKind::Call { func, args, .. }
                if expression_path(func).as_deref() == Some("range")
                    && args.iter().any(|argument| {
                        matches!(&argument.node, ExprKind::Name { id, .. } if id.to_string() == name)
                    }) =>
            {
                return Some(SourceType::Int64);
            }
            _ => {}
        }
        push_expression_analysis_children(expression, &mut expressions);
    }
    None
}

fn is_legacy_state_annotation(annotation: &Expr) -> bool {
    expression_path(annotation).is_some_and(|path| {
        matches!(
            path.rsplit('.').next(),
            Some("State" | "StateMap" | "MorphismEndStateView")
        )
    })
}

fn is_legacy_sequence_handle(name: &str, body: &[Stmt]) -> bool {
    matches!(name, "seq" | "assembler_seq") && !body.is_empty()
}

fn annotation_type(
    file_name: &str,
    definition: &str,
    annotation: &Expr,
) -> Result<SourceType, TypedCheckError> {
    if let ExprKind::Subscript { value, slice, .. } = &annotation.node {
        let container = expression_path(value).unwrap_or_default();
        let leaf = container.rsplit('.').next().unwrap_or(&container);
        return match leaf {
            "Optional" => annotation_type(file_name, definition, slice)
                .map(|inner| SourceType::Optional(Box::new(inner))),
            "ClassVar" => annotation_type(file_name, definition, slice),
            "ExpParam" | "ScanParam" => annotation_type(file_name, definition, slice)
                .map(|inner| SourceType::ScanParam(Box::new(inner))),
            "dict" | "Dict" => Ok(SourceType::ChannelBindings),
            "tuple" | "Tuple" | "list" | "List" => Ok(SourceType::FixedAggregate),
            _ => Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation: format!("{:?}", annotation.node),
            }),
        };
    }
    if let ExprKind::BinOp {
        left,
        op: nac3ast::Operator::BitOr,
        right,
    } = &annotation.node
    {
        let left = annotation_type(file_name, definition, left)?;
        let right = annotation_type(file_name, definition, right)?;
        return match (left, right) {
            (SourceType::Unit, value) | (value, SourceType::Unit) => {
                Ok(SourceType::Optional(Box::new(value)))
            }
            _ => Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation: format!("{:?}", annotation.node),
            }),
        };
    }
    let annotation =
        expression_path(annotation).unwrap_or_else(|| format!("{:?}", annotation.node));
    let leaf = annotation.rsplit('.').next().unwrap_or(&annotation);
    let source_type = match leaf {
        "None" | "Unit" => SourceType::Unit,
        "bool" | "Bool" => SourceType::Bool,
        "int" | "Int64" => SourceType::Int64,
        "float" | "Float64" => SourceType::Float64,
        "Duration" => SourceType::Duration,
        "str" | "String" => SourceType::String,
        "Morphism" => SourceType::Morphism,
        "MorphismDef" | "MorphismTemplate" => SourceType::MorphismTemplate,
        "AtomicMorphism" | "AtomicOp" | "TimedRegion" | "BlackBoxAtomicMorphism" => {
            SourceType::AtomicOp
        }
        "Board" => SourceType::Board,
        "Channel" => SourceType::Channel,
        "ExpParams" | "ScanBindings" => SourceType::ScanBindings,
        _ => {
            return Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation,
            });
        }
    };
    Ok(source_type)
}
