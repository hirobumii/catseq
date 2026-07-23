//! Side-effectful RTMQ Download runtime.

mod execution;
mod model;
pub mod protocol;
mod transport;

pub use execution::{
    BoardExecutionState, DeviceExceptionReport, ExecutionCertainty, RuntimeFailure,
    RuntimeFailureCode, RuntimeSuccess, execute_oasm_program,
};
pub use model::{
    AssembledOasmBoard, AssembledOasmProgram, BoardEndpoint, LinuxRawEthernetRuntimeConfig,
    OasmAddress, RuntimeContractError, RuntimeContractErrorCode, derive_destination_mac,
    validate_runtime_handoff,
};
