//! Atomic Morphism operations lowered into board-addressed OASM events.

use std::collections::HashMap;

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{RwgWaveformDerivation, ValueExprId, ValueExprPayload};

use super::model::{
    AtomicLowering, AtomicTargetSchema, ChannelBinding, ChannelKind, DirectEvent,
    DurationQuantization, EventOrder, OasmArgument, OasmCompileError, OasmFunction,
    RwgChannelState, RwgPlayTransition, TargetBoard, TtlEvent,
};
use super::value_eval::{
    bool_argument, eval_duration_cycles, json_argument, json_value, value_to_oasm_argument,
};

#[allow(clippy::too_many_arguments)]
pub(super) fn lower_atomic_events(
    schema: &AtomicTargetSchema,
    channel_key: &str,
    binding: &ChannelBinding,
    board: &TargetBoard,
    start: u64,
    epoch: u32,
    duration: u64,
    arguments: &[ValueExprId],
    program: &NativeArenas,
    evaluated_values: &[Result<ExactDecimal, OasmCompileError>],
    clock_hz: u64,
    duration_quantization: DurationQuantization,
    group_id: u64,
    rwg_states: &mut HashMap<String, RwgChannelState>,
    rsp_pid_configs: &mut HashMap<String, serde_json::Value>,
    ttl_events: &mut Vec<TtlEvent>,
    direct_events: &mut Vec<DirectEvent>,
) -> Result<(), OasmCompileError> {
    let argument = |index: usize| -> Result<OasmArgument, OasmCompileError> {
        let id = arguments
            .get(index)
            .copied()
            .ok_or_else(|| OasmCompileError::new(format!("Atomic argument {index} is absent")))?;
        value_to_oasm_argument(program, evaluated_values, id)
    };
    let direct = |offset_cycles: u64,
                  function: OasmFunction,
                  args: Vec<OasmArgument>,
                  direct_events: &mut Vec<DirectEvent>| {
        direct_events.push(DirectEvent {
            epoch,
            offset_cycles,
            board: binding.board.clone(),
            function,
            args,
            instruction_cost_cycles: schema.instruction_cost_cycles,
            order: EventOrder::channel(binding.kind, binding.local_id, group_id),
            group_id,
            preload: false,
            loop_scope: None,
        });
    };
    let validate_kind = |expected: ChannelKind| {
        if binding.kind == expected {
            Ok(())
        } else {
            Err(OasmCompileError::new(format!(
                "channel on {} has kind {:?}, expected {:?}",
                binding.board, binding.kind, expected
            )))
        }
    };
    match schema.lowering {
        AtomicLowering::TtlSetHigh | AtomicLowering::TtlSetLow => {
            validate_kind(ChannelKind::Ttl)?;
            if binding.local_id >= board.ttl_width || board.ttl_width > 64 {
                return Err(OasmCompileError::new("invalid TTL local id"));
            }
            let high = schema.lowering != AtomicLowering::TtlSetLow;
            ttl_events.push(TtlEvent {
                epoch,
                offset_cycles: start,
                board: binding.board.clone(),
                local_id: binding.local_id,
                high,
                instruction_cost_cycles: schema.instruction_cost_cycles,
                order: EventOrder::channel(binding.kind, binding.local_id, group_id),
                loop_scope: None,
            });
        }
        AtomicLowering::TtlInitialize => {
            validate_kind(ChannelKind::Ttl)?;
            direct(
                start,
                OasmFunction::TtlConfig,
                vec![
                    OasmArgument::Unsigned(1_u64 << binding.local_id),
                    OasmArgument::Unsigned(0),
                ],
                direct_events,
            );
        }
        AtomicLowering::RwgInitialize => {
            validate_kind(ChannelKind::Rwg)?;
            let hard = arguments
                .get(1)
                .copied()
                .and_then(|id| bool_argument(program, id))
                .unwrap_or(false);
            if hard {
                direct(start, OasmFunction::RwgInit, vec![], direct_events);
            }
            direct(
                start
                    .checked_add(duration)
                    .ok_or_else(|| OasmCompileError::new("RWG init timestamp overflows"))?,
                OasmFunction::RwgSetCarrier,
                vec![
                    OasmArgument::Unsigned(binding.local_id.into()),
                    argument(0)?,
                ],
                direct_events,
            );
            rwg_states.insert(channel_key.to_owned(), RwgChannelState::Ready);
        }
        AtomicLowering::RwgLoad => {
            validate_kind(ChannelKind::Rwg)?;
            let waveform_expr = arguments
                .first()
                .copied()
                .ok_or_else(|| OasmCompileError::new("RWG load requires a waveform expression"))?;
            let waveform_payload = program
                .values()
                .payload(waveform_expr)
                .map_err(|error| OasmCompileError::new(error.to_string()))?;
            if matches!(waveform_payload, Some(ValueExprPayload::Json(_))) {
                let waveforms = json_value(program, waveform_expr, evaluated_values)?;
                let waveforms = waveforms.as_array().ok_or_else(|| {
                    OasmCompileError::new("RWG load requires a waveform aggregate")
                })?;
                validate_waveform_params(waveforms)?;
                let rf_on = match rwg_states.get(channel_key) {
                    Some(RwgChannelState::Ready) => false,
                    Some(RwgChannelState::Active { rf_on, .. })
                    | Some(RwgChannelState::ActiveUnknown { rf_on }) => *rf_on,
                    Some(
                        RwgChannelState::WaveformsLoaded { .. } | RwgChannelState::Ramping { .. },
                    ) => {
                        return Err(OasmCompileError::new(
                            "RWG load cannot interrupt a pending waveform transition",
                        ));
                    }
                    None => {
                        return Err(OasmCompileError::new(
                            "RWG load requires a preceding initialize operation",
                        ));
                    }
                };
                let transition = static_snapshot_from_waveforms(waveforms)
                    .map(|snapshot| RwgPlayTransition::Activate { snapshot })
                    .unwrap_or(RwgPlayTransition::ActivateUnknown);
                emit_prepared_rwg_loads(
                    binding,
                    start,
                    epoch,
                    waveforms.to_vec(),
                    schema.instruction_cost_cycles,
                    group_id,
                    direct_events,
                );
                rwg_states.insert(
                    channel_key.to_owned(),
                    RwgChannelState::WaveformsLoaded {
                        rf_on,
                        transition,
                        preload_group_id: group_id,
                    },
                );
                return Ok(());
            }
            let Some(ValueExprPayload::RwgWaveforms(derivation)) = waveform_payload else {
                return Err(OasmCompileError::new(
                    "RWG load requires waveform parameters",
                ));
            };
            let expression_arguments = program
                .values()
                .children(waveform_expr)
                .map_err(|error| OasmCompileError::new(error.to_string()))?;
            let (waveforms, rf_on, transition) = match derivation {
                RwgWaveformDerivation::Static => {
                    let targets = expression_arguments
                        .first()
                        .copied()
                        .ok_or_else(|| OasmCompileError::new("static waveforms require targets"))?;
                    let targets = json_value(program, targets, evaluated_values)?;
                    let targets = targets.as_array().ok_or_else(|| {
                        OasmCompileError::new("RWG targets must be a native aggregate")
                    })?;
                    let phase_reset = expression_arguments
                        .get(1)
                        .copied()
                        .and_then(|id| bool_argument(program, id))
                        .unwrap_or(true);
                    let rf_on = match rwg_states.get(channel_key) {
                        Some(RwgChannelState::Ready) => false,
                        Some(RwgChannelState::Active { rf_on, .. })
                        | Some(RwgChannelState::ActiveUnknown { rf_on }) => *rf_on,
                        Some(
                            RwgChannelState::WaveformsLoaded { .. }
                            | RwgChannelState::Ramping { .. },
                        ) => {
                            return Err(OasmCompileError::new(
                                "RWG set_state cannot interrupt a pending waveform transition",
                            ));
                        }
                        None => {
                            return Err(OasmCompileError::new(
                                "RWG set_state requires a preceding initialize operation",
                            ));
                        }
                    };
                    validate_static_waveforms(targets, true)?;
                    (
                        build_static_waveforms(targets, phase_reset),
                        rf_on,
                        RwgPlayTransition::Activate {
                            snapshot: targets.to_vec(),
                        },
                    )
                }
                RwgWaveformDerivation::Linear => {
                    let targets = expression_arguments
                        .first()
                        .copied()
                        .ok_or_else(|| OasmCompileError::new("linear waveforms require targets"))?;
                    let duration_id = expression_arguments.get(1).copied().ok_or_else(|| {
                        OasmCompileError::new("linear waveforms require a duration")
                    })?;
                    let ramp_duration =
                        eval_duration_cycles(evaluated_values, duration_id, duration_quantization)?;
                    if ramp_duration == 0 {
                        return Err(OasmCompileError::new(
                            "RWG linear_ramp duration must be positive",
                        ));
                    }
                    let targets = json_value(program, targets, evaluated_values)?;
                    let targets = targets.as_array().ok_or_else(|| {
                        OasmCompileError::new("RWG targets must be a native aggregate")
                    })?;
                    validate_static_waveforms(targets, false)?;
                    let Some(RwgChannelState::Active { rf_on, snapshot }) =
                        rwg_states.get(channel_key).cloned()
                    else {
                        return Err(OasmCompileError::new(
                            "RWG linear_ramp requires an active channel state",
                        ));
                    };
                    if targets.len() != snapshot.len() {
                        return Err(OasmCompileError::new(format!(
                            "RWG linear_ramp target count {} does not match active SBG count {}",
                            targets.len(),
                            snapshot.len()
                        )));
                    }
                    let duration_us = ramp_duration as f64 * 1_000_000.0 / clock_hz as f64;
                    let (ramp, static_stop, end_snapshot) =
                        build_linear_ramp_waveforms(&snapshot, targets, duration_us)?;
                    (
                        ramp,
                        rf_on,
                        RwgPlayTransition::StartRamp {
                            static_stop,
                            end_snapshot,
                        },
                    )
                }
                RwgWaveformDerivation::RampEndpoint => {
                    if expression_arguments.len() != 1 {
                        return Err(OasmCompileError::new(
                            "RWG linear ramp endpoint requires its ramp waveform expression",
                        ));
                    }
                    let Some(RwgChannelState::Ramping {
                        rf_on,
                        static_stop,
                        end_snapshot,
                    }) = rwg_states.get(channel_key).cloned()
                    else {
                        return Err(OasmCompileError::new(
                            "RWG linear ramp endpoint has no preceding ramp play",
                        ));
                    };
                    (
                        static_stop,
                        rf_on,
                        RwgPlayTransition::FinishRamp { end_snapshot },
                    )
                }
            };
            emit_prepared_rwg_loads(
                binding,
                start,
                epoch,
                waveforms,
                schema.instruction_cost_cycles,
                group_id,
                direct_events,
            );
            rwg_states.insert(
                channel_key.to_owned(),
                RwgChannelState::WaveformsLoaded {
                    rf_on,
                    transition,
                    preload_group_id: group_id,
                },
            );
        }
        AtomicLowering::RwgPlay => {
            validate_kind(ChannelKind::Rwg)?;
            match rwg_states.get(channel_key).cloned() {
                Some(RwgChannelState::WaveformsLoaded {
                    rf_on,
                    transition,
                    preload_group_id,
                }) => {
                    emit_rwg_play(
                        binding,
                        start,
                        epoch,
                        schema.instruction_cost_cycles,
                        preload_group_id,
                        direct_events,
                    );
                    let next = match transition {
                        RwgPlayTransition::Activate { snapshot } => {
                            RwgChannelState::Active { rf_on, snapshot }
                        }
                        RwgPlayTransition::ActivateUnknown => {
                            RwgChannelState::ActiveUnknown { rf_on }
                        }
                        RwgPlayTransition::StartRamp {
                            static_stop,
                            end_snapshot,
                        } => RwgChannelState::Ramping {
                            rf_on,
                            static_stop,
                            end_snapshot,
                        },
                        RwgPlayTransition::FinishRamp { end_snapshot } => RwgChannelState::Active {
                            rf_on,
                            snapshot: end_snapshot,
                        },
                    };
                    rwg_states.insert(channel_key.to_owned(), next);
                }
                Some(_) => {
                    return Err(OasmCompileError::new(
                        "RWG play requires a preceding waveform load",
                    ));
                }
                None => {
                    return Err(OasmCompileError::new(
                        "RWG play requires a preceding initialize operation",
                    ));
                }
            }
        }
        AtomicLowering::RwgRfOn | AtomicLowering::RwgRfOff => {
            validate_kind(ChannelKind::Rwg)?;
            let state = rwg_states.get_mut(channel_key).ok_or_else(|| {
                OasmCompileError::new("RWG RF switch requires a preceding initialize operation")
            })?;
            if matches!(
                state,
                RwgChannelState::WaveformsLoaded { .. } | RwgChannelState::Ramping { .. }
            ) {
                return Err(OasmCompileError::new(
                    "RWG RF switch cannot interrupt an active ramp template",
                ));
            }
            let mask = 1_u64 << binding.local_id;
            let off = schema.lowering == AtomicLowering::RwgRfOff;
            direct(
                start,
                OasmFunction::RwgRfSwitch,
                vec![
                    OasmArgument::Unsigned(mask),
                    OasmArgument::Unsigned(if off { mask } else { 0 }),
                ],
                direct_events,
            );
            match state {
                RwgChannelState::Active { rf_on, .. }
                | RwgChannelState::ActiveUnknown { rf_on } => *rf_on = !off,
                RwgChannelState::Ready => {}
                RwgChannelState::WaveformsLoaded { .. } | RwgChannelState::Ramping { .. } => {
                    unreachable!("pending transitions were rejected above")
                }
            }
        }
        AtomicLowering::RspInitialize => {
            validate_kind(ChannelKind::Rsp)?;
            let mut args = Vec::new();
            for index in 1..arguments.len() {
                args.push(argument(index)?);
            }
            direct(start, OasmFunction::RspInit, args, direct_events);
            direct(
                start
                    .checked_add(duration)
                    .ok_or_else(|| OasmCompileError::new("RSP init timestamp overflows"))?,
                OasmFunction::RspSetCarrier,
                vec![
                    OasmArgument::Unsigned(binding.local_id.into()),
                    argument(0)?,
                ],
                direct_events,
            );
        }
        AtomicLowering::RspPidConfig => {
            validate_kind(ChannelKind::Rsp)?;
            let config = json_argument(program, arguments, 0, evaluated_values)?;
            rsp_pid_configs.insert(channel_key.to_owned(), config.clone());
            direct(
                start,
                OasmFunction::RspPidConfig,
                vec![OasmArgument::Json(config)],
                direct_events,
            );
        }
        AtomicLowering::RspPidStart | AtomicLowering::RspPidHold => {
            validate_kind(ChannelKind::Rsp)?;
            let config = rsp_pid_configs.get(channel_key).ok_or_else(|| {
                OasmCompileError::new("RSP PID operation requires a preceding pid_config")
            })?;
            let dgt_source = config
                .get("dgt_source")
                .and_then(json_u64)
                .ok_or_else(|| OasmCompileError::new("RSP PID config has no dgt_source"))?;
            direct(
                start,
                if schema.lowering == AtomicLowering::RspPidStart {
                    OasmFunction::RspPidStart
                } else {
                    OasmFunction::RspPidHold
                },
                vec![OasmArgument::Unsigned(dgt_source)],
                direct_events,
            );
        }
        AtomicLowering::RspPidRelease | AtomicLowering::RspPidRelink => {
            validate_kind(ChannelKind::Rsp)?;
            let config = rsp_pid_configs.get(channel_key).cloned().ok_or_else(|| {
                OasmCompileError::new("RSP PID operation requires a preceding pid_config")
            })?;
            direct(
                start,
                if schema.lowering == AtomicLowering::RspPidRelease {
                    OasmFunction::RspPidRelease
                } else {
                    OasmFunction::RspPidRelink
                },
                vec![OasmArgument::Json(config)],
                direct_events,
            );
        }
        AtomicLowering::RspRfConfig => direct(
            start,
            OasmFunction::RspRfConfig,
            vec![argument(0)?],
            direct_events,
        ),
        AtomicLowering::GlobalSync | AtomicLowering::Opaque => {
            unreachable!("handled by caller")
        }
    }
    Ok(())
}

fn validate_static_waveforms(
    targets: &[serde_json::Value],
    require_sbg_id: bool,
) -> Result<(), OasmCompileError> {
    for target in targets {
        let object = target
            .as_object()
            .ok_or_else(|| OasmCompileError::new("RWG target is not a StaticWaveform record"))?;
        if require_sbg_id && object.get("sbg_id").and_then(json_u64).is_none() {
            return Err(OasmCompileError::new(format!(
                "RWG set_state requires an integer sbg_id for every target; found {target}"
            )));
        }
    }
    Ok(())
}

fn validate_waveform_params(waveforms: &[serde_json::Value]) -> Result<(), OasmCompileError> {
    for waveform in waveforms {
        let object = waveform
            .as_object()
            .ok_or_else(|| OasmCompileError::new("RWG load item is not a WaveformParams record"))?;
        if object.get("sbg_id").and_then(json_u64).is_none() {
            return Err(OasmCompileError::new(format!(
                "RWG load requires an integer sbg_id; found {waveform}"
            )));
        }
        for field in ["freq_coeffs", "amp_coeffs"] {
            if !object
                .get(field)
                .is_some_and(|coefficients| coefficients.is_array())
            {
                return Err(OasmCompileError::new(format!(
                    "RWG load requires array-valued {field}; found {waveform}"
                )));
            }
        }
    }
    Ok(())
}

fn static_snapshot_from_waveforms(
    waveforms: &[serde_json::Value],
) -> Option<Vec<serde_json::Value>> {
    waveforms
        .iter()
        .map(|waveform| {
            let object = waveform.as_object()?;
            let static_coefficient = |field: &str| {
                let coefficients = object.get(field)?.as_array()?;
                let value = coefficients.first()?.as_f64()?;
                coefficients
                    .iter()
                    .skip(1)
                    .all(|coefficient| coefficient.is_null() || coefficient.as_f64() == Some(0.0))
                    .then_some(value)
            };
            Some(serde_json::json!({
                "$type": "StaticWaveform",
                "sbg_id": object.get("sbg_id")?.clone(),
                "freq": static_coefficient("freq_coeffs")?,
                "amp": static_coefficient("amp_coeffs")?,
                "phase": object
                    .get("initial_phase")
                    .and_then(serde_json::Value::as_f64)
                    .unwrap_or(0.0),
                "fct": object.get("fct").cloned().unwrap_or(serde_json::Value::Null),
            }))
        })
        .collect()
}

type RwgRampTransition = (
    Vec<serde_json::Value>,
    Vec<serde_json::Value>,
    Vec<serde_json::Value>,
);

fn build_linear_ramp_waveforms(
    current: &[serde_json::Value],
    targets: &[serde_json::Value],
    duration_us: f64,
) -> Result<RwgRampTransition, OasmCompileError> {
    let mut ramp = Vec::with_capacity(targets.len());
    let mut static_stop = Vec::with_capacity(targets.len());
    let mut end_snapshot = Vec::with_capacity(targets.len());
    for (current, target) in current.iter().zip(targets) {
        let current = current.as_object().ok_or_else(|| {
            OasmCompileError::new("active RWG snapshot is not a StaticWaveform record")
        })?;
        let target = target.as_object().ok_or_else(|| {
            OasmCompileError::new("RWG ramp target is not a StaticWaveform record")
        })?;
        let sbg_id = current
            .get("sbg_id")
            .and_then(json_u64)
            .ok_or_else(|| OasmCompileError::new("active RWG waveform has no integer sbg_id"))?;
        let current_fct = current
            .get("fct")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let target_fct = target
            .get("fct")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        if current_fct != target_fct {
            return Err(OasmCompileError::new(format!(
                "RWG ramp fct mismatch for SBG {sbg_id}"
            )));
        }
        let start_freq = required_json_number(current.get("freq"), "active RWG frequency")?;
        let start_amp = required_json_number(current.get("amp"), "active RWG amplitude")?;
        let target_freq = optional_json_number(target.get("freq"))?.unwrap_or(start_freq);
        let target_amp = optional_json_number(target.get("amp"))?.unwrap_or(start_amp);
        let freq_rate = (target_freq - start_freq) / duration_us;
        let amp_rate = (target_amp - start_amp) / duration_us;
        let ramp_coefficients = |start: f64, rate: f64| {
            if rate == 0.0 {
                serde_json::json!([null, null, null, null])
            } else {
                serde_json::json!([start, rate, null, null])
            }
        };
        ramp.push(serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": ramp_coefficients(start_freq, freq_rate),
            "amp_coeffs": ramp_coefficients(start_amp, amp_rate),
            "initial_phase": 0.0,
            "phase_reset": false,
            "fct": current_fct,
        }));
        static_stop.push(serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": [target_freq, 0.0, null, null],
            "amp_coeffs": [target_amp, 0.0, null, null],
            "initial_phase": 0.0,
            "phase_reset": false,
            "fct": target_fct,
        }));
        end_snapshot.push(serde_json::json!({
            "$type": "StaticWaveform",
            "sbg_id": sbg_id,
            "freq": target_freq,
            "amp": target_amp,
            "phase": 0.0,
            "fct": target_fct,
        }));
    }
    Ok((ramp, static_stop, end_snapshot))
}

pub(super) fn optional_json_number(
    value: Option<&serde_json::Value>,
) -> Result<Option<f64>, OasmCompileError> {
    match value {
        None | Some(serde_json::Value::Null) => Ok(None),
        Some(value) => value
            .as_f64()
            .map(Some)
            .ok_or_else(|| OasmCompileError::new("RWG waveform value is not numeric")),
    }
}

fn json_u64(value: &serde_json::Value) -> Option<u64> {
    value.as_u64().or_else(|| {
        let value = value.as_f64()?;
        (value.is_finite() && value >= 0.0 && value.fract() == 0.0 && value <= u64::MAX as f64)
            .then_some(value as u64)
    })
}

fn required_json_number(
    value: Option<&serde_json::Value>,
    description: &str,
) -> Result<f64, OasmCompileError> {
    optional_json_number(value)?
        .ok_or_else(|| OasmCompileError::new(format!("{description} is absent")))
}

fn build_static_waveforms(
    targets: &[serde_json::Value],
    phase_reset: bool,
) -> Vec<serde_json::Value> {
    targets
        .iter()
        .map(|target| {
        let target = target.as_object().cloned().unwrap_or_default();
        let sbg_id = target
            .get("sbg_id")
            .and_then(json_u64)
            .expect("validated set_state target has an integer sbg_id");
            serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": [target.get("freq").cloned().unwrap_or(serde_json::Value::Null), null, null, null],
            "amp_coeffs": [target.get("amp").cloned().unwrap_or(serde_json::Value::Null), null, null, null],
            "initial_phase": target.get("phase").cloned().unwrap_or_else(|| serde_json::Value::from(0.0)),
            "phase_reset": phase_reset,
            "fct": target.get("fct").cloned().unwrap_or(serde_json::Value::Null)
            })
        })
        .collect()
}

fn emit_prepared_rwg_loads(
    binding: &ChannelBinding,
    offset_cycles: u64,
    epoch: u32,
    waveforms: Vec<serde_json::Value>,
    instruction_cost_cycles: u64,
    group_id: u64,
    events: &mut Vec<DirectEvent>,
) {
    for waveform in waveforms {
        events.push(DirectEvent {
            epoch,
            offset_cycles,
            board: binding.board.clone(),
            function: OasmFunction::RwgLoadWaveform,
            args: vec![OasmArgument::Json(waveform)],
            instruction_cost_cycles,
            order: EventOrder::channel(binding.kind, binding.local_id, group_id),
            group_id,
            preload: true,
            loop_scope: None,
        });
    }
}

fn emit_rwg_play(
    binding: &ChannelBinding,
    offset_cycles: u64,
    epoch: u32,
    instruction_cost_cycles: u64,
    group_id: u64,
    events: &mut Vec<DirectEvent>,
) {
    let mask = 1_u64 << binding.local_id;
    events.push(DirectEvent {
        epoch,
        offset_cycles,
        board: binding.board.clone(),
        function: OasmFunction::RwgPlay,
        args: vec![OasmArgument::Unsigned(mask), OasmArgument::Unsigned(mask)],
        instruction_cost_cycles,
        order: EventOrder::channel(binding.kind, binding.local_id, group_id),
        group_id,
        preload: false,
        loop_scope: None,
    });
}
