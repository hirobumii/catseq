use std::collections::BTreeMap;
use std::str::FromStr;

use catseq_runtime::{
    AssembledOasmBoard, AssembledOasmProgram, BoardEndpoint, BoardExecutionState,
    LinuxRawEthernetRuntimeConfig, OasmAddress, RuntimeContractError, RuntimeFailure,
    RuntimeSuccess, execute_oasm_program as execute_runtime,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyclass(name = "AssembledOASMBoard", module = "catseq._native", frozen)]
#[derive(Clone)]
pub(crate) struct PyAssembledOasmBoard {
    inner: AssembledOasmBoard,
}

#[pymethods]
impl PyAssembledOasmBoard {
    #[new]
    fn new(address: &str, ich_words: Vec<u32>, exception_handler_word: u32) -> PyResult<Self> {
        let address = parse_address(address)?;
        let inner = AssembledOasmBoard::new(address, ich_words, exception_handler_word)
            .map_err(contract_error)?;
        Ok(Self { inner })
    }

    #[getter]
    fn address(&self) -> &'static str {
        self.inner.address().as_str()
    }

    #[getter]
    fn ich_words(&self) -> Vec<u32> {
        self.inner.ich_words().to_vec()
    }

    #[getter]
    fn exception_handler_word(&self) -> u32 {
        self.inner.exception_handler_word()
    }
}

#[pyclass(name = "AssembledOASMProgram", module = "catseq._native", frozen)]
pub(crate) struct PyAssembledOasmProgram {
    inner: AssembledOasmProgram,
}

#[pymethods]
impl PyAssembledOasmProgram {
    #[new]
    fn new(
        py: Python<'_>,
        schema_version: u32,
        reply_node: u16,
        reply_channel: u8,
        boards: Vec<Py<PyAssembledOasmBoard>>,
    ) -> PyResult<Self> {
        let boards = boards
            .into_iter()
            .map(|board| board.borrow(py).inner.clone())
            .collect();
        let inner = AssembledOasmProgram::new(schema_version, reply_node, reply_channel, boards)
            .map_err(contract_error)?;
        Ok(Self { inner })
    }

    #[getter]
    fn schema_version(&self) -> u32 {
        self.inner.schema_version()
    }

    #[getter]
    fn reply_node(&self) -> u16 {
        self.inner.reply_node()
    }

    #[getter]
    fn reply_channel(&self) -> u8 {
        self.inner.reply_channel()
    }

    #[getter]
    fn boards(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAssembledOasmBoard>>> {
        self.inner
            .boards()
            .iter()
            .cloned()
            .map(|inner| Py::new(py, PyAssembledOasmBoard { inner }))
            .collect()
    }
}

#[pyclass(name = "BoardEndpoint", module = "catseq._native", frozen)]
#[derive(Clone)]
pub(crate) struct PyBoardEndpoint {
    inner: BoardEndpoint,
}

#[pymethods]
impl PyBoardEndpoint {
    #[new]
    fn new(
        address: &str,
        node: u16,
        channel: u8,
        instruction_capacity_words: usize,
    ) -> PyResult<Self> {
        let address = parse_address(address)?;
        let inner = BoardEndpoint::new(address, node, channel, instruction_capacity_words)
            .map_err(contract_error)?;
        Ok(Self { inner })
    }

    #[getter]
    fn address(&self) -> &'static str {
        self.inner.address().as_str()
    }

    #[getter]
    fn node(&self) -> u16 {
        self.inner.node()
    }

    #[getter]
    fn channel(&self) -> u8 {
        self.inner.channel()
    }

    #[getter]
    fn instruction_capacity_words(&self) -> usize {
        self.inner.instruction_capacity_words()
    }
}

#[pyclass(
    name = "LinuxRawEthernetRuntimeConfig",
    module = "catseq._native",
    frozen
)]
pub(crate) struct PyLinuxRawEthernetRuntimeConfig {
    inner: LinuxRawEthernetRuntimeConfig,
}

#[pymethods]
impl PyLinuxRawEthernetRuntimeConfig {
    #[new]
    fn new(
        py: Python<'_>,
        schema_version: u32,
        interface: String,
        destination_mac: Option<Vec<u8>>,
        timeout_ms: u64,
        boards: Vec<Py<PyBoardEndpoint>>,
    ) -> PyResult<Self> {
        let destination_mac = destination_mac
            .map(|bytes| {
                bytes.try_into().map_err(|bytes: Vec<u8>| {
                    PyValueError::new_err(format!(
                        "destination MAC has {} bytes, expected 6",
                        bytes.len()
                    ))
                })
            })
            .transpose()?;
        let boards = boards
            .into_iter()
            .map(|board| board.borrow(py).inner)
            .collect();
        let inner = LinuxRawEthernetRuntimeConfig::new(
            schema_version,
            interface,
            destination_mac,
            timeout_ms,
            boards,
        )
        .map_err(contract_error)?;
        Ok(Self { inner })
    }

    #[getter]
    fn schema_version(&self) -> u32 {
        self.inner.schema_version()
    }

    #[getter]
    fn interface(&self) -> &str {
        self.inner.interface()
    }

    #[getter]
    fn destination_mac(&self) -> Option<Vec<u8>> {
        self.inner.destination_mac().map(Vec::from)
    }

    #[getter]
    fn timeout_ms(&self) -> u64 {
        self.inner.timeout_ms()
    }

    #[getter]
    fn boards(&self, py: Python<'_>) -> PyResult<Vec<Py<PyBoardEndpoint>>> {
        self.inner
            .boards()
            .iter()
            .copied()
            .map(|inner| Py::new(py, PyBoardEndpoint { inner }))
            .collect()
    }
}

#[pyclass(name = "OASMRuntimeSuccess", module = "catseq._native", frozen)]
pub(crate) struct PyOasmRuntimeSuccess {
    inner: RuntimeSuccess,
}

#[pymethods]
impl PyOasmRuntimeSuccess {
    #[getter]
    fn schema_version(&self) -> u32 {
        self.inner.schema_version()
    }

    #[getter]
    fn board_evidence(&self) -> BTreeMap<String, String> {
        python_evidence(self.inner.board_evidence())
    }

    #[getter]
    fn results(&self) -> BTreeMap<String, Vec<u32>> {
        self.inner
            .results()
            .iter()
            .map(|(address, words)| (address.as_str().to_owned(), words.clone()))
            .collect()
    }
}

#[pyclass(name = "OASMRuntimeFailure", module = "catseq._native", frozen)]
pub(crate) struct PyOasmRuntimeFailure {
    inner: RuntimeFailure,
}

#[pymethods]
impl PyOasmRuntimeFailure {
    #[getter]
    fn schema_version(&self) -> u32 {
        self.inner.schema_version()
    }

    #[getter]
    fn code(&self) -> &'static str {
        self.inner.code().as_str()
    }

    #[getter]
    fn message(&self) -> &str {
        self.inner.message()
    }

    #[getter]
    fn execution_certainty(&self) -> &'static str {
        self.inner.execution_certainty().as_str()
    }

    #[getter]
    fn board_evidence(&self) -> BTreeMap<String, String> {
        python_evidence(self.inner.board_evidence())
    }

    #[getter]
    fn device_exceptions(&self) -> BTreeMap<String, (u32, Option<u32>)> {
        self.inner
            .device_exceptions()
            .iter()
            .map(|(address, report)| {
                (
                    address.as_str().to_owned(),
                    (report.exception_flags(), report.instruction_address()),
                )
            })
            .collect()
    }

    #[getter]
    fn details(&self) -> BTreeMap<String, String> {
        self.inner.details().clone()
    }
}

#[pyfunction]
fn execute_oasm_program(
    py: Python<'_>,
    program: PyRef<'_, PyAssembledOasmProgram>,
    config: PyRef<'_, PyLinuxRawEthernetRuntimeConfig>,
) -> PyResult<Py<PyAny>> {
    let program = program.inner.clone();
    let config = config.inner.clone();
    let outcome = py.allow_threads(move || execute_runtime(&program, &config));
    match outcome {
        Ok(inner) => Ok(Py::new(py, PyOasmRuntimeSuccess { inner })?.into_any()),
        Err(inner) => Ok(Py::new(py, PyOasmRuntimeFailure { inner })?.into_any()),
    }
}

fn parse_address(value: &str) -> PyResult<OasmAddress> {
    OasmAddress::from_str(value).map_err(contract_error)
}

fn contract_error(error: RuntimeContractError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

fn python_evidence(
    evidence: &BTreeMap<OasmAddress, BoardExecutionState>,
) -> BTreeMap<String, String> {
    evidence
        .iter()
        .map(|(address, state)| (address.as_str().to_owned(), state.as_str().to_owned()))
        .collect()
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyAssembledOasmBoard>()?;
    module.add_class::<PyAssembledOasmProgram>()?;
    module.add_class::<PyBoardEndpoint>()?;
    module.add_class::<PyLinuxRawEthernetRuntimeConfig>()?;
    module.add_class::<PyOasmRuntimeSuccess>()?;
    module.add_class::<PyOasmRuntimeFailure>()?;
    module.add_function(wrap_pyfunction!(execute_oasm_program, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use catseq_runtime::BoardExecutionState;

    use super::*;

    #[test]
    fn native_evidence_decodes_without_a_socket() {
        let evidence = BTreeMap::from([(OasmAddress::Rwg0, BoardExecutionState::Succeeded)]);

        assert_eq!(
            python_evidence(&evidence),
            BTreeMap::from([("rwg0".to_owned(), "succeeded".to_owned())])
        );
    }

    #[test]
    fn indeterminate_native_evidence_keeps_its_state_name() {
        let evidence = BTreeMap::from([(OasmAddress::Rwg0, BoardExecutionState::LaunchSubmitted)]);

        assert_eq!(
            python_evidence(&evidence),
            BTreeMap::from([("rwg0".to_owned(), "launch_submitted".to_owned())])
        );
    }
}
