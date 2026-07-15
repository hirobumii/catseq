use catseq_compiler::{compile_json_request, run_cli as run_rust_cli, run_compiler_thread};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[pyfunction]
fn compile<'py>(py: Python<'py>, request: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let request = request.to_vec();
    let response = py
        .allow_threads(move || run_compiler_thread(move || compile_json_request(&request)))
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?
        .map_err(PyRuntimeError::new_err)?;
    Ok(PyBytes::new(py, &response))
}

#[pyfunction]
fn run_cli(py: Python<'_>) -> PyResult<i32> {
    let arguments = py
        .import("sys")?
        .getattr("argv")?
        .extract::<Vec<String>>()?
        .into_iter()
        .skip(1)
        .collect::<Vec<_>>();
    match py.allow_threads(move || run_compiler_thread(move || run_rust_cli(arguments))) {
        Ok(Ok(())) => Ok(0),
        Ok(Err(message)) => {
            eprintln!("catseqc: {message}");
            Ok(1)
        }
        Err(error) => {
            eprintln!("catseqc: {error}");
            Ok(1)
        }
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(compile, module)?)?;
    module.add_function(wrap_pyfunction!(run_cli, module)?)?;
    Ok(())
}
