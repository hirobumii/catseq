use catseq_frontend::{
    DurationUnit, RegisteredDefinitionRole, RegisteredEntryAnalysis, RegisteredRequestResolver,
    RequestResolutionError, ResolvedExternalRead, SourceBinding, SourceIntrinsic, SourceLiteral,
    SourceValueOperation, ValueAvailability, ValueType, ValueTypeConstructor,
    analyze_registered_entry,
};
use pyo3::PyTypeInfo;
use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyDict, PyFloat, PyFunction, PyInt, PyList, PyModule, PyString, PyTuple, PyType,
};

use crate::kernel_collector::{
    PyKernelDefinitionCollection, collect_entry_kernel_definitions, collect_kernel_definitions,
};
use crate::kernel_registration::{
    PyRegisteredKernelModules, compute_type_name, register_collected_kernel_modules,
};

#[pyclass(name = "_FrontendSession", module = "catseq._native", frozen)]
pub(crate) struct PyFrontendSession {
    _compile_environment: Py<PyDict>,
}

#[pymethods]
impl PyFrontendSession {
    #[new]
    fn new(compile_environment: &Bound<'_, PyAny>) -> PyResult<Self> {
        let compile_environment = compile_environment
            .downcast_exact::<PyDict>()
            .map_err(|_| PyTypeError::new_err("CompileEnvironment must be an exact dict"))?;
        Ok(Self {
            _compile_environment: compile_environment.clone().unbind(),
        })
    }

    fn _analyze_registered_kernel(
        &self,
        py: Python<'_>,
        experiment: &Bound<'_, PyAny>,
        params: &Bound<'_, PyAny>,
    ) -> PyResult<PyTypedSourceAnalysis> {
        let collection = collect_entry_kernel_definitions(py, experiment)?;
        let registered = register_collected_kernel_modules(py, collection)?;
        let mut resolver =
            PythonRegisteredRequestResolver::new(py, &registered, experiment, params)?;
        let inner = analyze_registered_entry(&registered.frontend, &mut resolver)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        Ok(PyTypedSourceAnalysis { inner })
    }
}

#[pyclass(name = "_TypedSourceAnalysis", module = "catseq._native", frozen)]
pub(crate) struct PyTypedSourceAnalysis {
    inner: RegisteredEntryAnalysis,
}

type PyComputeInterfaceRow = (
    usize,
    Vec<&'static str>,
    &'static str,
    String,
    String,
    String,
    usize,
    usize,
);
type PyDurationScaleRow = (
    String,
    &'static str,
    String,
    &'static str,
    String,
    usize,
    usize,
);

#[pymethods]
impl PyTypedSourceAnalysis {
    #[getter]
    fn _entry_name(&self) -> &str {
        self.inner.report().entry()
    }

    #[getter]
    fn _body_definitions(&self) -> Vec<(String, &'static str)> {
        self.inner
            .report()
            .definitions()
            .iter()
            .map(|definition| {
                (
                    definition_name(definition.module(), definition.qualified_name()),
                    definition.role().as_str(),
                )
            })
            .collect()
    }

    #[getter]
    fn _atomic_definitions(&self) -> Vec<(String, String, String, usize, usize)> {
        self.inner
            .report()
            .definitions()
            .iter()
            .filter(|definition| definition.role() == RegisteredDefinitionRole::Atomic)
            .map(|definition| {
                let symbol = definition
                    .atomic_symbol()
                    .expect("registered Atomic definitions always retain a symbol");
                let anchor = definition.anchor();
                (
                    definition_name(definition.module(), definition.qualified_name()),
                    symbol.to_owned(),
                    anchor.file_name().to_owned(),
                    anchor.line(),
                    anchor.column(),
                )
            })
            .collect()
    }

    #[getter]
    fn _call_edges(&self) -> Vec<(String, String, &'static str)> {
        let report = self.inner.report();
        report
            .call_edges()
            .iter()
            .map(|edge| {
                let caller = report
                    .definitions()
                    .iter()
                    .find(|definition| definition.definition_id() == edge.caller_definition_id())
                    .expect("call edges retain a reachable caller definition");
                (
                    definition_name(caller.module(), caller.qualified_name()),
                    edge.callee().to_owned(),
                    edge.callee_role().as_str(),
                )
            })
            .collect()
    }

    #[getter]
    fn _external_reads(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let rows = PyList::empty(py);
        for read in self.inner.report().external_reads() {
            let value = match read.value() {
                SourceLiteral::None => py.None(),
                SourceLiteral::Bool(value) => {
                    value.into_pyobject(py)?.to_owned().into_any().unbind()
                }
                SourceLiteral::Int32(value) => value.into_pyobject(py)?.into_any().unbind(),
                SourceLiteral::Float64(value) => f64::from_bits(*value)
                    .into_pyobject(py)?
                    .into_any()
                    .unbind(),
                SourceLiteral::String(value) => value.into_pyobject(py)?.into_any().unbind(),
            };
            rows.append(PyTuple::new(
                py,
                [
                    read.name().into_pyobject(py)?.into_any().unbind(),
                    read.value_type()
                        .as_str()
                        .into_pyobject(py)?
                        .into_any()
                        .unbind(),
                    read.availability()
                        .as_str()
                        .into_pyobject(py)?
                        .into_any()
                        .unbind(),
                    value,
                ],
            )?)?;
        }
        Ok(rows.into_any().unbind())
    }

    #[getter]
    fn _morphism_compositions(&self) -> Vec<(String, &'static str)> {
        self.inner
            .report()
            .definitions()
            .iter()
            .flat_map(|definition| {
                let name = definition_name(definition.module(), definition.qualified_name());
                definition.hir().nodes().iter().filter_map(move |node| {
                    node.morphism_composition()
                        .map(|composition| (name.clone(), composition.as_str()))
                })
            })
            .collect()
    }

    #[getter]
    fn _duration_scales(&self) -> Vec<PyDurationScaleRow> {
        self.inner
            .report()
            .definitions()
            .iter()
            .flat_map(|definition| {
                let name = definition_name(definition.module(), definition.qualified_name());
                let hir = definition.hir();
                hir.nodes()
                    .iter()
                    .enumerate()
                    .filter_map(move |(node_id, node)| {
                        if node.value_operation() != Some(SourceValueOperation::ScaleDuration) {
                            return None;
                        }
                        let children = &hir.edges()[node.edge_start() as usize
                            ..(node.edge_start() + node.edge_count()) as usize];
                        let [scalar_node, unit_node] = children else {
                            unreachable!("typed physical Duration scaling has exactly two inputs")
                        };
                        let scalar = &hir.facts()[*scalar_node as usize];
                        let unit = match hir.facts()[*unit_node as usize].source_binding() {
                            Some(SourceBinding::DurationUnit(unit)) => *unit,
                            _ => unreachable!(
                                "typed physical Duration scaling retains one exact unit binding"
                            ),
                        };
                        let anchor = node.anchor();
                        Some((
                            name.clone(),
                            unit.as_str(),
                            scalar
                                .value_type()
                                .expect("physical Duration scale input is a typed scalar")
                                .as_str(),
                            hir.facts()[node_id].availability().as_str(),
                            anchor.file_name().to_owned(),
                            anchor.line(),
                            anchor.column(),
                        ))
                    })
            })
            .collect()
    }

    #[getter]
    fn _compute_source_profile_id(&self) -> Option<&'static str> {
        self.inner
            .compute()
            .map(|compute| compute.source_profile_id())
    }

    #[getter]
    fn _compute_unit_count(&self) -> usize {
        self.inner
            .compute()
            .map_or(0, |compute| compute.unit_store().unit_count())
    }

    #[getter]
    fn _compute_source_unit_count(&self) -> usize {
        self.inner
            .compute()
            .map_or(0, |compute| compute.unit_store().source_unit_count())
    }

    #[getter]
    fn _compute_calls(
        &self,
    ) -> Vec<(u32, usize, &'static str, &'static str, String, usize, usize)> {
        self.inner
            .report()
            .compute_calls()
            .iter()
            .map(|call| {
                let anchor = call.call_anchor();
                (
                    call.work_id(),
                    call.definition_id(),
                    call.availability().as_str(),
                    call.topology_effect().as_str(),
                    anchor.file_name().to_owned(),
                    anchor.line(),
                    anchor.column(),
                )
            })
            .collect()
    }

    #[getter]
    fn _compute_interfaces(&self) -> Vec<PyComputeInterfaceRow> {
        self.inner
            .compute()
            .into_iter()
            .flat_map(|compute| compute.interfaces())
            .map(|interface| {
                let provenance = interface.provenance();
                (
                    interface.definition_id(),
                    interface
                        .parameters()
                        .iter()
                        .copied()
                        .map(compute_type_name)
                        .collect(),
                    compute_type_name(interface.result()),
                    interface.abi_signature().to_owned(),
                    interface.abi_hash().to_owned(),
                    provenance.file_name().to_owned(),
                    provenance.line(),
                    provenance.column(),
                )
            })
            .collect()
    }
}

#[pyfunction(name = "_collect_kernel_definitions")]
fn py_collect_kernel_definitions(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
) -> PyResult<PyKernelDefinitionCollection> {
    collect_kernel_definitions(py, experiment)
}

#[pyfunction(name = "_register_kernel_modules")]
fn py_register_kernel_modules(
    py: Python<'_>,
    experiment: &Bound<'_, PyAny>,
) -> PyResult<PyRegisteredKernelModules> {
    let collection = collect_kernel_definitions(py, experiment)?;
    register_collected_kernel_modules(py, collection)
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(py_collect_kernel_definitions, module)?)?;
    module.add_function(wrap_pyfunction!(py_register_kernel_modules, module)?)?;
    module.add_class::<PyFrontendSession>()?;
    module.add_class::<PyTypedSourceAnalysis>()?;
    Ok(())
}

struct PythonRegisteredRequestResolver<'a, 'py> {
    py: Python<'py>,
    registered: &'a PyRegisteredKernelModules,
    experiment: &'a Bound<'py, PyAny>,
    params: &'a Bound<'py, PyAny>,
    external_declarations: Vec<Py<PyAny>>,
}

impl<'a, 'py> PythonRegisteredRequestResolver<'a, 'py> {
    fn new(
        py: Python<'py>,
        registered: &'a PyRegisteredKernelModules,
        experiment: &'a Bound<'py, PyAny>,
        params: &'a Bound<'py, PyAny>,
    ) -> PyResult<Self> {
        let exp_params_type = py
            .import("catseq.experiment.params")?
            .getattr("ExpParams")?;
        if !params.get_type().is(&exp_params_type) {
            return Err(PyTypeError::new_err(
                "params must be an exact ExpParams instance",
            ));
        }
        Ok(Self {
            py,
            registered,
            experiment,
            params,
            external_declarations: Vec::new(),
        })
    }

    fn definition_function(&self, definition_id: usize) -> PyResult<Bound<'py, PyFunction>> {
        self.registered
            .definitions
            .get(definition_id)
            .ok_or_else(|| PyRuntimeError::new_err("registered definition id is unavailable"))?
            .original
            .bind(self.py)
            .downcast_exact::<PyFunction>()
            .cloned()
            .map_err(Into::into)
    }

    fn exact_path(
        &self,
        definition_id: usize,
        path: &str,
        bound_entry_owner: bool,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        let mut segments = path.split('.');
        let root = segments
            .next()
            .expect("registered analysis never requests an empty direct path");
        let mut value = if bound_entry_owner {
            let Some(attribute) = segments.next() else {
                return Ok(Some(self.experiment.clone()));
            };
            let Some(value) = self.raw_owner_attribute(attribute)? else {
                return Ok(None);
            };
            value
        } else {
            let function = self.definition_function(definition_id)?;
            let globals_object = function.getattr("__globals__")?;
            let globals = globals_object.downcast_exact::<PyDict>()?;
            if let Some(value) = globals.get_item(root)? {
                value
            } else {
                let builtins_object = function.getattr("__builtins__")?;
                let builtins = builtins_object.downcast_exact::<PyDict>().map_err(|_| {
                    PyRuntimeError::new_err(
                        "registered Python function must retain an exact __builtins__ dict",
                    )
                })?;
                let Some(value) = builtins.get_item(root)? else {
                    return Ok(None);
                };
                value
            }
        };

        for attribute in segments {
            let Ok(module) = value.downcast_exact::<PyModule>() else {
                return Ok(None);
            };
            let Some(next) = module.dict().get_item(attribute)? else {
                return Ok(None);
            };
            value = next;
        }
        Ok(Some(value))
    }

    fn raw_owner_attribute(&self, name: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
        let mro_object = self.experiment.get_type().getattr("__mro__")?;
        let mro = mro_object.downcast_exact::<PyTuple>()?;
        for class in mro.iter() {
            let namespace = class.getattr("__dict__")?;
            match namespace.get_item(name) {
                Ok(value) => return Ok(Some(value)),
                Err(error) if error.is_instance_of::<PyKeyError>(self.py) => {}
                Err(error) => return Err(error),
            }
        }
        Ok(None)
    }

    fn exact_exp_param_type(&self) -> PyResult<Bound<'py, PyAny>> {
        self.py
            .import("catseq.experiment.params")?
            .getattr("ExpParam")
    }

    fn external_id(&mut self, declaration: &Bound<'py, PyAny>) -> u32 {
        if let Some(index) = self
            .external_declarations
            .iter()
            .position(|known| known.is(declaration))
        {
            return u32::try_from(index).expect("request-local external ids fit u32");
        }
        let id = u32::try_from(self.external_declarations.len())
            .expect("request-local external ids fit u32");
        self.external_declarations
            .push(declaration.clone().unbind());
        id
    }
}

impl RegisteredRequestResolver for PythonRegisteredRequestResolver<'_, '_> {
    fn is_entry_owner_method(
        &mut self,
        definition_id: usize,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<bool, RequestResolutionError> {
        let definition = self
            .registered
            .definitions
            .get(definition_id)
            .ok_or_else(|| RequestResolutionError::new("registered definition is unavailable"))?;
        let registered_definition = self
            .registered
            .frontend
            .definition(definition_id)
            .ok_or_else(|| RequestResolutionError::new("registered definition is unavailable"))?;
        let original = definition.original.bind(self.py);
        let wrapper = definition.wrapper.bind(self.py);
        let mro_object = self
            .experiment
            .get_type()
            .getattr("__mro__")
            .map_err(request_error)?;
        let mro = mro_object
            .downcast_exact::<PyTuple>()
            .map_err(|error| RequestResolutionError::new(error.to_string()))?;
        for class in mro.iter() {
            let class_qualified_name = class
                .getattr("__qualname__")
                .and_then(|value| value.extract::<String>())
                .map_err(request_error)?;
            let Some(remainder) = registered_definition
                .qualified_name()
                .strip_prefix(&class_qualified_name)
            else {
                continue;
            };
            if !remainder.starts_with('.') {
                continue;
            }
            let namespace = class.getattr("__dict__").map_err(request_error)?;
            let values = namespace.call_method0("values").map_err(request_error)?;
            for value in values.try_iter().map_err(request_error)? {
                let value = value.map_err(request_error)?;
                if value.is(original) || value.is(wrapper) {
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }

    fn resolve_annotation_binding(
        &mut self,
        definition_id: usize,
        path: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError> {
        let value = self
            .exact_path(definition_id, path, false)
            .map_err(request_error)?
            .ok_or_else(|| {
                RequestResolutionError::new(format!("annotation `{path}` is unbound"))
            })?;
        if value.is(&PyInt::type_object(self.py)) {
            return Ok(SourceBinding::ValueType(ValueType::Int32));
        }
        if value.is(&PyBool::type_object(self.py)) {
            return Ok(SourceBinding::ValueType(ValueType::Bool));
        }
        if value.is(&PyFloat::type_object(self.py)) {
            return Ok(SourceBinding::ValueType(ValueType::Float64));
        }
        if value.is(&PyString::type_object(self.py)) {
            return Ok(SourceBinding::ValueType(ValueType::String));
        }
        if value.is(&PyList::type_object(self.py)) {
            return Ok(SourceBinding::TypeConstructor(ValueTypeConstructor::List));
        }
        let sequence = self
            .py
            .import("collections.abc")
            .and_then(|module| module.getattr("Sequence"))
            .map_err(request_error)?;
        if value.is(&sequence) {
            return Ok(SourceBinding::TypeConstructor(
                ValueTypeConstructor::Sequence,
            ));
        }
        let morphism_module = self
            .py
            .import("catseq.morphism.core")
            .map_err(request_error)?;
        let morphism = morphism_module.getattr("Morphism").map_err(request_error)?;
        if value.is(&morphism) {
            return Ok(SourceBinding::ValueType(ValueType::Morphism));
        }
        let duration = self
            .py
            .import("catseq.time_utils")
            .and_then(|module| module.getattr("Duration"))
            .map_err(request_error)?;
        if value.is(&duration) {
            return Ok(SourceBinding::ValueType(ValueType::Duration));
        }
        let exp_params = self
            .py
            .import("catseq.experiment.params")
            .and_then(|module| module.getattr("ExpParams"))
            .map_err(request_error)?;
        if value.is(&exp_params) {
            return Ok(SourceBinding::ExpParams);
        }
        if let Ok(value_type) = value.downcast_exact::<PyType>() {
            let module = value_type
                .getattr("__module__")
                .and_then(|value| value.extract::<String>())
                .map_err(request_error)?;
            if module.starts_with("catseq.types.") {
                let qualified_name = value_type
                    .getattr("__qualname__")
                    .and_then(|value| value.extract::<String>())
                    .map_err(request_error)?;
                return Ok(SourceBinding::ValueType(ValueType::Named(format!(
                    "{module}.{qualified_name}"
                ))));
            }
        }
        Err(RequestResolutionError::new(format!(
            "annotation `{path}` is not an admitted exact source type"
        )))
    }

    fn resolve_callable_binding(
        &mut self,
        definition_id: usize,
        path: &str,
        bound_entry_owner: bool,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError> {
        let Some(value) = self
            .exact_path(definition_id, path, bound_entry_owner)
            .map_err(request_error)?
        else {
            return Ok(SourceBinding::Unsupported {
                display_name: path.to_owned(),
            });
        };
        if let Some(definition_id) =
            self.registered.definitions.iter().position(|definition| {
                value.is(&definition.original) || value.is(&definition.wrapper)
            })
        {
            let role = self
                .registered
                .frontend
                .definition(definition_id)
                .expect("Python and Rust registration definitions share exact ids")
                .role();
            return Ok(SourceBinding::Definition {
                definition_id,
                role,
            });
        }
        let cycles = self
            .py
            .import("catseq.time_utils")
            .and_then(|module| module.getattr("cycles"))
            .map_err(request_error)?;
        if value.is(&cycles) {
            return Ok(SourceBinding::Intrinsic(SourceIntrinsic::Cycles));
        }
        let morphism = self
            .py
            .import("catseq.morphism.core")
            .map_err(request_error)?;
        let id = morphism.getattr("Id").map_err(request_error)?;
        if value.is(&id) {
            return Ok(SourceBinding::Intrinsic(SourceIntrinsic::Id));
        }
        let wait = morphism.getattr("Wait").map_err(request_error)?;
        if value.is(&wait) {
            return Ok(SourceBinding::Intrinsic(SourceIntrinsic::Wait));
        }
        if value.downcast_exact::<PyFunction>().is_ok() {
            return Ok(SourceBinding::HostRpc {
                display_name: path.to_owned(),
            });
        }
        Ok(SourceBinding::Unsupported {
            display_name: path.to_owned(),
        })
    }

    fn resolve_duration_unit(
        &mut self,
        definition_id: usize,
        path: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<DurationUnit, RequestResolutionError> {
        let value = self
            .exact_path(definition_id, path, false)
            .map_err(request_error)?
            .ok_or_else(|| {
                RequestResolutionError::new(format!("physical Duration unit `{path}` is unbound"))
            })?;
        let time_utils = self.py.import("catseq.time_utils").map_err(request_error)?;
        for (name, unit) in [
            ("s", DurationUnit::Second),
            ("ms", DurationUnit::Millisecond),
            ("us", DurationUnit::Microsecond),
            ("ns", DurationUnit::Nanosecond),
        ] {
            let exact = time_utils.getattr(name).map_err(request_error)?;
            if value.is(&exact) {
                return Ok(unit);
            }
        }
        Err(RequestResolutionError::new(format!(
            "physical Duration unit `{path}` is not an exact CatSeq SI unit"
        )))
    }

    fn resolve_exp_param(
        &mut self,
        _definition_id: usize,
        owner_attribute: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<ResolvedExternalRead, RequestResolutionError> {
        let declaration = self
            .raw_owner_attribute(owner_attribute)
            .map_err(request_error)?
            .ok_or_else(|| {
                RequestResolutionError::new(format!(
                    "entry owner has no exact ExpParam declaration `{owner_attribute}`"
                ))
            })?;
        let exp_param_type = self.exact_exp_param_type().map_err(request_error)?;
        if !declaration.get_type().is(&exp_param_type) {
            return Err(RequestResolutionError::new(format!(
                "entry owner attribute `{owner_attribute}` is not an exact ExpParam"
            )));
        }
        let declaration_name = declaration
            .getattr("name")
            .and_then(|name| name.extract::<String>())
            .map_err(request_error)?;
        let values = self.params.getattr("_values").map_err(request_error)?;
        let value = values.get_item(&declaration).map_err(|error| {
            if error.is_instance_of::<PyKeyError>(self.py) {
                RequestResolutionError::new(format!(
                    "ExpParams has no value for `{owner_attribute}`"
                ))
            } else {
                request_error(error)
            }
        })?;
        let (value_type, value) = if let Ok(value) = value.downcast_exact::<PyBool>() {
            (
                ValueType::Bool,
                SourceLiteral::Bool(value.extract().map_err(request_error)?),
            )
        } else if let Ok(value) = value.downcast_exact::<PyInt>() {
            let value = value.extract::<i64>().map_err(request_error)?;
            let value = i32::try_from(value).map_err(|_| {
                RequestResolutionError::new(format!(
                    "ExpParam `{owner_attribute}` integer value is outside i32"
                ))
            })?;
            (ValueType::Int32, SourceLiteral::Int32(value))
        } else if let Ok(value) = value.downcast_exact::<PyFloat>() {
            let value = value.extract::<f64>().map_err(request_error)?;
            (ValueType::Float64, SourceLiteral::Float64(value.to_bits()))
        } else if let Ok(value) = value.downcast_exact::<PyString>() {
            let value = value.extract::<String>().map_err(request_error)?;
            (ValueType::String, SourceLiteral::String(value))
        } else {
            return Err(RequestResolutionError::new(format!(
                "ExpParam `{owner_attribute}` must contain an exact bool, i32 int, f64 float, or string"
            )));
        };
        let id = self.external_id(&declaration);
        Ok(ResolvedExternalRead {
            id,
            name: declaration_name,
            value_type,
            availability: ValueAvailability::Compile,
            value,
        })
    }
}

fn request_error(error: PyErr) -> RequestResolutionError {
    RequestResolutionError::new(error.to_string())
}

fn definition_name(module: &str, qualified_name: &str) -> String {
    format!("{module}.{qualified_name}")
}
