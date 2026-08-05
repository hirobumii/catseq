use std::collections::BTreeMap;

use catseq_core::morphism_arena::{MorphismArenaBuilder, NativeProvenance};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{ValueExprArenaBuilder, ValueExprPayload, ValueExprType};

use super::abi_cost::oasm_call_cost;
use super::model::{
    AtomicLowering, AtomicTargetSchema, BoardEpochInput, ChannelBinding, ChannelKind, DirectEvent,
    DurationQuantization, EventOrder, LinkValue, LoopTiming, TargetBoard, TargetBoardKind,
    TtlEvent,
};
use super::scheduler::compile_board;
use super::{
    CompileEnvironment, LinkBindings, OasmArgument, OasmFunction, TargetProfile,
    compile_oasm_call_plan,
};

fn duration_program(environment_slot: bool) -> NativeArenas {
    let mut values = ValueExprArenaBuilder::new();
    let duration = if environment_slot {
        values.environment_slot("delay", ValueExprType::Duration)
    } else {
        values.runtime_slot("delay", ValueExprType::Duration)
    };
    let values = values.finish().unwrap();
    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let root = morphisms.logical_shift(duration, provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn environment_rewind_program() -> NativeArenas {
    use catseq_core::morphism_arena::BoundaryPolicy;

    let mut values = ValueExprArenaBuilder::new();
    let forward = values.constant(ValueExprPayload::DurationCycles(10));
    let rewind = values.environment_slot("rewind", ValueExprType::Duration);
    let values = values.finish().unwrap();
    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let forward = morphisms.logical_shift(forward, provenance);
    let rewind = morphisms.logical_shift(rewind, provenance);
    let root = morphisms.serial(&[forward, rewind], &[BoundaryPolicy::Auto], provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn physical_environment_interval_program() -> NativeArenas {
    let mut values = ValueExprArenaBuilder::new();
    let duration = values.environment_slot("duration", ValueExprType::Duration);
    let values = values.finish().unwrap();
    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let root = morphisms.physical_wait(duration, provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn loop_program() -> NativeArenas {
    let mut values = ValueExprArenaBuilder::new();
    let duration = values.constant(ValueExprPayload::DurationCycles(10));
    let count = values.constant(ValueExprPayload::Int64(3));
    let values = values.finish().unwrap();
    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let body = morphisms.logical_shift(duration, provenance);
    let root = morphisms.loop_region(body, count, provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn linked_native_record_program() -> NativeArenas {
    let mut values = ValueExprArenaBuilder::new();
    let enabled = values.runtime_slot("enabled", ValueExprType::Bool);
    let gain = values.runtime_slot("gain", ValueExprType::Int64);
    let fractional_gain = values.runtime_slot("fractional_gain", ValueExprType::Float64);
    let config = values.constant(ValueExprPayload::Json(serde_json::json!({
        "$type": "TestConfig",
        "enabled": {"$value_expr": enabled.index()},
        "gain": {"$value_expr": gain.index()},
        "fractional_gain": {"$value_expr": fractional_gain.index()},
    })));
    let values = values.finish().unwrap();

    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let operation = morphisms.atomic("test.rsp.rf_config", &[config], provenance);
    let template = morphisms.publish_template(operation);
    let root = morphisms.instantiate(template, "pid", provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn empty_environment() -> CompileEnvironment {
    CompileEnvironment {
        schema_version: 1,
        channels: BTreeMap::new(),
        opaque_calls: BTreeMap::new(),
    }
}

fn target() -> TargetProfile {
    TargetProfile {
        schema_version: 1,
        rtmq_abi_version: 2,
        clock_hz: 250_000_000,
        duration_quantization: DurationQuantization::Strict,
        loop_timing: LoopTiming::default(),
        boards: BTreeMap::new(),
        operations: BTreeMap::new(),
    }
}

fn direct_event(function: OasmFunction, args: Vec<OasmArgument>) -> DirectEvent {
    DirectEvent {
        epoch: 0,
        offset_cycles: 0,
        board: "rwg0".to_owned(),
        function,
        args,
        instruction_cost_cycles: 0,
        order: EventOrder::BOARD,
        group_id: 0,
        preload: false,
        loop_scope: None,
    }
}

fn ttl_event(local_id: u8, high: bool, sequence: u64) -> TtlEvent {
    TtlEvent {
        epoch: 0,
        offset_cycles: 0,
        board: "rwg0".to_owned(),
        local_id,
        high,
        instruction_cost_cycles: sequence,
        order: EventOrder::channel(super::model::ChannelKind::Ttl, local_id, sequence),
        loop_scope: None,
    }
}

fn compile_ttl_events(ttl_events: Vec<TtlEvent>) -> super::model::OasmBoardPlan {
    compile_board(BoardEpochInput {
        epoch: 0,
        origin_cycles: 0,
        address: "rwg0".to_owned(),
        board_kind: TargetBoardKind::Rwg,
        duration_cycles: 0,
        initial_cursor: 0,
        ttl_events,
        direct_events: Vec::new(),
    })
    .unwrap()
}

#[test]
fn duration_runtime_slots_require_integer_cycle_bindings() {
    let program = duration_program(false);
    let bindings = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::from([("delay".to_owned(), LinkValue::Float(5.0))]),
        environment_values: BTreeMap::new(),
    };

    let error =
        compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings).unwrap_err();

    assert!(error.to_string().contains("wrong type"));
}

#[test]
fn link_bindings_supply_environment_slots() {
    let program = duration_program(true);
    let bindings = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::new(),
        environment_values: BTreeMap::from([("delay".to_owned(), LinkValue::Unsigned(5))]),
    };

    let plan =
        compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings).unwrap();

    assert!(plan.epochs()[0].boards().is_empty());
}

#[test]
fn environment_duration_bindings_can_rewind_without_epoch_underflow() {
    let program = environment_rewind_program();
    let bindings = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::new(),
        environment_values: BTreeMap::from([("rewind".to_owned(), LinkValue::Signed(-4))]),
    };

    let plan =
        compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings).unwrap();

    assert_eq!(plan.logical_duration_cycles(), 10);
}

#[test]
fn physical_environment_intervals_remain_non_negative_after_linking() {
    let program = physical_environment_interval_program();
    let bindings = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::new(),
        environment_values: BTreeMap::from([("duration".to_owned(), LinkValue::Signed(-1))]),
    };

    let error =
        compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("physical interval duration must be non-negative"),
        "{error}"
    );
}

#[test]
fn system_environment_values_replace_per_compile_values_only() {
    let mut per_compile = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::from([("scan".to_owned(), LinkValue::Unsigned(9))]),
        environment_values: BTreeMap::from([("delay".to_owned(), LinkValue::Unsigned(1))]),
    };
    let system = LinkBindings {
        schema_version: 1,
        runtime_values: BTreeMap::new(),
        environment_values: BTreeMap::from([("delay".to_owned(), LinkValue::Unsigned(5))]),
    };

    per_compile.replace_environment_values_from(&system);

    assert_eq!(
        per_compile.runtime_values,
        BTreeMap::from([("scan".to_owned(), LinkValue::Unsigned(9))])
    );
    assert_eq!(
        per_compile.environment_values,
        BTreeMap::from([("delay".to_owned(), LinkValue::Unsigned(5))])
    );
}

#[test]
fn logical_duration_excludes_hardware_loop_scheduling_overhead() {
    let plan = compile_oasm_call_plan(
        &loop_program(),
        &empty_environment(),
        &target(),
        &LinkBindings::empty(),
    )
    .unwrap();

    assert_eq!(plan.logical_duration_cycles(), 30);
}

#[test]
fn link_values_cover_the_closed_scalar_type_set() {
    assert!(LinkValue::Bool(true).matches_type(ValueExprType::Bool));
    assert!(LinkValue::String("state".to_owned()).matches_type(ValueExprType::String));
    assert!(!LinkValue::Float(5.0).matches_type(ValueExprType::Duration));
}

#[test]
fn runtime_links_preserve_native_record_json_scalar_types() {
    let environment = CompileEnvironment {
        schema_version: 1,
        channels: BTreeMap::from([(
            "pid".to_owned(),
            ChannelBinding {
                board: "rsp0".to_owned(),
                local_id: 0,
                kind: ChannelKind::Rsp,
            },
        )]),
        opaque_calls: BTreeMap::new(),
    };
    let mut target = target();
    target.boards.insert(
        "rsp0".to_owned(),
        TargetBoard {
            kind: TargetBoardKind::Rsp,
            ttl_width: 0,
        },
    );
    target.operations.insert(
        "test.rsp.rf_config".to_owned(),
        AtomicTargetSchema {
            lowering: AtomicLowering::RspRfConfig,
            duration_argument: None,
            fixed_duration_cycles: None,
            board: None,
            instruction_cost_cycles: 0,
        },
    );
    let program = linked_native_record_program();

    for enabled in [true, false] {
        let bindings = LinkBindings {
            schema_version: 1,
            runtime_values: BTreeMap::from([
                ("enabled".to_owned(), LinkValue::Bool(enabled)),
                ("gain".to_owned(), LinkValue::Signed(7)),
                ("fractional_gain".to_owned(), LinkValue::Float(7.0)),
            ]),
            environment_values: BTreeMap::new(),
        };

        let plan = compile_oasm_call_plan(&program, &environment, &target, &bindings).unwrap();

        assert_eq!(
            plan.epochs()[0].boards()[0].calls()[0].args,
            vec![OasmArgument::Json(serde_json::json!({
                "$type": "TestConfig",
                "enabled": enabled,
                "gain": 7,
                "fractional_gain": 7.0,
            }))]
        );
    }
}

#[test]
fn oasm_instruction_occupancy_is_a_target_lowering_property() {
    let play = direct_event(
        OasmFunction::RwgPlay,
        vec![OasmArgument::Unsigned(1), OasmArgument::Unsigned(1)],
    );
    let zero_carrier = direct_event(
        OasmFunction::RwgSetCarrier,
        vec![OasmArgument::Unsigned(0), OasmArgument::Float(0.0)],
    );
    let ordinary_carrier = direct_event(
        OasmFunction::RwgSetCarrier,
        vec![OasmArgument::Unsigned(0), OasmArgument::Float(100.0)],
    );

    assert_eq!(oasm_call_cost(&play).unwrap(), 15);
    assert_eq!(oasm_call_cost(&zero_carrier).unwrap(), 16);
    assert_eq!(oasm_call_cost(&ordinary_carrier).unwrap(), 18);
}

#[test]
fn same_instant_ttl_writes_use_last_program_order() {
    for (events, expected_state) in [
        (vec![ttl_event(0, false, 2), ttl_event(0, true, 1)], 0),
        (vec![ttl_event(0, true, 2), ttl_event(0, false, 1)], 1),
        (
            vec![
                ttl_event(0, true, 3),
                ttl_event(0, false, 2),
                ttl_event(0, true, 1),
            ],
            1,
        ),
    ] {
        let plan = compile_ttl_events(events);

        assert_eq!(plan.calls().len(), 1);
        assert_eq!(plan.calls()[0].function, OasmFunction::TtlSet);
        assert_eq!(
            plan.calls()[0].args,
            vec![
                OasmArgument::Unsigned(1),
                OasmArgument::Unsigned(expected_state),
                OasmArgument::String("rwg".to_owned()),
            ]
        );
    }
}

#[test]
fn same_instant_ttl_channels_remain_mask_coalesced_and_deterministic() {
    let first = compile_ttl_events(vec![
        ttl_event(1, true, 4),
        ttl_event(0, false, 3),
        ttl_event(1, false, 2),
        ttl_event(0, true, 1),
    ]);
    let second = compile_ttl_events(vec![
        ttl_event(0, true, 1),
        ttl_event(1, false, 2),
        ttl_event(0, false, 3),
        ttl_event(1, true, 4),
    ]);

    assert_eq!(first, second);
    assert_eq!(first.calls().len(), 1);
    assert_eq!(
        first.calls()[0].args,
        vec![
            OasmArgument::Unsigned(0b11),
            OasmArgument::Unsigned(0b10),
            OasmArgument::String("rwg".to_owned()),
        ]
    );
}
