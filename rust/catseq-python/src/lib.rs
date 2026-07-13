mod bindings;

use pyo3::prelude::*;

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    bindings::add_to_module(module)
}
