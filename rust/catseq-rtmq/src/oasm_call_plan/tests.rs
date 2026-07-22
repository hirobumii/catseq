use std::collections::BTreeMap;

use catseq_core::morphism_arena::{MorphismArenaBuilder, NativeProvenance};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{ValueExprArenaBuilder, ValueExprPayload, ValueExprType};

use super::abi_cost::oasm_call_cost;
use super::model::{DirectEvent, DurationQuantization, EventOrder, LinkValue, LoopTiming};
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
    let root = morphisms.wait(duration, provenance);
    NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
}

fn loop_program() -> NativeArenas {
    let mut values = ValueExprArenaBuilder::new();
    let duration = values.constant(ValueExprPayload::DurationCycles(10));
    let count = values.constant(ValueExprPayload::Int64(3));
    let values = values.finish().unwrap();
    let mut morphisms = MorphismArenaBuilder::new();
    let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let body = morphisms.wait(duration, provenance);
    let root = morphisms.loop_region(body, count, provenance);
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
