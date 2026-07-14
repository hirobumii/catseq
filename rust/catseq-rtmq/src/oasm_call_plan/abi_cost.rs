//! RTMQ ABI instruction occupancy used only during target scheduling.

use super::atomic_lowering::optional_json_number;
use super::{DirectEvent, OasmArgument, OasmCompileError, OasmFunction};

pub(super) fn oasm_call_cost(event: &DirectEvent) -> Result<u64, OasmCompileError> {
    let fixed = match event.function {
        OasmFunction::LoopBegin | OasmFunction::LoopEnd | OasmFunction::UserDefinedFunc => 0,
        OasmFunction::TtlConfig => 2,
        OasmFunction::TtlSet => 1,
        OasmFunction::RwgInit => 53,
        OasmFunction::RwgSetCarrier => rwg_set_carrier_cost(event)?,
        OasmFunction::RwgRfSwitch => event
            .args
            .first()
            .and_then(unsigned_argument)
            .map_or(1, |mask| u64::from(mask.count_ones())),
        OasmFunction::RwgLoadWaveform => return rwg_load_waveform_cost(event),
        OasmFunction::RwgPlay => 15,
        OasmFunction::WaitMaster => 8,
        OasmFunction::TrigSlave => 17,
        OasmFunction::RspInit => 11,
        OasmFunction::RspSetCarrier => 37,
        OasmFunction::RspPidConfig => 39,
        OasmFunction::RspPidStart => 3,
        OasmFunction::RspPidHold => 2,
        OasmFunction::RspPidRelease | OasmFunction::RspPidRelink => 15,
        OasmFunction::RspRfConfig => 13,
        OasmFunction::Wait => 0,
    };
    Ok(fixed)
}

fn rwg_set_carrier_cost(event: &DirectEvent) -> Result<u64, OasmCompileError> {
    let frequency = match event.args.get(1) {
        Some(OasmArgument::Float(value)) => *value,
        Some(OasmArgument::Unsigned(value)) => *value as f64,
        Some(OasmArgument::Signed(value)) => *value as f64,
        _ => {
            return Err(OasmCompileError::new(
                "rwg_set_carrier requires a numeric frequency",
            ));
        }
    };
    Ok(if frequency == 0.0 {
        16
    } else if frequency == 250.0 {
        17
    } else {
        18
    })
}

fn unsigned_argument(argument: &OasmArgument) -> Option<u64> {
    match argument {
        OasmArgument::Unsigned(value) => Some(*value),
        _ => None,
    }
}

fn rwg_load_waveform_cost(event: &DirectEvent) -> Result<u64, OasmCompileError> {
    let waveform = match event.args.first() {
        Some(OasmArgument::Json(serde_json::Value::Object(waveform))) => waveform,
        _ => {
            return Err(OasmCompileError::new(
                "rwg_load_waveform requires one waveform record",
            ));
        }
    };
    let fct =
        optional_json_number(waveform.get("fct"))?.unwrap_or(0x1_0000_0000_u64 as f64 / 250.0);
    let mut cost = 4_u64; // SFS+CLO for FTE config, then FTE and APE high writes.
    cost = cost
        .checked_add(rwg_coefficients_cost(
            waveform.get("freq_coeffs"),
            fct,
            false,
        )?)
        .ok_or_else(|| OasmCompileError::new("RWG waveform cost overflows u64"))?;
    if let Some(phase) = optional_json_number(waveform.get("initial_phase"))? {
        let encoded = (phase * 0x10_0000_u64 as f64).round_ties_even() as i128;
        cost += immediate_write_cost(encoded & 0xF_FFFF);
    }
    cost = cost
        .checked_add(rwg_coefficients_cost(
            waveform.get("amp_coeffs"),
            0x7FFF_FFFF_u64 as f64,
            true,
        )?)
        .ok_or_else(|| OasmCompileError::new("RWG waveform cost overflows u64"))?;
    Ok(cost)
}

fn rwg_coefficients_cost(
    value: Option<&serde_json::Value>,
    fct: f64,
    amplitude: bool,
) -> Result<u64, OasmCompileError> {
    let coefficients = value
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| OasmCompileError::new("RWG coefficients must be an array"))?;
    let scale: f64 = 8192.0 / 250.0;
    coefficients
        .iter()
        .enumerate()
        .try_fold(0_u64, |cost, (order, coefficient)| {
            let Some(coefficient) = optional_json_number(Some(coefficient))? else {
                return Ok(cost);
            };
            let encoded = (coefficient * fct * scale.powi(order as i32)).round_ties_even() as i128;
            let encoded = if amplitude { encoded >> 12 } else { encoded };
            cost.checked_add(immediate_write_cost(encoded))
                .ok_or_else(|| OasmCompileError::new("RWG coefficient write cost overflows u64"))
        })
}

const fn immediate_write_cost(value: i128) -> u64 {
    let low = value & 0xFFFF_FFFF;
    if low == 0 || low == 0xFFFF_FFFF { 1 } else { 2 }
}
