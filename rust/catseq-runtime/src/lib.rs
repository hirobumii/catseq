//! Side-effectful RTMQ Download runtime.

mod model;

pub use model::{
    AssembledOasmBoard, AssembledOasmProgram, BoardEndpoint, LinuxRawEthernetRuntimeConfig,
    OasmAddress, RuntimeContractError, RuntimeContractErrorCode, derive_destination_mac,
    validate_runtime_handoff,
};
