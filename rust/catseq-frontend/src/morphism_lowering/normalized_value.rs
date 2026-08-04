//! Parsing for the normalized compile-time value notation stored in Typed Source HIR.

use std::collections::HashMap;

use catseq_core::exact_decimal::ExactDecimal;

use super::{LoweredValue, MorphismLoweringError, ScalarValue};

#[derive(Clone, Copy, Eq, PartialEq)]
enum NumericDimension {
    Scalar,
    Duration,
}

pub(super) fn normalized_has_duration_unit(value: &str) -> bool {
    normalized_numeric_dimension(value) == Some(NumericDimension::Duration)
}

fn normalized_numeric_dimension(value: &str) -> Option<NumericDimension> {
    if normalized_is_cycles_call(value) {
        return parse_normalized_cycles(value).map(|_| NumericDimension::Duration);
    }
    if value.starts_with("constant:Int(")
        || value.starts_with("constant:Float(")
        || ExactDecimal::parse(value).is_some()
    {
        return Some(NumericDimension::Scalar);
    }
    if let Some(unit) = value.strip_prefix("name:") {
        return matches!(
            unit,
            "s" | "ms"
                | "us"
                | "ns"
                | "catseq.time_utils.s"
                | "catseq.time_utils.ms"
                | "catseq.time_utils.us"
                | "catseq.time_utils.ns"
        )
        .then_some(NumericDimension::Duration);
    }
    for prefix in ["unary:USub(", "unary:UAdd("] {
        if let Some(operand) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        {
            return normalized_numeric_dimension(operand);
        }
    }
    for (prefix, operation) in [
        ("bin:Add(", "add"),
        ("bin:Sub(", "subtract"),
        ("bin:Mult(", "multiply"),
        ("bin:Div(", "divide"),
    ] {
        let Some(operands) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        else {
            continue;
        };
        let (left, right) = split_normalized_operands(operands)?;
        let left = normalized_numeric_dimension(left)?;
        let right = normalized_numeric_dimension(right)?;
        return match (operation, left, right) {
            ("add" | "subtract", NumericDimension::Scalar, NumericDimension::Scalar) => {
                Some(NumericDimension::Scalar)
            }
            ("add" | "subtract", NumericDimension::Duration, NumericDimension::Duration) => {
                Some(NumericDimension::Duration)
            }
            ("multiply", NumericDimension::Scalar, NumericDimension::Scalar) => {
                Some(NumericDimension::Scalar)
            }
            ("multiply", NumericDimension::Duration, NumericDimension::Scalar)
            | ("multiply", NumericDimension::Scalar, NumericDimension::Duration)
            | ("divide", NumericDimension::Duration, NumericDimension::Scalar) => {
                Some(NumericDimension::Duration)
            }
            ("divide", NumericDimension::Scalar, NumericDimension::Scalar)
            | ("divide", NumericDimension::Duration, NumericDimension::Duration) => {
                Some(NumericDimension::Scalar)
            }
            _ => None,
        };
    }
    None
}

pub(super) fn normalized_is_cycles_call(value: &str) -> bool {
    let Some(call) = value.strip_prefix("call:") else {
        return false;
    };
    let Some(open) = call.find('(') else {
        return false;
    };
    &call[..open] == "catseq.time_utils.cycles"
}

pub(super) fn parse_normalized_cycles(value: &str) -> Option<ExactDecimal> {
    if !normalized_is_cycles_call(value) {
        return None;
    }
    let call = value.strip_prefix("call:")?;
    let open = call.find('(')?;
    let arguments = call.get(open + 1..)?.strip_suffix(')')?;
    let (positional, keywords) = split_normalized_once(arguments, ';')?;
    if positional.is_empty()
        || !keywords.is_empty()
        || split_normalized_once(positional, ',').is_some()
    {
        return None;
    }
    if positional.contains("Float(") {
        return None;
    }
    let cycles = parse_normalized_numeric(positional)?.to_signed_cycle_delta()?;
    Some(ExactDecimal::from_i64(cycles))
}

pub(super) fn lower_normalized_default(value: &str, clock_hz: u64) -> Option<LoweredValue> {
    let scalar = match value {
        "constant:None" => return Some(LoweredValue::Null),
        "constant:Bool(true)" => ScalarValue::Bool(true),
        "constant:Bool(false)" => ScalarValue::Bool(false),
        value if value.starts_with("constant:Int(") => {
            let value = value
                .strip_prefix("constant:Int(")?
                .strip_suffix(')')?
                .parse()
                .ok()?;
            ScalarValue::Int(value)
        }
        value if normalized_is_cycles_call(value) => {
            ScalarValue::DurationCycles(parse_normalized_cycles(value)?)
        }
        value if normalized_has_duration_unit(value) => ScalarValue::DurationCycles(
            parse_normalized_numeric(value)?.checked_mul(ExactDecimal::from_u64(clock_hz))?,
        ),
        value => ScalarValue::Float(parse_normalized_numeric(value)?),
    };
    Some(LoweredValue::Scalar(scalar))
}

pub(super) fn parse_normalized_numeric(value: &str) -> Option<ExactDecimal> {
    if let Some(value) = value
        .strip_prefix("constant:Float(")
        .and_then(|value| value.strip_suffix(')'))
        .or_else(|| {
            value
                .strip_prefix("constant:Int(")
                .and_then(|value| value.strip_suffix(')'))
        })
    {
        return ExactDecimal::parse(value);
    }
    if let Some(unit) = value.strip_prefix("name:") {
        return match unit {
            "s" | "catseq.time_utils.s" => Some(ExactDecimal::from_u64(1)),
            "ms" | "catseq.time_utils.ms" => ExactDecimal::parse("0.001"),
            "us" | "catseq.time_utils.us" => ExactDecimal::parse("0.000001"),
            "ns" | "catseq.time_utils.ns" => ExactDecimal::parse("0.000000001"),
            _ => None,
        };
    }
    if let Some(operand) = value
        .strip_prefix("unary:USub(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric(operand)?.checked_neg();
    }
    if let Some(operand) = value
        .strip_prefix("unary:UAdd(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric(operand);
    }
    for (prefix, operation) in [
        (
            "bin:Add(",
            ExactDecimal::checked_add as fn(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
        ),
        ("bin:Sub(", ExactDecimal::checked_sub),
        ("bin:Mult(", ExactDecimal::checked_mul),
        ("bin:Div(", ExactDecimal::checked_div),
    ] {
        if let Some(operands) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        {
            let (left, right) = split_normalized_operands(operands)?;
            return operation(
                parse_normalized_numeric(left)?,
                parse_normalized_numeric(right)?,
            );
        }
    }
    ExactDecimal::parse(value)
}

fn split_normalized_operands(operands: &str) -> Option<(&str, &str)> {
    let mut depth = 0_u32;
    for (index, character) in operands.char_indices() {
        match character {
            '(' => depth = depth.checked_add(1)?,
            ')' => depth = depth.checked_sub(1)?,
            ',' if depth == 0 => return Some((&operands[..index], &operands[index + 1..])),
            _ => {}
        }
    }
    None
}

pub(super) fn normalized_to_json(
    value: &str,
    fields: &HashMap<String, String>,
) -> Result<serde_json::Value, MorphismLoweringError> {
    if value == "constant:None" {
        return Ok(serde_json::Value::Null);
    }
    if value == "constant:Bool(true)" {
        return Ok(true.into());
    }
    if value == "constant:Bool(false)" {
        return Ok(false.into());
    }
    if let Some(string) = value
        .strip_prefix("constant:Str(\"")
        .and_then(|value| value.strip_suffix("\")"))
    {
        return Ok(string.to_owned().into());
    }
    if let Some(number) = parse_normalized_numeric_with_fields(value, fields) {
        return serde_json::Number::from_f64(number.to_f64())
            .map(serde_json::Value::Number)
            .ok_or_else(|| MorphismLoweringError::new("non-finite normalized number"));
    }
    if let Some(name) = value.strip_prefix("name:")
        && let Some(value) = fields.get(name)
    {
        return normalized_to_json(value, fields);
    }
    if value.starts_with("path:") {
        return Ok(serde_json::Value::String(value.to_owned()));
    }
    if let Some(elements) = value
        .strip_prefix("aggregate:[")
        .and_then(|value| value.strip_suffix(']'))
    {
        return split_normalized_list(elements, ',')
            .into_iter()
            .filter(|value| !value.is_empty())
            .map(|value| normalized_to_json(value, fields))
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array);
    }
    if let Some(call) = value.strip_prefix("call:")
        && let Some(open) = call.find('(')
        && let Some(arguments) = call.strip_suffix(')')
    {
        let schema = &call[..open];
        let arguments = &arguments[open + 1..];
        let (positional, keywords) =
            split_normalized_once(arguments, ';').unwrap_or((arguments, ""));
        let field_names: &[&str] = match schema.rsplit('.').next().unwrap_or(schema) {
            "StaticWaveform" => &["freq", "amp", "sbg_id", "phase", "fct"],
            "WaveformParams" => &[
                "sbg_id",
                "freq_coeffs",
                "amp_coeffs",
                "initial_phase",
                "phase_reset",
                "fct",
            ],
            "RSPPIDConfig" => &[
                "adc_in",
                "rf_out",
                "dgt_source",
                "setpoint",
                "kp",
                "ki",
                "kd",
                "output_max",
            ],
            "RSPWaveformParams" => &["rf_out", "amp", "output_max"],
            other => {
                let _ = other;
                return Ok(serde_json::Value::String(value.to_owned()));
            }
        };
        let mut record = serde_json::Map::new();
        record.insert(
            "$type".to_owned(),
            schema
                .rsplit('.')
                .next()
                .unwrap_or(schema)
                .to_owned()
                .into(),
        );
        for (index, argument) in split_normalized_list(positional, ',')
            .into_iter()
            .filter(|value| !value.is_empty())
            .enumerate()
        {
            record.insert(
                field_names[index].to_owned(),
                normalized_to_json(argument, fields)?,
            );
        }
        for keyword in split_normalized_list(keywords, ',') {
            if keyword.is_empty() {
                continue;
            }
            let Some((name, value)) = split_normalized_once(keyword, '=') else {
                continue;
            };
            record.insert(name.to_owned(), normalized_to_json(value, fields)?);
        }
        return Ok(serde_json::Value::Object(record));
    }
    Ok(serde_json::Value::String(value.to_owned()))
}

fn parse_normalized_numeric_with_fields(
    value: &str,
    fields: &HashMap<String, String>,
) -> Option<ExactDecimal> {
    if let Some(value) = parse_normalized_numeric(value) {
        return Some(value);
    }
    if let Some(name) = value.strip_prefix("name:") {
        return parse_normalized_numeric_with_fields(fields.get(name)?, fields);
    }
    if let Some(operand) = value
        .strip_prefix("unary:USub(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric_with_fields(operand, fields)?.checked_neg();
    }
    if let Some(operands) = value
        .strip_prefix("bin:LShift(")
        .and_then(|value| value.strip_suffix(')'))
    {
        let (left, right) = split_normalized_operands(operands)?;
        let left = parse_normalized_numeric_with_fields(left, fields)?.to_cycle_count()?;
        let right = parse_normalized_numeric_with_fields(right, fields)?.to_cycle_count()?;
        return left
            .checked_shl(u32::try_from(right).ok()?)
            .map(ExactDecimal::from_u64);
    }
    for (prefix, operation) in [
        (
            "bin:Add(",
            ExactDecimal::checked_add as fn(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
        ),
        ("bin:Sub(", ExactDecimal::checked_sub),
        ("bin:Mult(", ExactDecimal::checked_mul),
        ("bin:Div(", ExactDecimal::checked_div),
    ] {
        if let Some(operands) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        {
            let (left, right) = split_normalized_operands(operands)?;
            return operation(
                parse_normalized_numeric_with_fields(left, fields)?,
                parse_normalized_numeric_with_fields(right, fields)?,
            );
        }
    }
    None
}

fn split_normalized_once(value: &str, separator: char) -> Option<(&str, &str)> {
    let mut depth = 0_u32;
    for (index, character) in value.char_indices() {
        match character {
            '(' | '[' => depth = depth.checked_add(1)?,
            ')' | ']' => depth = depth.checked_sub(1)?,
            character if character == separator && depth == 0 => {
                return Some((&value[..index], &value[index + character.len_utf8()..]));
            }
            _ => {}
        }
    }
    None
}

fn split_normalized_list(mut value: &str, separator: char) -> Vec<&str> {
    let mut values = Vec::new();
    while let Some((left, right)) = split_normalized_once(value, separator) {
        values.push(left);
        value = right;
    }
    values.push(value);
    values
}

#[cfg(test)]
mod tests {
    use super::{normalized_has_duration_unit, normalized_is_cycles_call, parse_normalized_cycles};

    #[test]
    fn normalized_duration_units_are_matched_as_complete_name_tokens() {
        assert!(normalized_has_duration_unit(
            "bin:Mult(constant:Int(80),name:ns)"
        ));
        assert!(normalized_has_duration_unit(
            "bin:Div(name:ns,constant:Int(2))"
        ));
        assert!(!normalized_has_duration_unit(
            "bin:Add(constant:Float(1.0),bin:Mult(constant:Int(0),name:ns))"
        ));
        assert!(!normalized_has_duration_unit("bin:Div(name:ns,name:us)"));
        assert!(!normalized_has_duration_unit("name:start"));
        assert!(!normalized_has_duration_unit("name:usage"));
    }

    #[test]
    fn normalized_cycles_calls_require_one_signed_integer() {
        assert!(normalized_is_cycles_call(
            "call:catseq.time_utils.cycles(constant:Int(250);)"
        ));
        assert_eq!(
            parse_normalized_cycles("call:catseq.time_utils.cycles(constant:Int(250);)")
                .and_then(|value| value.to_cycle_count()),
            Some(250)
        );
        assert!(
            parse_normalized_cycles("call:catseq.time_utils.cycles(constant:Float(1.5);)")
                .is_none()
        );
        assert_eq!(
            parse_normalized_cycles("call:catseq.time_utils.cycles(unary:USub(constant:Int(1));)")
                .and_then(|value| value.to_signed_cycle_delta()),
            Some(-1)
        );
    }
}
