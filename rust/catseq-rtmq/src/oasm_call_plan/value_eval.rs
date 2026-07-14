//! Link-time Value Expression evaluation and OASM argument materialization.

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{ValueExprId, ValueExprKind, ValueExprPayload};

use super::{DurationQuantization, LinkBindings, OasmArgument, OasmCompileError};

pub(super) fn json_argument(
    program: &NativeArenas,
    arguments: &[ValueExprId],
    index: usize,
    values: &[Result<ExactDecimal, OasmCompileError>],
) -> Result<serde_json::Value, OasmCompileError> {
    let id = arguments
        .get(index)
        .copied()
        .ok_or_else(|| OasmCompileError::new(format!("JSON argument {index} is absent")))?;
    let Some(ValueExprPayload::Json(value)) = program
        .values()
        .payload(id)
        .map_err(|error| OasmCompileError::new(error.to_string()))?
    else {
        return Err(OasmCompileError::new(format!(
            "argument {index} is not structured native data"
        )));
    };
    resolve_json_expressions(value, values)
}

fn resolve_json_expressions(
    value: &serde_json::Value,
    values: &[Result<ExactDecimal, OasmCompileError>],
) -> Result<serde_json::Value, OasmCompileError> {
    match value {
        serde_json::Value::Object(object)
            if object.len() == 1 && object.contains_key("$value_expr") =>
        {
            let index = object["$value_expr"]
                .as_u64()
                .ok_or_else(|| OasmCompileError::new("invalid native value expression reference"))?
                as usize;
            let value = values
                .get(index)
                .cloned()
                .ok_or_else(|| OasmCompileError::new("unknown native value expression"))??;
            serde_json::Number::from_f64(value.to_f64())
                .map(serde_json::Value::Number)
                .ok_or_else(|| OasmCompileError::new("native value expression is non-finite"))
        }
        serde_json::Value::Object(object) => object
            .iter()
            .map(|(key, value)| Ok((key.clone(), resolve_json_expressions(value, values)?)))
            .collect::<Result<serde_json::Map<_, _>, OasmCompileError>>()
            .map(serde_json::Value::Object),
        serde_json::Value::Array(array) => array
            .iter()
            .map(|value| resolve_json_expressions(value, values))
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array),
        value => Ok(value.clone()),
    }
}

pub(super) fn value_to_oasm_argument(
    program: &NativeArenas,
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<OasmArgument, OasmCompileError> {
    match program
        .values()
        .payload(id)
        .map_err(|error| OasmCompileError::new(error.to_string()))?
    {
        Some(ValueExprPayload::Bool(value)) => Ok(OasmArgument::Bool(*value)),
        Some(ValueExprPayload::Int64(value)) => Ok(OasmArgument::Signed(*value)),
        Some(ValueExprPayload::Float64(value)) => Ok(OasmArgument::Float(*value)),
        Some(ValueExprPayload::DurationCycles(value)) => Ok(OasmArgument::Unsigned(*value)),
        Some(ValueExprPayload::String(value)) => Ok(OasmArgument::String(value.clone())),
        Some(ValueExprPayload::Json(value)) => {
            Ok(OasmArgument::Json(resolve_json_expressions(value, values)?))
        }
        Some(ValueExprPayload::RuntimeSlot(_) | ValueExprPayload::EnvironmentSlot(_)) | None => {
            let value = values.get(id.index()).cloned().ok_or_else(|| {
                OasmCompileError::new(format!("unknown OASM argument expression {}", id.index()))
            })??;
            Ok(OasmArgument::Float(value.to_f64()))
        }
    }
}

pub(super) fn evaluate_numeric_values(
    program: &NativeArenas,
    link_bindings: &LinkBindings,
) -> Vec<Result<ExactDecimal, OasmCompileError>> {
    let arena = program.values();
    let mut values =
        Vec::<Result<ExactDecimal, OasmCompileError>>::with_capacity(arena.nodes().len());
    for (index, node) in arena.nodes().iter().enumerate() {
        let children = &arena.edges()
            [node.edge_start() as usize..node.edge_start() as usize + node.edge_count() as usize];
        let value = match node.kind() {
            ValueExprKind::Constant => match arena.payload(ValueExprId::from_index(index as u32)) {
                Ok(Some(ValueExprPayload::DurationCycles(value))) => {
                    Ok(ExactDecimal::from_u64(*value))
                }
                Ok(Some(ValueExprPayload::Int64(value))) => Ok(ExactDecimal::from_i64(*value)),
                Ok(Some(ValueExprPayload::Float64(value))) => {
                    ExactDecimal::from_f64_shortest(*value).ok_or_else(|| {
                        OasmCompileError::new(format!("expression {index} is not finite"))
                    })
                }
                Ok(Some(ValueExprPayload::Json(_))) => Err(OasmCompileError::new(format!(
                    "expression {index} is structured data, not a numeric value"
                ))),
                _ => Err(OasmCompileError::new(format!(
                    "expression {index} is not an integer duration"
                ))),
            },
            ValueExprKind::Add => numeric_binary(&values, children, ExactDecimal::checked_add),
            ValueExprKind::Subtract => numeric_binary(&values, children, ExactDecimal::checked_sub),
            ValueExprKind::Multiply => numeric_binary(&values, children, ExactDecimal::checked_mul),
            ValueExprKind::Divide => match numeric_operand(&values, children[1]) {
                Ok(denominator) => numeric_operand(&values, children[0]).and_then(|numerator| {
                    numerator
                        .checked_div(denominator)
                        .ok_or_else(|| OasmCompileError::new("duration division is invalid"))
                }),
                Err(error) => Err(error),
            },
            ValueExprKind::Modulo => numeric_binary(&values, children, ExactDecimal::checked_rem),
            ValueExprKind::Maximum => numeric_binary(&values, children, ExactDecimal::maximum),
            ValueExprKind::Negate => numeric_operand(&values, children[0]).and_then(|value| {
                value
                    .checked_neg()
                    .ok_or_else(|| OasmCompileError::new("numeric negation overflows"))
            }),
            ValueExprKind::RuntimeSlot => {
                match arena.payload(ValueExprId::from_index(index as u32)) {
                    Ok(Some(ValueExprPayload::RuntimeSlot(name))) => link_bindings
                        .runtime_values
                        .get(name)
                        .filter(|value| value.matches_type(node.value_type()))
                        .cloned()
                        .and_then(|value| value.into_numeric_for(node.value_type()))
                        .ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Runtime Slot {name:?} is absent or has the wrong type in Link Bindings"
                            ))
                        }),
                    _ => Err(OasmCompileError::new(format!(
                        "RuntimeSlot expression {index} has no slot payload"
                    ))),
                }
            }
            ValueExprKind::EnvironmentSlot => {
                match arena.payload(ValueExprId::from_index(index as u32)) {
                    Ok(Some(ValueExprPayload::EnvironmentSlot(name))) => link_bindings
                        .environment_values
                        .get(name)
                        .filter(|value| value.matches_type(node.value_type()))
                        .cloned()
                        .and_then(|value| value.into_numeric_for(node.value_type()))
                        .ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Environment Slot {name:?} is absent or has the wrong type in Link Bindings"
                            ))
                        }),
                    _ => Err(OasmCompileError::new(format!(
                        "EnvironmentSlot expression {index} has no slot payload"
                    ))),
                }
            }
        };
        values.push(value);
    }
    values
}

fn numeric_binary(
    values: &[Result<ExactDecimal, OasmCompileError>],
    children: &[ValueExprId],
    operation: impl FnOnce(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
) -> Result<ExactDecimal, OasmCompileError> {
    let left = numeric_operand(values, children[0])?;
    let right = numeric_operand(values, children[1])?;
    operation(left, right).ok_or_else(|| OasmCompileError::new("exact numeric operation failed"))
}

fn numeric_operand(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<ExactDecimal, OasmCompileError> {
    values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "expression {} is not topological",
            id.index()
        )))
    })
}

pub(super) fn eval_cycles(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<u64, OasmCompileError> {
    let value = values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "cannot evaluate expression {}",
            id.index()
        )))
    })?;
    value.to_cycle_count().ok_or_else(|| {
        OasmCompileError::new("duration is not an exact non-negative target Cycle Count")
    })
}

pub(super) fn eval_duration_cycles(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
    quantization: DurationQuantization,
) -> Result<u64, OasmCompileError> {
    let value = values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "cannot evaluate expression {}",
            id.index()
        )))
    })?;
    let cycles = match quantization {
        DurationQuantization::Strict => value.to_cycle_count(),
        DurationQuantization::NearestEven => value.to_cycle_count_rounded(),
    };
    let requirement = match quantization {
        DurationQuantization::Strict => "an exact non-negative",
        DurationQuantization::NearestEven => "a non-negative",
    };
    cycles.ok_or_else(|| {
        OasmCompileError::new(format!(
            "duration {} is not {requirement} target Cycle Count (expression {})",
            value.to_f64(),
            id.index()
        ))
    })
}
