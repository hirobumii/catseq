use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyFunction, PyModule, PyTuple};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CollectedDefinitionRole {
    Kernel,
    Compute,
    MorphismDefinition,
    Atomic,
    Intrinsic,
}

impl CollectedDefinitionRole {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Kernel => "kernel",
            Self::Compute => "compute",
            Self::MorphismDefinition => "morphism_definition",
            Self::Atomic => "atomic",
            Self::Intrinsic => "intrinsic",
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
    collect_kernel_definitions_with_scope(py, experiment, CollectionScope::Catalog)
}

pub(crate) fn collect_entry_kernel_definitions(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
) -> PyResult<PyKernelDefinitionCollection> {
    collect_kernel_definitions_with_scope(py, experiment, CollectionScope::EntryBindings)
}

#[derive(Clone, Copy)]
enum CollectionScope {
    Catalog,
    EntryBindings,
}

fn collect_kernel_definitions_with_scope(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
    scope: CollectionScope,
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
    let mut definitions = catalog
        .iter()
        .map(|facts| {
            let facts = parse_facts(&facts)?;
            facts.collect()
        })
        .collect::<PyResult<Vec<_>>>()?;
    if matches!(scope, CollectionScope::EntryBindings) {
        definitions = select_entry_bindings(py, experiment, &entry, definitions)?;
    }

    Ok(PyKernelDefinitionCollection {
        owner: experiment.clone().unbind(),
        entry,
        definitions,
    })
}

fn select_entry_bindings(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
    entry: &CollectedDefinition,
    catalog: Vec<CollectedDefinition>,
) -> PyResult<Vec<CollectedDefinition>> {
    let entry_id = exact_definition_id(entry.original.bind(py), &catalog).ok_or_else(|| {
        PyRuntimeError::new_err(
            "registered BaseExp.build_sequence is absent from the definition catalog",
        )
    })?;
    let mut selected = vec![false; catalog.len()];
    let mut pending = vec![entry_id];
    selected[entry_id] = true;

    while let Some(definition_id) = pending.pop() {
        let original = catalog[definition_id]
            .original
            .bind(py)
            .downcast_exact::<PyFunction>()?;
        let code = original.getattr("__code__")?;
        let names_object = code.getattr("co_names")?;
        let names = names_object.downcast_exact::<PyTuple>()?;
        let names = names
            .iter()
            .map(|name| name.extract::<String>())
            .collect::<PyResult<Vec<_>>>()?;
        let globals_object = original.getattr("__globals__")?;
        let globals = globals_object.downcast_exact::<PyDict>()?;
        for name in &names {
            let Some(value) = globals.get_item(name)? else {
                continue;
            };
            select_exact_binding(&value, &names, &catalog, &mut selected, &mut pending)?;
        }

        let mro_object = experiment.get_type().getattr("__mro__")?;
        let mro = mro_object.downcast_exact::<PyTuple>()?;
        for class in mro.iter() {
            let namespace = class.getattr("__dict__")?;
            for name in &names {
                if let Ok(value) = namespace.get_item(name) {
                    select_definition(&value, &catalog, &mut selected, &mut pending);
                }
            }
        }
    }

    Ok(catalog
        .into_iter()
        .enumerate()
        .filter_map(|(definition_id, definition)| selected[definition_id].then_some(definition))
        .collect())
}

fn select_exact_binding(
    value: &Bound<'_, PyAny>,
    names: &[String],
    catalog: &[CollectedDefinition],
    selected: &mut [bool],
    pending: &mut Vec<usize>,
) -> PyResult<()> {
    if select_definition(value, catalog, selected, pending) {
        return Ok(());
    }
    let Ok(module) = value.downcast_exact::<PyModule>() else {
        return Ok(());
    };
    let mut modules = vec![module.clone()];
    let mut visited = Vec::<Py<PyModule>>::new();
    while let Some(module) = modules.pop() {
        if visited.iter().any(|known| known.is(&module)) {
            continue;
        }
        visited.push(module.clone().unbind());
        for name in names {
            let Some(attribute) = module.dict().get_item(name)? else {
                continue;
            };
            if select_definition(&attribute, catalog, selected, pending) {
                continue;
            }
            if let Ok(nested) = attribute.downcast_exact::<PyModule>() {
                modules.push(nested.clone());
            }
        }
    }
    Ok(())
}

fn select_definition(
    value: &Bound<'_, PyAny>,
    catalog: &[CollectedDefinition],
    selected: &mut [bool],
    pending: &mut Vec<usize>,
) -> bool {
    let Some(definition_id) = exact_definition_id(value, catalog) else {
        return false;
    };
    if !selected[definition_id] {
        selected[definition_id] = true;
        pending.push(definition_id);
    }
    true
}

fn exact_definition_id(
    value: &Bound<'_, PyAny>,
    definitions: &[CollectedDefinition],
) -> Option<usize> {
    definitions
        .iter()
        .position(|definition| value.is(&definition.original) || value.is(&definition.wrapper))
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
        "compute" => Ok(CollectedDefinitionRole::Compute),
        "morphism" => Ok(CollectedDefinitionRole::MorphismDefinition),
        "atomic_morphism" => Ok(CollectedDefinitionRole::Atomic),
        "compiler_intrinsic" => Ok(CollectedDefinitionRole::Intrinsic),
        _ => Err(PyRuntimeError::new_err("unknown CatSeq definition role")),
    }
}
