use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyFunction, PyModule, PyTuple};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CollectedDefinitionRole {
    Kernel,
    MorphismDefinition,
    Atomic,
}

impl CollectedDefinitionRole {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Kernel => "kernel",
            Self::MorphismDefinition => "morphism_definition",
            Self::Atomic => "atomic",
        }
    }
}

pub(crate) struct CollectedDefinition {
    pub(crate) name: String,
    pub(crate) role: CollectedDefinitionRole,
    pub(crate) symbol: Option<String>,
    pub(crate) original: Py<PyAny>,
    pub(crate) wrapper: Py<PyAny>,
    pub(crate) module: Py<PyModule>,
}

#[pyclass(
    name = "_KernelDefinitionCollection",
    module = "catseq._native",
    frozen
)]
pub(crate) struct PyKernelDefinitionCollection {
    pub(crate) owner: Py<PyAny>,
    pub(crate) entry: CollectedDefinition,
    pub(crate) definitions: Vec<CollectedDefinition>,
}

#[pymethods]
impl PyKernelDefinitionCollection {
    #[getter]
    fn _entry_owner(&self, py: Python<'_>) -> Py<PyAny> {
        self.owner.clone_ref(py)
    }

    #[getter]
    fn _entry_name(&self) -> &str {
        &self.entry.name
    }

    #[getter]
    fn _entry_original(&self, py: Python<'_>) -> Py<PyAny> {
        self.entry.original.clone_ref(py)
    }

    #[getter]
    fn _entry_wrapper(&self, py: Python<'_>) -> Py<PyAny> {
        self.entry.wrapper.clone_ref(py)
    }

    #[getter]
    fn _definition_names(&self) -> Vec<String> {
        self.definitions
            .iter()
            .map(|definition| definition.name.clone())
            .collect()
    }

    #[getter]
    fn _definition_roles(&self) -> Vec<String> {
        self.definitions
            .iter()
            .map(|definition| definition.role.as_str().to_owned())
            .collect()
    }

    #[getter]
    fn _atomic_symbols(&self) -> Vec<String> {
        self.definitions
            .iter()
            .filter_map(|definition| definition.symbol.clone())
            .collect()
    }
}

pub(crate) fn collect_kernel_definitions(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
) -> PyResult<PyKernelDefinitionCollection> {
    let base_exp = py
        .import("catseq.experiment.base_exp")?
        .getattr("BaseExp")?;
    if !experiment.is_instance(&base_exp)? {
        return Err(PyTypeError::new_err(
            "Kernel collection requires an actual BaseExp instance",
        ));
    }

    let root = experiment.get_type().getattr("build_sequence")?;
    let root = root.downcast_exact::<PyFunction>().map_err(|_| {
        PyTypeError::new_err("BaseExp.build_sequence must be an exact Python function")
    })?;

    let core = py.import("catseq.morphism.core")?;
    let root_facts = core
        .getattr("_registered_definition_facts")?
        .call1((root,))?;
    if root_facts.is_none() {
        return Err(PyTypeError::new_err(
            "BaseExp.build_sequence must be registered by the exact private @kernel decorator",
        ));
    }
    let root_facts = parse_facts(&root_facts)?;
    if root_facts.role != CollectedDefinitionRole::Kernel {
        return Err(PyTypeError::new_err(
            "BaseExp.build_sequence must have the Kernel role",
        ));
    }
    let entry = root_facts.collect()?;

    let catalog = core.getattr("_registered_definition_catalog")?.call0()?;
    let catalog = catalog.downcast_exact::<PyTuple>()?;
    let definitions = catalog
        .iter()
        .map(|facts| {
            let facts = parse_facts(&facts)?;
            facts.collect()
        })
        .collect::<PyResult<Vec<_>>>()?;

    Ok(PyKernelDefinitionCollection {
        owner: experiment.clone().unbind(),
        entry,
        definitions,
    })
}

struct RegistrationFacts<'py> {
    original: Bound<'py, PyFunction>,
    wrapper: Bound<'py, PyFunction>,
    role: CollectedDefinitionRole,
    symbol: Option<String>,
    module: Bound<'py, PyModule>,
}

impl RegistrationFacts<'_> {
    fn name(&self) -> PyResult<String> {
        let module = self.module.name()?;
        let qualified_name: String = self.original.getattr("__qualname__")?.extract()?;
        Ok(format!("{module}.{qualified_name}"))
    }

    fn collect(self) -> PyResult<CollectedDefinition> {
        Ok(CollectedDefinition {
            name: self.name()?,
            role: self.role,
            symbol: self.symbol,
            original: self.original.unbind().into(),
            wrapper: self.wrapper.unbind().into(),
            module: self.module.unbind(),
        })
    }
}

fn parse_facts<'py>(value: &Bound<'py, PyAny>) -> PyResult<RegistrationFacts<'py>> {
    let facts = value.downcast_exact::<PyTuple>()?;
    Ok(RegistrationFacts {
        original: facts.get_item(0)?.downcast_exact::<PyFunction>()?.clone(),
        wrapper: facts.get_item(1)?.downcast_exact::<PyFunction>()?.clone(),
        role: definition_role(facts.get_item(2)?.extract()?)?,
        symbol: facts.get_item(3)?.extract()?,
        module: facts.get_item(4)?.downcast_exact::<PyModule>()?.clone(),
    })
}

fn definition_role(role: &str) -> PyResult<CollectedDefinitionRole> {
    match role {
        "kernel" => Ok(CollectedDefinitionRole::Kernel),
        "morphism_template" => Ok(CollectedDefinitionRole::MorphismDefinition),
        "atomic_morphism" => Ok(CollectedDefinitionRole::Atomic),
        _ => Err(PyRuntimeError::new_err("unknown CatSeq definition role")),
    }
}
