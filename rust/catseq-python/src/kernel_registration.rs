use std::fs;
use std::sync::Arc;

use catseq_frontend::{
    DefinitionRegistrationInput, ModuleRegistrationInput, RegisteredDefinitionRole,
    RegisteredKernelModules, RegistrationInput, register_kernel_modules,
};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use crate::kernel_collector::{
    CollectedDefinition, CollectedDefinitionRole, PyKernelDefinitionCollection,
};

#[pyclass(name = "_RegisteredKernelModules", module = "catseq._native", frozen)]
pub(crate) struct PyRegisteredKernelModules {
    pub(crate) frontend: RegisteredKernelModules,
    owner: Py<PyAny>,
    entry: CollectedDefinition,
    pub(crate) definitions: Vec<CollectedDefinition>,
}

#[pymethods]
impl PyRegisteredKernelModules {
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

    #[getter]
    fn _module_names(&self) -> Vec<String> {
        self.frontend
            .modules()
            .iter()
            .map(|module| module.import_name().to_owned())
            .collect()
    }

    #[getter]
    fn _module_files(&self) -> Vec<String> {
        self.frontend
            .modules()
            .iter()
            .map(|module| module.file_name().to_owned())
            .collect()
    }

    #[getter]
    fn _definition_locations(&self) -> Vec<(String, String, usize, usize)> {
        self.frontend
            .definitions()
            .iter()
            .map(|definition| {
                let location = definition.location();
                (
                    self.definitions[definition.id()].name.clone(),
                    location.file.0.to_string(),
                    location.row,
                    location.column,
                )
            })
            .collect()
    }
}

pub(crate) fn register_collected_kernel_modules(
    py: Python<'_>,
    collection: PyKernelDefinitionCollection,
) -> PyResult<PyRegisteredKernelModules> {
    let PyKernelDefinitionCollection {
        owner,
        entry,
        definitions,
    } = collection;

    let definitions = definitions.into_iter().fold(
        Vec::<CollectedDefinition>::new(),
        |mut unique, definition| {
            if !unique
                .iter()
                .any(|existing| existing.original.is(&definition.original))
            {
                unique.push(definition);
            }
            unique
        },
    );
    let entry_definition_id = definitions
        .iter()
        .position(|definition| definition.original.is(&entry.original))
        .ok_or_else(|| {
            PyRuntimeError::new_err(
                "registered BaseExp.build_sequence is absent from the #51 definition catalog",
            )
        })?;

    let mut modules = Vec::<Py<PyModule>>::new();
    for definition in &definitions {
        if !modules.iter().any(|module| module.is(&definition.module)) {
            modules.push(definition.module.clone_ref(py));
        }
    }
    let module_inputs = modules
        .iter()
        .enumerate()
        .map(|(id, module)| load_module_source(py, id, module))
        .collect::<PyResult<Vec<_>>>()?;
    let definition_inputs = definitions
        .iter()
        .enumerate()
        .map(|(id, definition)| {
            let original = definition.original.bind(py);
            let qualified_name = original.getattr("__qualname__")?.extract()?;
            let source_start_line = original
                .getattr("__code__")?
                .getattr("co_firstlineno")?
                .extract()?;
            let module_id = modules
                .iter()
                .position(|module| module.is(&definition.module))
                .expect("every collected definition module was retained above");
            Ok(DefinitionRegistrationInput {
                id,
                module_id,
                qualified_name,
                source_start_line,
                role: frontend_role(definition.role),
                atomic_symbol: definition.symbol.clone(),
            })
        })
        .collect::<PyResult<Vec<_>>>()?;
    let frontend = register_kernel_modules(RegistrationInput {
        modules: module_inputs,
        definitions: definition_inputs,
        entry_definition_id,
    })
    .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

    Ok(PyRegisteredKernelModules {
        frontend,
        owner,
        entry,
        definitions,
    })
}

fn load_module_source(
    py: Python<'_>,
    id: usize,
    module: &Py<PyModule>,
) -> PyResult<ModuleRegistrationInput> {
    let module = module.bind(py);
    let import_name = module.name()?.to_str()?.to_owned();
    let (file_name, source) = match module.getattr_opt("__file__")? {
        Some(file) if !file.is_none() => {
            let file_name = file.extract::<String>().map_err(|error| {
                PyRuntimeError::new_err(format!(
                    "cannot load registered module {import_name}: __file__ is not a string: {error}"
                ))
            })?;
            let source = fs::read_to_string(&file_name).map_err(|error| {
                PyRuntimeError::new_err(format!(
                    "cannot load registered module {import_name} from {file_name}: {error}"
                ))
            })?;
            (file_name, source)
        }
        _ => {
            let loader = module
                .getattr_opt("__loader__")?
                .ok_or_else(|| missing_source_error(&import_name))?;
            let source = loader
                .call_method1("get_source", (&import_name,))
                .map_err(|error| {
                    PyRuntimeError::new_err(format!(
                        "cannot load registered module {import_name} through __loader__.get_source: {error}"
                    ))
                })?;
            if source.is_none() {
                return Err(missing_source_error(&import_name));
            }
            let source = source.extract::<String>().map_err(|error| {
                PyRuntimeError::new_err(format!(
                    "cannot load registered module {import_name}: __loader__.get_source did not return a string: {error}"
                ))
            })?;
            (format!("<{import_name}>"), source)
        }
    };
    Ok(ModuleRegistrationInput {
        id,
        import_name,
        file_name,
        source: Arc::from(source),
    })
}

fn missing_source_error(module: &str) -> PyErr {
    PyRuntimeError::new_err(format!(
        "cannot load registered module {module}: neither __file__ nor __loader__.get_source provides source"
    ))
}

const fn frontend_role(role: CollectedDefinitionRole) -> RegisteredDefinitionRole {
    match role {
        CollectedDefinitionRole::Kernel => RegisteredDefinitionRole::Kernel,
        CollectedDefinitionRole::MorphismDefinition => RegisteredDefinitionRole::MorphismDefinition,
        CollectedDefinitionRole::Atomic => RegisteredDefinitionRole::Atomic,
    }
}
