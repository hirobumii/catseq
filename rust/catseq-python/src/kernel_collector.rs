use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyTypeError};
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

impl CollectedDefinition {
    fn clone_ref(&self, py: Python<'_>) -> Self {
        Self {
            name: self.name.clone(),
            role: self.role,
            symbol: self.symbol.clone(),
            original: self.original.clone_ref(py),
            wrapper: self.wrapper.clone_ref(py),
            module: self.module.clone_ref(py),
        }
    }
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
    // Follow exact global/module/owner access paths from the entry without
    // reading the process-global registration catalog. This only determines
    // which source modules must be available; semantic reachability remains a
    // result of registered source analysis and unreachable candidates never
    // enter HIR.
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
    let definition_facts = core.getattr("_registered_definition_facts")?;
    let root_facts = definition_facts.call1((root,))?;
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

    let definitions = match scope {
        CollectionScope::Catalog => {
            let catalog = core.getattr("_registered_definition_catalog")?.call0()?;
            let catalog = catalog.downcast_exact::<PyTuple>()?;
            catalog
                .iter()
                .map(|facts| {
                    let facts = parse_facts(&facts)?;
                    facts.collect()
                })
                .collect::<PyResult<Vec<_>>>()?
        }
        CollectionScope::EntryBindings => {
            select_entry_bindings(py, experiment, &definition_facts, entry.clone_ref(py))?
        }
    };

    Ok(PyKernelDefinitionCollection {
        owner: experiment.clone().unbind(),
        entry,
        definitions,
    })
}

fn select_entry_bindings(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
    definition_facts: &Bound<'_, PyAny>,
    entry: CollectedDefinition,
) -> PyResult<Vec<CollectedDefinition>> {
    let mut selected = vec![entry];
    let mut pending = vec![0];

    while let Some(definition_id) = pending.pop() {
        let original_object = selected[definition_id].original.clone_ref(py);
        let wrapper = selected[definition_id].wrapper.clone_ref(py);
        let original = original_object.bind(py).downcast_exact::<PyFunction>()?;
        let accesses = definition_access_paths(py, experiment, original, wrapper.bind(py))?;
        let globals_object = original.getattr("__globals__")?;
        let globals = globals_object.downcast_exact::<PyDict>()?;
        for access in &accesses.globals {
            let Some((root, attributes)) = access.split_first() else {
                unreachable!("definition access paths are non-empty")
            };
            let Some(value) = globals.get_item(root)? else {
                continue;
            };
            select_exact_binding_path(
                definition_facts,
                value,
                attributes,
                &mut selected,
                &mut pending,
            )?;
        }

        if let Some(receiver) = accesses.receiver {
            let mro_object = experiment.get_type().getattr("__mro__")?;
            let mro = mro_object.downcast_exact::<PyTuple>()?;
            for access in receiver {
                let Some((attribute, rest)) = access.split_first() else {
                    unreachable!("receiver access paths contain an attribute")
                };
                for class in mro.iter() {
                    let namespace = class.getattr("__dict__")?;
                    match namespace.get_item(attribute) {
                        Ok(value) => {
                            select_exact_binding_path(
                                definition_facts,
                                value,
                                rest,
                                &mut selected,
                                &mut pending,
                            )?;
                            break;
                        }
                        Err(error) if error.is_instance_of::<PyKeyError>(py) => {}
                        Err(error) => return Err(error),
                    }
                }
            }
        }
    }

    Ok(selected)
}

fn select_exact_binding_path(
    definition_facts: &Bound<'_, PyAny>,
    mut value: Bound<'_, PyAny>,
    attributes: &[String],
    selected: &mut Vec<CollectedDefinition>,
    pending: &mut Vec<usize>,
) -> PyResult<()> {
    for attribute in attributes {
        let Ok(module) = value.downcast_exact::<PyModule>() else {
            return Ok(());
        };
        let Some(next) = module.dict().get_item(attribute)? else {
            return Ok(());
        };
        value = next;
    }
    let facts = definition_facts.call1((&value,))?;
    if facts.is_none() {
        return Ok(());
    }
    let definition = parse_facts(&facts)?.collect()?;
    if exact_definition_id(&value, selected).is_none() {
        let definition_id = selected.len();
        selected.push(definition);
        pending.push(definition_id);
    }
    Ok(())
}

struct DefinitionAccessPaths {
    globals: Vec<Vec<String>>,
    receiver: Option<Vec<Vec<String>>>,
}

fn definition_access_paths(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
    function: &Bound<'_, PyFunction>,
    wrapper: &Bound<'_, PyAny>,
) -> PyResult<DefinitionAccessPaths> {
    let receiver_name = exact_owner_receiver_name(experiment, function, wrapper)?;
    let instructions = py
        .import("dis")?
        .getattr("get_instructions")?
        .call1((function,))?;
    let mut globals = Vec::new();
    let mut receiver = Vec::new();
    let mut pending: Option<(bool, Vec<String>)> = None;
    for instruction in instructions.try_iter()? {
        let instruction = instruction?;
        let opname = instruction.getattr("opname")?.extract::<String>()?;
        if matches!(opname.as_str(), "LOAD_GLOBAL" | "LOAD_NAME") {
            finish_access_path(&mut pending, &mut globals, &mut receiver);
            pending = Some((
                false,
                vec![instruction.getattr("argval")?.extract::<String>()?],
            ));
        } else if opname == "LOAD_FAST"
            && instruction.getattr("argval")?.extract::<String>()?.as_str()
                == receiver_name.as_deref().unwrap_or("")
        {
            finish_access_path(&mut pending, &mut globals, &mut receiver);
            pending = Some((true, Vec::new()));
        } else if matches!(opname.as_str(), "LOAD_ATTR" | "LOAD_METHOD") {
            if let Some((_, path)) = &mut pending {
                path.push(instruction.getattr("argval")?.extract::<String>()?);
            }
        } else {
            finish_access_path(&mut pending, &mut globals, &mut receiver);
        }
    }
    finish_access_path(&mut pending, &mut globals, &mut receiver);
    Ok(DefinitionAccessPaths {
        globals,
        receiver: receiver_name.map(|_| receiver),
    })
}

fn exact_owner_receiver_name(
    experiment: &Bound<'_, PyAny>,
    original: &Bound<'_, PyFunction>,
    wrapper: &Bound<'_, PyAny>,
) -> PyResult<Option<String>> {
    let mro_object = experiment.get_type().getattr("__mro__")?;
    let mro = mro_object.downcast_exact::<PyTuple>()?;
    let mut is_owner_method = false;
    for class in mro.iter() {
        let namespace = class.getattr("__dict__")?;
        for item in namespace.call_method0("items")?.try_iter()? {
            let item = item?;
            let item = item.downcast_exact::<PyTuple>()?;
            let value = item.get_item(1)?;
            if value.is(original) || value.is(wrapper) {
                is_owner_method = true;
                break;
            }
        }
        if is_owner_method {
            break;
        }
    }
    if !is_owner_method {
        return Ok(None);
    }
    let code = original.getattr("__code__")?;
    if code.getattr("co_argcount")?.extract::<usize>()? == 0 {
        return Ok(None);
    }
    let variables_object = code.getattr("co_varnames")?;
    let variables = variables_object.downcast_exact::<PyTuple>()?;
    Ok(Some(variables.get_item(0)?.extract()?))
}

fn finish_access_path(
    pending: &mut Option<(bool, Vec<String>)>,
    globals: &mut Vec<Vec<String>>,
    receiver: &mut Vec<Vec<String>>,
) {
    let Some((is_receiver, path)) = pending.take() else {
        return;
    };
    if path.is_empty() {
        return;
    }
    if is_receiver {
        receiver.push(path);
    } else {
        globals.push(path);
    }
}

pub(crate) fn exact_definition_id(
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
