use pyo3::prelude::*;

mod kernel_analysis;
mod kernel_collector;
mod kernel_registration;
mod runtime;

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<kernel_collector::PyKernelDefinitionCollection>()?;
    module.add_class::<kernel_registration::PyRegisteredKernelModules>()?;
    module.add_class::<kernel_registration::PyComputeValidation>()?;
    kernel_analysis::register(module)?;
    runtime::register(module)?;
    Ok(())
}
