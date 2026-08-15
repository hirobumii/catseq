use std::fs;
use std::sync::Arc;

use catseq_frontend::{
    BuiltinNameBindingInput, ComputeType, ComputeValidation, DefinitionNameBindingInput,
    DefinitionRegistrationInput, ModuleRegistrationInput, RegisteredBuiltin,
    RegisteredDefinitionRole, RegisteredKernelModules, RegistrationInput, register_kernel_modules,
    validate_compute_roots,
};
use pyo3::PyTypeInfo;
use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFunction, PyInt, PyModule, PyTuple, PyType};

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

#[pyclass(name = "_ComputeValidation", module = "catseq._native", frozen)]
pub(crate) struct PyComputeValidation {
    inner: ComputeValidation,
}

#[pymethods]
impl PyComputeValidation {
    #[getter]
    fn _source_profile_id(&self) -> &'static str {
        self.inner.source_profile_id()
    }

    #[getter]
    fn _interface_definition_ids(&self) -> Vec<usize> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| interface.definition_id())
            .collect()
    }

    #[getter]
    fn _interface_parameters(&self) -> Vec<Vec<&'static str>> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| {
                interface
                    .parameters()
                    .iter()
                    .copied()
                    .map(compute_type_name)
                    .collect()
            })
            .collect()
    }

    #[getter]
    fn _interface_results(&self) -> Vec<&'static str> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| compute_type_name(interface.result()))
            .collect()
    }

    #[getter]
    fn _abi_signatures(&self) -> Vec<&str> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| interface.abi_signature())
            .collect()
    }

    #[getter]
    fn _abi_hashes(&self) -> Vec<&str> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| interface.abi_hash())
            .collect()
    }

    #[getter]
    fn _provenance(&self) -> Vec<(&str, &str, usize, usize)> {
        self.inner
            .interfaces()
            .iter()
            .map(|interface| {
                let provenance = interface.provenance();
                (
                    provenance.module(),
                    provenance.file_name(),
                    provenance.line(),
                    provenance.column(),
                )
            })
            .collect()
    }

    #[getter]
    fn _unit_count(&self) -> usize {
        self.inner.unit_store().unit_count()
    }

    #[getter]
    fn _source_unit_count(&self) -> usize {
        self.inner.unit_store().source_unit_count()
    }
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
            .filter(|definition| definition.role == CollectedDefinitionRole::Atomic)
            .map(|definition| {
                definition
                    .symbol
                    .clone()
                    .expect("registered Atomic definitions always retain a symbol")
            })
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

    fn _validate_compute_roots(&self, roots: &Bound<'_, PyTuple>) -> PyResult<PyComputeValidation> {
        let root_definition_ids = roots
            .iter()
            .map(|root| self.compute_definition_id(&root))
            .collect::<PyResult<Vec<_>>>()?;
        let inner = validate_compute_roots(&self.frontend, &root_definition_ids)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        Ok(PyComputeValidation { inner })
    }
}

impl PyRegisteredKernelModules {
    fn compute_definition_id(&self, root: &Bound<'_, PyAny>) -> PyResult<usize> {
        root.downcast_exact::<PyFunction>().map_err(|_| {
            PyTypeError::new_err("Compute roots must be exact registered Python functions")
        })?;
        self.definitions
            .iter()
            .enumerate()
            .find(|(_, definition)| {
                definition.role == CollectedDefinitionRole::Compute
                    && (root.is(&definition.original) || root.is(&definition.wrapper))
            })
            .map(|(definition_id, _)| definition_id)
            .ok_or_else(|| {
                PyTypeError::new_err(
                    "Compute root is not an exact @compute identity from this request",
                )
            })
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
    let definition_name_bindings = definition_name_bindings(py, &modules, &definitions)?;
    let builtin_name_bindings = builtin_name_bindings(py, &definitions)?;
    let frontend = register_kernel_modules(RegistrationInput {
        modules: module_inputs,
        definitions: definition_inputs,
        definition_name_bindings,
        builtin_name_bindings,
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

fn definition_name_bindings(
    py: Python<'_>,
    modules: &[Py<PyModule>],
    definitions: &[CollectedDefinition],
) -> PyResult<Vec<DefinitionNameBindingInput>> {
    let mut bindings = Vec::new();
    for (module_id, module) in modules.iter().enumerate() {
        for (name, value) in module.bind(py).dict().iter() {
            let Ok(name) = name.extract::<String>() else {
                continue;
            };
            if let Some(definition_id) = exact_definition_id(&value, definitions) {
                bindings.push(DefinitionNameBindingInput {
                    module_id,
                    name,
                    definition_id,
                });
                continue;
            }
            let Ok(imported_module) = value.downcast_exact::<PyModule>() else {
                continue;
            };
            for (attribute, attribute_value) in imported_module.dict().iter() {
                let Ok(attribute) = attribute.extract::<String>() else {
                    continue;
                };
                let Some(definition_id) = exact_definition_id(&attribute_value, definitions) else {
                    continue;
                };
                bindings.push(DefinitionNameBindingInput {
                    module_id,
                    name: format!("{name}.{attribute}"),
                    definition_id,
                });
            }
        }
    }
    Ok(bindings)
}

fn exact_definition_id(
    value: &Bound<'_, PyAny>,
    definitions: &[CollectedDefinition],
) -> Option<usize> {
    definitions
        .iter()
        .position(|definition| value.is(&definition.original) || value.is(&definition.wrapper))
}

fn builtin_name_bindings(
    py: Python<'_>,
    definitions: &[CollectedDefinition],
) -> PyResult<Vec<BuiltinNameBindingInput>> {
    let mut bindings = Vec::new();
    for (definition_id, definition) in definitions.iter().enumerate() {
        if definition.role != CollectedDefinitionRole::Compute {
            continue;
        }
        let original = definition
            .original
            .bind(py)
            .downcast_exact::<PyFunction>()
            .expect("collected definitions retain exact Python functions");
        let globals_object = original.getattr("__globals__")?;
        let globals = globals_object.downcast_exact::<PyDict>()?;
        let function_builtins_object = original.getattr("__builtins__")?;
        let function_builtins = function_builtins_object.downcast_exact::<PyDict>()?;
        for (name, builtin) in [
            ("int", RegisteredBuiltin::Int32),
            ("int32", RegisteredBuiltin::Int32),
            ("bool", RegisteredBuiltin::Bool),
            ("range", RegisteredBuiltin::Range),
        ] {
            let expected = match builtin {
                RegisteredBuiltin::Int32 => PyInt::type_object(py),
                RegisteredBuiltin::Bool => PyBool::type_object(py),
                RegisteredBuiltin::Range => unsafe {
                    // SAFETY: the GIL is held and CPython owns PyRange_Type for
                    // the lifetime of this interpreter.
                    PyType::from_borrowed_type_ptr(
                        py,
                        std::ptr::addr_of_mut!(pyo3::ffi::PyRange_Type),
                    )
                },
            };
            let is_exact_builtin = match globals.get_item(name)? {
                Some(value) => value.is(&expected),
                None => function_builtins
                    .get_item(name)?
                    .is_some_and(|value| value.is(&expected)),
            };
            if is_exact_builtin {
                bindings.push(BuiltinNameBindingInput {
                    definition_id,
                    name: name.to_owned(),
                    builtin,
                });
            }
        }
    }
    Ok(bindings)
}

const fn compute_type_name(compute_type: ComputeType) -> &'static str {
    match compute_type {
        ComputeType::Bool => "bool",
        ComputeType::Int32 => "i32",
    }
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
        CollectedDefinitionRole::Compute => RegisteredDefinitionRole::Compute,
        CollectedDefinitionRole::MorphismDefinition => RegisteredDefinitionRole::MorphismDefinition,
        CollectedDefinitionRole::Atomic => RegisteredDefinitionRole::Atomic,
    }
}
