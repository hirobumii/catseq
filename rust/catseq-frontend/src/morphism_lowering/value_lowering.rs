//! Compile-time scalar, aggregate, and Value Expression lowering.

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::value_expr::{
    ValueExprArenaBuilder, ValueExprId, ValueExprKind, ValueExprPayload, ValueExprType,
};

use crate::{ComparisonOperation, SourceHirNode, SourceLiteral, SourceType, ValueOperation};

use super::normalized_value::{normalized_has_duration_unit, parse_normalized_numeric};
use super::{LoweredValue, MorphismLoweringError, ScalarValue, lowering_error};

pub(super) fn lower_aggregate_operation(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Option<LoweredValue> {
    let [left, right] = children else {
        return None;
    };
    match (
        node.value_operation(),
        values[*left as usize].clone(),
        values[*right as usize].clone(),
    ) {
        (
            Some(ValueOperation::Add),
            Some(LoweredValue::Aggregate(mut left)),
            Some(LoweredValue::Aggregate(right)),
        ) => {
            left.extend(right);
            Some(LoweredValue::Aggregate(left))
        }
        _ => None,
    }
}

pub(super) fn lower_compile_compare(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    if node.comparison_operations().len() + 1 != children.len() {
        return Err(lowering_error(node, "invalid comparison operand shape"));
    }
    let operands = children
        .iter()
        .map(|child| values[*child as usize].as_ref())
        .collect::<Option<Vec<_>>>();
    let Some(operands) = operands else {
        return Ok(None);
    };
    let mut result = true;
    for (index, operation) in node.comparison_operations().iter().enumerate() {
        result &= compare_lowered_values(*operation, operands[index], operands[index + 1])
            .ok_or_else(|| lowering_error(node, "comparison is not compile-time evaluable"))?;
        if !result {
            break;
        }
    }
    Ok(Some(LoweredValue::Scalar(ScalarValue::Bool(result))))
}

fn compare_lowered_values(
    operation: ComparisonOperation,
    left: &LoweredValue,
    right: &LoweredValue,
) -> Option<bool> {
    use std::cmp::Ordering;

    let equality = || lowered_values_equal(left, right);
    match operation {
        ComparisonOperation::Equal | ComparisonOperation::Is => equality(),
        ComparisonOperation::NotEqual | ComparisonOperation::IsNot => equality().map(|v| !v),
        ComparisonOperation::Less
        | ComparisonOperation::LessEqual
        | ComparisonOperation::Greater
        | ComparisonOperation::GreaterEqual => {
            let ordering = numeric_scalar(left)?.checked_cmp(numeric_scalar(right)?)?;
            Some(match operation {
                ComparisonOperation::Less => ordering == Ordering::Less,
                ComparisonOperation::LessEqual => ordering != Ordering::Greater,
                ComparisonOperation::Greater => ordering == Ordering::Greater,
                ComparisonOperation::GreaterEqual => ordering != Ordering::Less,
                _ => unreachable!(),
            })
        }
        ComparisonOperation::In | ComparisonOperation::NotIn => {
            let contains = match right {
                LoweredValue::Aggregate(values) => values
                    .iter()
                    .map(|value| lowered_values_equal(left, value))
                    .collect::<Option<Vec<_>>>()?
                    .into_iter()
                    .any(|equal| equal),
                LoweredValue::Scalar(ScalarValue::String(haystack)) => match left {
                    LoweredValue::Scalar(ScalarValue::String(needle)) => haystack.contains(needle),
                    _ => return None,
                },
                _ => return None,
            };
            Some(if operation == ComparisonOperation::In {
                contains
            } else {
                !contains
            })
        }
    }
}

fn lowered_values_equal(left: &LoweredValue, right: &LoweredValue) -> Option<bool> {
    match (left, right) {
        (LoweredValue::Null, LoweredValue::Null) => Some(true),
        (LoweredValue::Null, _) | (_, LoweredValue::Null) => Some(false),
        (
            LoweredValue::Scalar(ScalarValue::Bool(left)),
            LoweredValue::Scalar(ScalarValue::Bool(right)),
        ) => Some(left == right),
        (
            LoweredValue::Scalar(ScalarValue::String(left)),
            LoweredValue::Scalar(ScalarValue::String(right)),
        ) => Some(left == right),
        (LoweredValue::Scalar(_), LoweredValue::Scalar(_)) => Some(
            numeric_scalar(left)?
                .checked_cmp(numeric_scalar(right)?)?
                .is_eq(),
        ),
        (LoweredValue::Json(left), LoweredValue::Json(right)) => Some(left == right),
        (LoweredValue::Aggregate(left), LoweredValue::Aggregate(right)) => {
            if left.len() != right.len() {
                return Some(false);
            }
            for (left, right) in left.iter().zip(right) {
                if !lowered_values_equal(left, right)? {
                    return Some(false);
                }
            }
            Some(true)
        }
        _ => Some(false),
    }
}

fn numeric_scalar(value: &LoweredValue) -> Option<ExactDecimal> {
    match value {
        LoweredValue::Scalar(ScalarValue::Int(value)) => Some(ExactDecimal::from_i64(*value)),
        LoweredValue::Scalar(ScalarValue::Float(value))
        | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => Some(*value),
        _ => None,
    }
}

pub(super) fn lower_aggregate_intrinsic(
    node: &SourceHirNode,
    children: &[u32],
    fact: &crate::SemanticFact,
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let leaf = fact
        .resolved_definition()
        .or(node.symbol())
        .unwrap_or_default()
        .rsplit('.')
        .next()
        .unwrap_or_default();
    let arguments = children
        .iter()
        .skip(1)
        .map(|child| values[*child as usize].clone())
        .collect::<Option<Vec<_>>>();
    let Some(arguments) = arguments else {
        return Ok(None);
    };
    let result = match leaf {
        "range" => {
            let integers = arguments
                .iter()
                .map(|value| match value {
                    LoweredValue::Scalar(ScalarValue::Int(value)) => Some(*value),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>();
            let Some(integers) = integers else {
                return Ok(None);
            };
            let (start, stop, step) = match integers.as_slice() {
                [stop] => (0, *stop, 1),
                [start, stop] => (*start, *stop, 1),
                [start, stop, step] if *step != 0 => (*start, *stop, *step),
                _ => {
                    return Err(lowering_error(
                        node,
                        "range requires one to three integer arguments and a nonzero step",
                    ));
                }
            };
            let mut values = Vec::new();
            let mut current = start;
            while if step > 0 {
                current < stop
            } else {
                current > stop
            } {
                values.push(LoweredValue::Scalar(ScalarValue::Int(current)));
                current = current
                    .checked_add(step)
                    .ok_or_else(|| lowering_error(node, "range overflows Int64"))?;
            }
            LoweredValue::Aggregate(values)
        }
        "zip" => {
            let aggregates = arguments
                .into_iter()
                .map(|value| match value {
                    LoweredValue::Aggregate(values) => Some(values),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>();
            let Some(aggregates) = aggregates else {
                return Ok(None);
            };
            let length = aggregates.iter().map(Vec::len).min().unwrap_or(0);
            LoweredValue::Aggregate(
                (0..length)
                    .map(|index| {
                        LoweredValue::Aggregate(
                            aggregates
                                .iter()
                                .map(|values| values[index].clone())
                                .collect(),
                        )
                    })
                    .collect(),
            )
        }
        "enumerate" => {
            let Some(LoweredValue::Aggregate(values)) = arguments.first().cloned() else {
                return Ok(None);
            };
            let start = match arguments.get(1) {
                None => 0,
                Some(LoweredValue::Scalar(ScalarValue::Int(value))) => *value,
                Some(_) => return Ok(None),
            };
            LoweredValue::Aggregate(
                values
                    .into_iter()
                    .enumerate()
                    .map(|(index, value)| {
                        LoweredValue::Aggregate(vec![
                            LoweredValue::Scalar(ScalarValue::Int(start + index as i64)),
                            value,
                        ])
                    })
                    .collect(),
            )
        }
        "tuple" | "list" => match arguments.as_slice() {
            [LoweredValue::Aggregate(values)] => LoweredValue::Aggregate(values.clone()),
            _ => LoweredValue::Aggregate(arguments),
        },
        "ones_like" => {
            let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
                return Ok(None);
            };
            LoweredValue::Aggregate(
                (0..values.len())
                    .map(|_| LoweredValue::Scalar(ScalarValue::Float(ExactDecimal::from_i64(1))))
                    .collect(),
            )
        }
        _ => return Ok(None),
    };
    Ok(Some(result))
}

pub(super) fn lower_static_subscript(
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Option<LoweredValue> {
    let [aggregate, index] = children else {
        return None;
    };
    let Some(LoweredValue::Aggregate(aggregate)) = values[*aggregate as usize].as_ref() else {
        return None;
    };
    let Some(LoweredValue::Scalar(ScalarValue::Int(index))) = values[*index as usize].as_ref()
    else {
        return None;
    };
    let index = if *index < 0 {
        aggregate.len().checked_sub(index.unsigned_abs() as usize)?
    } else {
        *index as usize
    };
    aggregate.get(index).cloned()
}

pub(super) fn is_numeric_intrinsic(resolved: &str) -> bool {
    matches!(
        resolved.rsplit('.').next().unwrap_or(resolved),
        "sqrt" | "arccos" | "cos" | "sin" | "mod" | "round" | "len" | "sum"
    )
}

pub(super) fn lower_numeric_intrinsic(
    node: &SourceHirNode,
    children: &[u32],
    resolved: &str,
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let resolved = resolved.rsplit('.').next().unwrap_or(resolved);
    let arguments = children
        .iter()
        .skip(1)
        .filter_map(|child| values[*child as usize].clone())
        .collect::<Vec<_>>();
    if resolved == "len" {
        let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
            return Ok(None);
        };
        return Ok(Some(LoweredValue::Scalar(ScalarValue::Int(
            values.len() as i64
        ))));
    }
    if resolved == "sum" {
        let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
            return Ok(None);
        };
        let operands = values
            .iter()
            .map(|value| match value {
                LoweredValue::Scalar(value) => Some(value.clone()),
                _ => None,
            })
            .collect::<Option<Vec<_>>>();
        let Some(mut operands) = operands else {
            return Ok(None);
        };
        let Some(mut total) = operands.drain(..1).next() else {
            return Ok(Some(LoweredValue::Scalar(ScalarValue::Int(0))));
        };
        for operand in operands {
            let Some(next) = fold_scalar_operation(ValueOperation::Add, &[total, operand]) else {
                return Ok(None);
            };
            total = next;
        }
        return Ok(Some(LoweredValue::Scalar(total)));
    }
    let numeric = arguments
        .iter()
        .map(|argument| match argument {
            LoweredValue::Scalar(ScalarValue::Int(value)) => Some(*value as f64),
            LoweredValue::Scalar(ScalarValue::Float(value))
            | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => Some(value.to_f64()),
            _ => None,
        })
        .collect::<Option<Vec<_>>>();
    let Some(numeric) = numeric else {
        return Ok(None);
    };
    let value = match (resolved, numeric.as_slice()) {
        ("sqrt", [value]) => value.sqrt(),
        ("arccos", [value]) => value.acos(),
        ("cos", [value]) => value.cos(),
        ("sin", [value]) => value.sin(),
        ("mod", [left, right]) => left.rem_euclid(*right),
        ("round", [value]) => value.round_ties_even(),
        _ => return Ok(None),
    };
    let value = ExactDecimal::from_f64_shortest(value)
        .ok_or_else(|| lowering_error(node, format!("{resolved} produced a non-finite value")))?;
    Ok(Some(LoweredValue::Scalar(ScalarValue::Float(value))))
}

pub(super) fn lowered_to_json(
    value: &LoweredValue,
) -> Result<serde_json::Value, MorphismLoweringError> {
    match value {
        LoweredValue::Null => Ok(serde_json::Value::Null),
        LoweredValue::Json(value) => Ok(value.clone()),
        LoweredValue::Aggregate(values) => values
            .iter()
            .map(lowered_to_json)
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array),
        LoweredValue::Scalar(ScalarValue::Bool(value)) => Ok((*value).into()),
        LoweredValue::Scalar(ScalarValue::Int(value)) => Ok((*value).into()),
        LoweredValue::Scalar(ScalarValue::Float(value))
        | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => {
            serde_json::Number::from_f64(value.to_f64())
                .map(serde_json::Value::Number)
                .ok_or_else(|| MorphismLoweringError::new("native record contains non-finite data"))
        }
        LoweredValue::Scalar(ScalarValue::String(value)) => Ok(value.clone().into()),
        LoweredValue::Scalar(ScalarValue::Expr(id)) => Ok(serde_json::json!({
            "$value_expr": id.index()
        })),
        LoweredValue::Morphism(_)
        | LoweredValue::Template(_)
        | LoweredValue::ChannelBindings(_) => Err(MorphismLoweringError::new(
            "Morphism value cannot be embedded in a native record",
        )),
    }
}

pub(super) fn lower_literal(
    node: &SourceHirNode,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let value = match node.literal() {
        Some(SourceLiteral::Bool(value)) => ScalarValue::Bool(*value),
        Some(SourceLiteral::Int(value)) => ScalarValue::Int(value.parse().map_err(|_| {
            lowering_error(
                node,
                format!("integer literal {value:?} does not fit Int64"),
            )
        })?),
        Some(SourceLiteral::FloatBits(value)) => ScalarValue::Float(
            ExactDecimal::from_f64_shortest(f64::from_bits(*value))
                .ok_or_else(|| lowering_error(node, "invalid Float64 literal"))?,
        ),
        Some(SourceLiteral::String(value)) => ScalarValue::String(value.clone()),
        Some(SourceLiteral::None) => return Ok(Some(LoweredValue::Null)),
        None => return Ok(None),
    };
    Ok(Some(LoweredValue::Scalar(value)))
}

pub(super) fn lower_compile_value(
    node: &SourceHirNode,
    value: &str,
    source_type: Option<&SourceType>,
    clock_hz: u64,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let scalar = match value {
        "True" | "true" => ScalarValue::Bool(true),
        "False" | "false" => ScalarValue::Bool(false),
        "constant:Bool(true)" => ScalarValue::Bool(true),
        "constant:Bool(false)" => ScalarValue::Bool(false),
        quoted
            if quoted.len() >= 2
                && ((quoted.starts_with('"') && quoted.ends_with('"'))
                    || (quoted.starts_with('\'') && quoted.ends_with('\''))) =>
        {
            ScalarValue::String(quoted[1..quoted.len() - 1].to_owned())
        }
        integer if integer.parse::<i64>().is_ok() => {
            ScalarValue::Int(integer.parse().expect("checked above"))
        }
        numeric => {
            let numeric = parse_normalized_numeric(numeric).ok_or_else(|| {
                lowering_error(node, format!("unsupported compile-time value {value:?}"))
            })?;
            if source_type == Some(&SourceType::Int64) {
                let integer = numeric
                    .to_cycle_count()
                    .and_then(|value| i64::try_from(value).ok())
                    .ok_or_else(|| lowering_error(node, "Int64 compile value is not integral"))?;
                ScalarValue::Int(integer)
            } else if source_type == Some(&SourceType::Duration)
                || normalized_has_duration_unit(value)
            {
                ScalarValue::DurationCycles(
                    numeric
                        .checked_mul(ExactDecimal::from_u64(clock_hz))
                        .ok_or_else(|| lowering_error(node, "duration conversion overflows"))?,
                )
            } else {
                ScalarValue::Float(numeric)
            }
        }
    };
    Ok(Some(LoweredValue::Scalar(scalar)))
}

pub(super) fn lower_duration_unit(node: &SourceHirNode, clock_hz: u64) -> Option<LoweredValue> {
    let denominator = match node.symbol()? {
        "s" => 1_u64,
        "ms" => 1_000,
        "us" => 1_000_000,
        "ns" => 1_000_000_000,
        _ => return None,
    };
    Some(LoweredValue::Scalar(ScalarValue::DurationCycles(
        ExactDecimal::from_u64(clock_hz).checked_div(ExactDecimal::from_u64(denominator))?,
    )))
}

pub(super) fn lower_value_operation(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
    source_type: Option<&SourceType>,
    builder: &mut ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let operands = children
        .iter()
        .filter_map(|child| match values[*child as usize].clone() {
            Some(LoweredValue::Scalar(value)) => Some(value),
            _ => None,
        })
        .collect::<Vec<_>>();
    let operation = node
        .value_operation()
        .ok_or_else(|| lowering_error(node, "value operation is absent"))?;
    if operands.len() != children.len() {
        return Ok(None);
    }
    if let Some(value) = fold_scalar_operation(operation, &operands) {
        return Ok(Some(LoweredValue::Scalar(value)));
    }
    let Some(value_type) = source_type_to_value_type(source_type) else {
        return Ok(None);
    };
    let children = operands
        .iter()
        .cloned()
        .map(|value| scalar_to_expr(value, builder, node))
        .collect::<Result<Vec<_>, _>>()?;
    let kind = match operation {
        ValueOperation::Add => ValueExprKind::Add,
        ValueOperation::Subtract => ValueExprKind::Subtract,
        ValueOperation::Multiply => ValueExprKind::Multiply,
        ValueOperation::Divide => ValueExprKind::Divide,
        ValueOperation::Modulo => ValueExprKind::Modulo,
        ValueOperation::Negate => ValueExprKind::Negate,
        ValueOperation::Positive => return Ok(Some(LoweredValue::Scalar(operands[0].clone()))),
        ValueOperation::LogicalNot => {
            return Err(lowering_error(
                node,
                "link-time boolean negation cannot control Morphism structure",
            ));
        }
        ValueOperation::FloorDivide | ValueOperation::Power => {
            return Err(lowering_error(
                node,
                format!("{} is not supported in ValueExpr yet", operation.as_str()),
            ));
        }
        ValueOperation::LeftShift => {
            return Err(lowering_error(
                node,
                "link-time integer shifting is not supported",
            ));
        }
    };
    Ok(Some(LoweredValue::Scalar(ScalarValue::Expr(
        builder.operation(kind, value_type, &children),
    ))))
}

fn fold_scalar_operation(
    operation: ValueOperation,
    operands: &[ScalarValue],
) -> Option<ScalarValue> {
    use ScalarValue::{Bool, DurationCycles, Float, Int};
    match (operation, operands) {
        (ValueOperation::Add, [Int(left), Int(right)]) => left.checked_add(*right).map(Int),
        (ValueOperation::Subtract, [Int(left), Int(right)]) => left.checked_sub(*right).map(Int),
        (ValueOperation::Multiply, [Int(left), Int(right)]) => left.checked_mul(*right).map(Int),
        (ValueOperation::Divide, [Int(left), Int(right)]) => ExactDecimal::from_i64(*left)
            .checked_div(ExactDecimal::from_i64(*right))
            .map(Float),
        (ValueOperation::Add, [Float(left), Float(right)]) => left.checked_add(*right).map(Float),
        (ValueOperation::Subtract, [Float(left), Float(right)]) => {
            left.checked_sub(*right).map(Float)
        }
        (ValueOperation::Multiply, [Float(left), Float(right)]) => {
            left.checked_mul(*right).map(Float)
        }
        (ValueOperation::Divide, [Float(left), Float(right)]) => {
            left.checked_div(*right).map(Float)
        }
        (ValueOperation::Add, [Float(left), Int(right)])
        | (ValueOperation::Add, [Int(right), Float(left)]) => {
            left.checked_add(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Subtract, [Float(left), Int(right)]) => {
            left.checked_sub(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Subtract, [Int(left), Float(right)]) => {
            ExactDecimal::from_i64(*left).checked_sub(*right).map(Float)
        }
        (ValueOperation::Multiply, [Float(left), Int(right)])
        | (ValueOperation::Multiply, [Int(right), Float(left)]) => {
            left.checked_mul(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Divide, [Float(left), Int(right)]) => {
            left.checked_div(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Divide, [Int(left), Float(right)]) => {
            ExactDecimal::from_i64(*left).checked_div(*right).map(Float)
        }
        (ValueOperation::Power, [Int(base), Int(exponent)]) if *exponent >= 0 => {
            base.checked_pow(*exponent as u32).map(Int)
        }
        (ValueOperation::Power, [Float(base), Int(exponent)]) => {
            ExactDecimal::from_f64_shortest(base.to_f64().powi(*exponent as i32)).map(Float)
        }
        (ValueOperation::Power, [Float(base), Float(exponent)]) => {
            ExactDecimal::from_f64_shortest(base.to_f64().powf(exponent.to_f64())).map(Float)
        }
        (ValueOperation::LeftShift, [Int(value), Int(shift)]) if (0..64).contains(shift) => {
            value.checked_shl(*shift as u32).map(Int)
        }
        (ValueOperation::FloorDivide, [Int(left), Int(right)]) if *right != 0 => {
            Some(Int(left.div_euclid(*right)))
        }
        (ValueOperation::Modulo, [Int(left), Int(right)]) if *right != 0 => {
            Some(Int(left.rem_euclid(*right)))
        }
        (ValueOperation::Multiply, [DurationCycles(value), Int(scale)])
        | (ValueOperation::Multiply, [Int(scale), DurationCycles(value)]) => value
            .checked_mul(ExactDecimal::from_i64(*scale))
            .map(DurationCycles),
        (ValueOperation::Multiply, [DurationCycles(value), Float(scale)])
        | (ValueOperation::Multiply, [Float(scale), DurationCycles(value)]) => {
            value.checked_mul(*scale).map(DurationCycles)
        }
        (ValueOperation::Divide, [DurationCycles(value), Int(scale)]) => value
            .checked_div(ExactDecimal::from_i64(*scale))
            .map(DurationCycles),
        (ValueOperation::Divide, [DurationCycles(value), Float(scale)]) => {
            value.checked_div(*scale).map(DurationCycles)
        }
        (ValueOperation::Divide, [Float(value), DurationCycles(scale)]) => {
            value.checked_div(*scale).map(Float)
        }
        (ValueOperation::Divide, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_div(*right).map(Float)
        }
        (ValueOperation::Add, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_add(*right).map(DurationCycles)
        }
        (ValueOperation::Subtract, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_sub(*right).map(DurationCycles)
        }
        (ValueOperation::Negate, [Int(value)]) => value.checked_neg().map(Int),
        (ValueOperation::Negate, [Float(value)]) => value.checked_neg().map(Float),
        (ValueOperation::Negate, [DurationCycles(value)]) => value.checked_neg().map(Float),
        (ValueOperation::Positive, [value]) => Some(value.clone()),
        (ValueOperation::LogicalNot, [Bool(value)]) => Some(Bool(!value)),
        _ => None,
    }
}

pub(super) fn call_arguments(
    children: &[u32],
    values: &[Option<LoweredValue>],
    builder: &mut ValueExprArenaBuilder,
    node: &SourceHirNode,
) -> Result<Vec<ValueExprId>, MorphismLoweringError> {
    let mut arguments = Vec::new();
    for child in children.iter().skip(1) {
        let Some(value) = values[*child as usize].clone() else {
            continue;
        };
        match value {
            LoweredValue::Scalar(value) => arguments.push(scalar_to_expr(value, builder, node)?),
            LoweredValue::Json(value) => {
                arguments.push(builder.constant(ValueExprPayload::Json(value)))
            }
            LoweredValue::Aggregate(values) => {
                arguments.push(builder.constant(ValueExprPayload::Json(
                    serde_json::Value::Array(values.iter().map(lowered_to_json).collect::<Result<
                        Vec<_>,
                        _,
                    >>(
                    )?),
                )))
            }
            LoweredValue::Null => {
                arguments.push(builder.constant(ValueExprPayload::Json(serde_json::Value::Null)))
            }
            LoweredValue::Morphism(_)
            | LoweredValue::Template(_)
            | LoweredValue::ChannelBindings(_) => {}
        }
    }
    Ok(arguments)
}

pub(super) fn scalar_to_expr(
    value: ScalarValue,
    builder: &mut ValueExprArenaBuilder,
    node: &SourceHirNode,
) -> Result<ValueExprId, MorphismLoweringError> {
    let payload = match value {
        ScalarValue::Bool(value) => ValueExprPayload::Bool(value),
        ScalarValue::Int(value) => ValueExprPayload::Int64(value),
        ScalarValue::Float(value) => ValueExprPayload::Float64(value.to_f64()),
        ScalarValue::DurationCycles(value) => {
            let cycles = value.to_cycle_count_rounded().ok_or_else(|| {
                lowering_error(
                    node,
                    format!(
                        "duration {} is not an exact non-negative target Cycle Count",
                        value.to_f64()
                    ),
                )
            })?;
            ValueExprPayload::DurationCycles(cycles)
        }
        ScalarValue::String(value) => ValueExprPayload::String(value),
        ScalarValue::Expr(id) => return Ok(id),
    };
    Ok(builder.constant(payload))
}

pub(super) fn source_type_to_value_type(source_type: Option<&SourceType>) -> Option<ValueExprType> {
    match source_type? {
        SourceType::Bool => Some(ValueExprType::Bool),
        SourceType::Int64 => Some(ValueExprType::Int64),
        SourceType::Float64 => Some(ValueExprType::Float64),
        SourceType::Duration => Some(ValueExprType::Duration),
        SourceType::String => Some(ValueExprType::String),
        _ => None,
    }
}
