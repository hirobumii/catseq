use std::collections::BTreeMap;
use std::path::PathBuf;

use catseq_compiler::{
    CompiledSequence as NativeCompiledSequence, CompilerSession, compile_json_request,
    run_cli as run_rust_cli, run_compiler_thread,
};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

mod kernel_collector;
mod kernel_registration;
mod runtime;

#[pyclass(name = "CompiledSequence", module = "catseq._native", frozen)]
struct PyCompiledSequence {
    inner: NativeCompiledSequence,
    opaque_callables: BTreeMap<String, Py<PyAny>>,
}

#[pymethods]
impl PyCompiledSequence {
    #[getter]
    fn entry(&self) -> &str {
        self.inner.entry()
    }

    #[getter]
    fn logical_duration_cycles(&self) -> u64 {
        self.inner.logical_duration_cycles()
    }

    #[getter]
    fn clock_hz(&self) -> u64 {
        self.inner.clock_hz()
    }

    #[getter]
    fn total_duration_us(&self) -> PyResult<f64> {
        if self.inner.clock_hz() == 0 {
            return Err(PyValueError::new_err(
                "CompiledSequence clock_hz must be greater than zero",
            ));
        }
        Ok(
            self.inner.logical_duration_cycles() as f64 * 1_000_000.0
                / self.inner.clock_hz() as f64,
        )
    }

    #[getter]
    fn native_compile_seconds(&self) -> f64 {
        self.inner.native_compile_seconds()
    }

    #[getter]
    fn oasm_call_plan(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        json_to_python(py, self.inner.oasm_call_plan())
    }

    #[getter]
    fn diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        json_to_python(py, self.inner.diagnostics())
    }

    #[getter]
    fn incremental(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        json_to_python(py, self.inner.incremental())
    }

    #[getter]
    fn _opaque_callables(&self, py: Python<'_>) -> BTreeMap<String, Py<PyAny>> {
        self.opaque_callables
            .iter()
            .map(|(key, callable)| (key.clone(), callable.clone_ref(py)))
            .collect()
    }
}

#[pyclass(name = "Compiler", module = "catseq._native", frozen)]
struct PyCompiler {
    inner: CompilerSession,
    opaque_callables: BTreeMap<String, Py<PyAny>>,
}

#[pymethods]
impl PyCompiler {
    #[new]
    #[pyo3(signature = (
        source_root,
        compile_environment,
        target_profile,
        environment_values,
        opaque_callables,
        cache_dir=None,
    ))]
    fn new(
        source_root: PathBuf,
        compile_environment: &[u8],
        target_profile: &[u8],
        environment_values: &[u8],
        opaque_callables: BTreeMap<String, Py<PyAny>>,
        cache_dir: Option<PathBuf>,
    ) -> PyResult<Self> {
        let inner = CompilerSession::from_json(
            source_root,
            compile_environment,
            target_profile,
            environment_values,
            cache_dir,
        )
        .map_err(PyRuntimeError::new_err)?;
        Ok(Self {
            inner,
            opaque_callables,
        })
    }

    #[getter]
    fn source_root(&self) -> String {
        self.inner.source_root().display().to_string()
    }

    fn compile(
        &self,
        py: Python<'_>,
        source_path: PathBuf,
        entry: String,
        mut entry_opaque_callables: BTreeMap<String, Py<PyAny>>,
        entry_arguments: &[u8],
        link_bindings: &[u8],
    ) -> PyResult<PyCompiledSequence> {
        let compiler = self.inner.clone();
        let entry_arguments = entry_arguments.to_vec();
        let link_bindings = link_bindings.to_vec();
        let mut opaque_callables: BTreeMap<String, Py<PyAny>> = self
            .opaque_callables
            .iter()
            .map(|(key, callable)| (key.clone(), callable.clone_ref(py)))
            .collect();
        let inner = py
            .allow_threads(move || {
                run_compiler_thread(move || {
                    compiler.compile_entry(source_path, entry, &entry_arguments, &link_bindings)
                })
            })
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?
            .map_err(PyRuntimeError::new_err)?;
        for key in inner.opaque_callable_keys() {
            if opaque_callables.contains_key(&key) {
                continue;
            }
            let callable = entry_opaque_callables.remove(&key).ok_or_else(|| {
                PyRuntimeError::new_err(format!(
                    "blackbox callback {key:?} is unavailable on the host; callbacks must be module-level functions"
                ))
            })?;
            opaque_callables.insert(key, callable);
        }
        Ok(PyCompiledSequence {
            inner,
            opaque_callables,
        })
    }

    fn _collect_kernel_definitions(
        &self,
        py: Python<'_>,
        experiment: &Bound<'_, PyAny>,
    ) -> PyResult<kernel_collector::PyKernelDefinitionCollection> {
        kernel_collector::collect_kernel_definitions(py, experiment)
    }

    fn _register_kernel_modules(
        &self,
        py: Python<'_>,
        experiment: &Bound<'_, PyAny>,
    ) -> PyResult<kernel_registration::PyRegisteredKernelModules> {
        let collection = kernel_collector::collect_kernel_definitions(py, experiment)?;
        kernel_registration::register_collected_kernel_modules(py, collection)
    }
}

fn json_to_python<T: serde::Serialize + ?Sized>(py: Python<'_>, value: &T) -> PyResult<Py<PyAny>> {
    let encoded =
        serde_json::to_string(value).map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    Ok(py
        .import("json")?
        .call_method1("loads", (encoded,))?
        .unbind())
}

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
    module.add_class::<PyCompiler>()?;
    module.add_class::<PyCompiledSequence>()?;
    module.add_class::<kernel_collector::PyKernelDefinitionCollection>()?;
    module.add_class::<kernel_registration::PyRegisteredKernelModules>()?;
    module.add_class::<kernel_registration::PyComputeValidation>()?;
    runtime::register(module)?;
    Ok(())
}
