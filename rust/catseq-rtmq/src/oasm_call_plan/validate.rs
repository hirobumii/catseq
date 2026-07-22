//! Validation of the versioned inputs accepted by the OASM backend.

use super::model::{CompileEnvironment, LinkBindings, OasmCompileError, TargetProfile};

pub(super) fn validate_inputs(
    environment: &CompileEnvironment,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<(), OasmCompileError> {
    if environment.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported compile environment schema {}",
            environment.schema_version
        )));
    }
    if target.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported target profile schema {}",
            target.schema_version
        )));
    }
    if target.rtmq_abi_version != 2 {
        return Err(OasmCompileError::new(format!(
            "unsupported RTMQ ABI version {}",
            target.rtmq_abi_version
        )));
    }
    if target.clock_hz == 0 {
        return Err(OasmCompileError::new("clock_hz must be nonzero"));
    }
    if link_bindings.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported link bindings schema {}",
            link_bindings.schema_version
        )));
    }
    Ok(())
}
