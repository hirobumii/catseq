//! Native Morphism DAG lowering and linking to Python OASM calls.

use catseq_core::native_arenas::NativeArenas;

mod abi_cost;
mod arena_util;
mod atomic_lowering;
mod epochs;
mod event_lowering;
mod loop_lowering;
mod model;
mod plan_builder;
mod scheduler;
mod timing;
mod validate;
mod value_eval;

use epochs::analyze_epochs;
use event_lowering::lower_events;
pub use model::{
    ChannelBinding, ChannelKind, CompileEnvironment, LinkBindings, OasmArgument, OasmBoardPlan,
    OasmCall, OasmCallPlan, OasmCompileError, OasmEpochPlan, OasmFunction, TargetProfile,
};
use plan_builder::build_call_plan;
use timing::analyze_timing;
use validate::validate_inputs;

/// Lower, schedule and link native arenas into calls understood by the
/// existing Python OASM adapter. No Python object participates in this pass.
pub fn compile_oasm_call_plan(
    program: &NativeArenas,
    environment: &CompileEnvironment,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<OasmCallPlan, OasmCompileError> {
    validate_inputs(environment, target, link_bindings)?;
    let timing = analyze_timing(program, target, link_bindings)?;
    let epochs = analyze_epochs(program, target)?;
    let lowered = lower_events(program, environment, target, &timing, &epochs)?;
    build_call_plan(program, target, &timing, &epochs, lowered)
}

#[cfg(test)]
mod tests;
