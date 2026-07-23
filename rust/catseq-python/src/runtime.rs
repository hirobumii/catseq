use std::str::FromStr;

use catseq_runtime::{
    AssembledOasmBoard, AssembledOasmProgram, BoardEndpoint, LinuxRawEthernetRuntimeConfig,
    OasmAddress, RuntimeContractError, validate_runtime_handoff as validate_handoff,
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

#[pyfunction]
fn validate_runtime_handoff(
    program: &PyAssembledOasmProgram,
    config: &PyLinuxRawEthernetRuntimeConfig,
) -> PyResult<()> {
    validate_handoff(&program.inner, &config.inner).map_err(contract_error)
}

fn parse_address(value: &str) -> PyResult<OasmAddress> {
    OasmAddress::from_str(value).map_err(contract_error)
}

fn contract_error(error: RuntimeContractError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyAssembledOasmBoard>()?;
    module.add_class::<PyAssembledOasmProgram>()?;
    module.add_class::<PyBoardEndpoint>()?;
    module.add_class::<PyLinuxRawEthernetRuntimeConfig>()?;
    module.add_function(wrap_pyfunction!(validate_runtime_handoff, module)?)?;
    Ok(())
}
