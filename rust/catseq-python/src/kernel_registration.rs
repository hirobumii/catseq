use std::fs;
use std::sync::Arc;

use catseq_frontend::{
    BuiltinNameBindingInput, ComputeType, ComputeValidation, DefinitionNameBindingInput,
    DefinitionRegistrationInput, ModuleRegistrationInput, RegisteredBuiltin,
    RegisteredDefinitionRole, RegisteredKernelModules, RegistrationInput, register_kernel_modules,
    validate_compute_roots,
};
use nac3ast::{Constant, Expr, ExprKind, Operator, StmtKind, Unaryop};
use pyo3::PyTypeInfo;
use pyo3::exceptions::{PyAttributeError, PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyDict, PyFloat, PyFunction, PyInt, PyModule, PyString, PyTuple, PyType,
};

use crate::kernel_collector::{
    CollectedDefinition, CollectedDefinitionRole, PyKernelDefinitionCollection, exact_definition_id,
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
    verify_source_revisions(py, &frontend, &definitions)?;
    Ok(PyRegisteredKernelModules {
        frontend,
        owner,
        entry,
        definitions,
    })
}

fn verify_source_revisions(
    py: Python<'_>,
    frontend: &RegisteredKernelModules,
    definitions: &[CollectedDefinition],
) -> PyResult<()> {
    let compile = py.import("builtins")?.getattr("compile")?;
    let code_type = py.import("types")?.getattr("CodeType")?;
    let compiled_modules = frontend
        .modules()
        .iter()
        .map(|module| {
            let code = compile.call1((
                module.source().as_ref(),
                module.file_name(),
                "exec",
                0,
                true,
            ))?;
            Ok((module.id(), code.unbind()))
        })
        .collect::<PyResult<Vec<_>>>()?;

    for registered in frontend.definitions() {
        let definition = definitions.get(registered.id()).ok_or_else(|| {
            PyRuntimeError::new_err("registered source revision has no Python definition")
        })?;
        let original = definition
            .original
            .bind(py)
            .downcast_exact::<PyFunction>()?;
        let original_code = original.getattr("__code__")?;
        let source_start_line = original_code
            .getattr("co_firstlineno")?
            .extract::<usize>()?;
        let module_code = compiled_modules
            .iter()
            .find(|(module_id, _)| *module_id == registered.module_id())
            .expect("every registered definition retains compiled module source")
            .1
            .bind(py);
        let candidate = find_compiled_definition_code(
            module_code,
            &code_type,
            registered.qualified_name(),
            source_start_line,
        )?
        .ok_or_else(|| source_revision_error(frontend, registered.id(), "compiled identity"))?;
        if let Some(attribute) = code_revision_mismatch(&original_code, &candidate)? {
            return Err(source_revision_error(frontend, registered.id(), attribute));
        }
        let statement = frontend
            .definition_ast(registered.id())
            .expect("registered definitions retain their exact parsed statement");
        if let Some(attribute) = signature_revision_mismatch(py, original, statement)? {
            return Err(source_revision_error(frontend, registered.id(), attribute));
        }
    }
    Ok(())
}

fn signature_revision_mismatch(
    py: Python<'_>,
    function: &Bound<'_, PyFunction>,
    statement: &nac3ast::Stmt,
) -> PyResult<Option<&'static str>> {
    let StmtKind::FunctionDef { args, returns, .. } = &statement.node else {
        return Ok(Some("signature shape"));
    };

    let defaults_object = function.getattr("__defaults__")?;
    let defaults = if defaults_object.is_none() {
        Vec::new()
    } else {
        defaults_object
            .downcast_exact::<PyTuple>()?
            .iter()
            .collect::<Vec<_>>()
    };
    if defaults.len() != args.defaults.len() {
        return Ok(Some("positional defaults"));
    }
    for (source, runtime) in args.defaults.iter().zip(defaults) {
        if let Some(source) = revision_literal(source)
            && runtime_revision_literal(py, &runtime)? != Some(source)
        {
            return Ok(Some("positional defaults"));
        }
    }

    let kw_defaults_object = function.getattr("__kwdefaults__")?;
    let kw_defaults = if kw_defaults_object.is_none() {
        None
    } else {
        Some(kw_defaults_object.downcast_exact::<PyDict>()?)
    };
    let source_kw_default_count = args
        .kw_defaults
        .iter()
        .filter(|default| default.is_some())
        .count();
    if kw_defaults.map_or(0, |defaults| defaults.len()) != source_kw_default_count {
        return Ok(Some("keyword defaults"));
    }
    for (argument, source) in args.kwonlyargs.iter().zip(&args.kw_defaults) {
        let Some(source) = source else {
            continue;
        };
        let name = argument.node.arg.to_string();
        let runtime = match kw_defaults {
            Some(defaults) => defaults.get_item(&name)?,
            None => None,
        }
        .ok_or_else(|| PyRuntimeError::new_err("Python keyword default is unavailable"))?;
        if let Some(source) = revision_literal(source)
            && runtime_revision_literal(py, &runtime)? != Some(source)
        {
            return Ok(Some("keyword defaults"));
        }
    }

    let annotations_object = function.getattr("__annotations__")?;
    let annotations = annotations_object.downcast_exact::<PyDict>()?;
    let mut source_annotations = Vec::new();
    for argument in args
        .posonlyargs
        .iter()
        .chain(&args.args)
        .chain(&args.kwonlyargs)
    {
        if let Some(annotation) = argument.node.annotation.as_deref() {
            source_annotations.push((argument.node.arg.to_string(), annotation));
        }
    }
    if let Some(argument) = &args.vararg
        && let Some(annotation) = argument.node.annotation.as_deref()
    {
        source_annotations.push((argument.node.arg.to_string(), annotation));
    }
    if let Some(argument) = &args.kwarg
        && let Some(annotation) = argument.node.annotation.as_deref()
    {
        source_annotations.push((argument.node.arg.to_string(), annotation));
    }
    if let Some(returns) = returns.as_deref() {
        source_annotations.push(("return".to_owned(), returns));
    }
    if annotations.len() != source_annotations.len() {
        return Ok(Some("annotations"));
    }
    for (name, source) in source_annotations {
        let runtime = annotations
            .get_item(name)?
            .ok_or_else(|| PyRuntimeError::new_err("Python annotation is unavailable"))?;
        if !annotation_revision_matches(py, function, source, &runtime)? {
            return Ok(Some("annotations"));
        }
    }

    Ok(None)
}

#[derive(Eq, PartialEq)]
enum RevisionLiteral {
    None,
    Bool(bool),
    Int(String),
    Float(u64),
    String(String),
}

fn revision_literal(expression: &Expr) -> Option<RevisionLiteral> {
    match &expression.node {
        ExprKind::Constant { value, .. } => match value {
            Constant::None => Some(RevisionLiteral::None),
            Constant::Bool(value) => Some(RevisionLiteral::Bool(*value)),
            Constant::Int(value) => Some(RevisionLiteral::Int(value.to_string())),
            Constant::Float(value) => Some(RevisionLiteral::Float(value.to_bits())),
            Constant::Str(value) => Some(RevisionLiteral::String(value.clone())),
            _ => None,
        },
        ExprKind::UnaryOp { op, operand } => match (op, revision_literal(operand)?) {
            (Unaryop::UAdd, value @ (RevisionLiteral::Int(_) | RevisionLiteral::Float(_))) => {
                Some(value)
            }
            (Unaryop::USub, RevisionLiteral::Int(value)) => Some(RevisionLiteral::Int(format!(
                "-{}",
                value.trim_start_matches('+')
            ))),
            (Unaryop::USub, RevisionLiteral::Float(value)) => {
                Some(RevisionLiteral::Float((-f64::from_bits(value)).to_bits()))
            }
            _ => None,
        },
        _ => None,
    }
}

fn runtime_revision_literal(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
) -> PyResult<Option<RevisionLiteral>> {
    if value.is_none() {
        return Ok(Some(RevisionLiteral::None));
    }
    if value.get_type().is(&PyBool::type_object(py)) {
        return Ok(Some(RevisionLiteral::Bool(value.extract()?)));
    }
    if value.get_type().is(&PyInt::type_object(py)) {
        return Ok(Some(RevisionLiteral::Int(
            value.str()?.to_str()?.to_owned(),
        )));
    }
    if value.get_type().is(&PyFloat::type_object(py)) {
        return Ok(Some(RevisionLiteral::Float(
            value.extract::<f64>()?.to_bits(),
        )));
    }
    if value.get_type().is(&PyString::type_object(py)) {
        return Ok(Some(RevisionLiteral::String(value.extract()?)));
    }
    Ok(None)
}

fn annotation_revision_matches(
    py: Python<'_>,
    function: &Bound<'_, PyFunction>,
    source: &Expr,
    runtime: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    if let Ok(runtime) = runtime.downcast_exact::<PyString>() {
        let Some(source) = render_annotation(source) else {
            return Ok(false);
        };
        let runtime = runtime.to_str()?;
        return Ok(compact_annotation(runtime) == compact_annotation(&source));
    }
    if let Some(source) = resolve_direct_annotation(function, source)? {
        return Ok(source.is(runtime));
    }
    match &source.node {
        ExprKind::Constant {
            value: Constant::None,
            ..
        } => {
            let none_type = py.import("types")?.getattr("NoneType")?;
            Ok(runtime.is_none() || runtime.is(&none_type))
        }
        ExprKind::Subscript { value, slice, .. } => {
            let Some(source_origin) = resolve_direct_annotation(function, value)? else {
                return Ok(false);
            };
            let runtime_origin = match runtime.getattr("__origin__") {
                Ok(origin) => origin,
                Err(error) if error.is_instance_of::<PyAttributeError>(py) => return Ok(false),
                Err(error) => return Err(error),
            };
            let source_origin = normalized_annotation_origin(py, &source_origin)?;
            if !source_origin.is(&runtime_origin) {
                return Ok(false);
            }
            let runtime_arguments_object = runtime.getattr("__args__")?;
            let runtime_arguments = runtime_arguments_object.downcast_exact::<PyTuple>()?;
            let source_arguments = match &slice.node {
                ExprKind::Tuple { elts, .. } => elts.iter().collect::<Vec<_>>(),
                _ => vec![slice.as_ref()],
            };
            if source_arguments.len() != runtime_arguments.len() {
                return Ok(false);
            }
            for (source, runtime) in source_arguments.into_iter().zip(runtime_arguments.iter()) {
                if !annotation_revision_matches(py, function, source, &runtime)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        ExprKind::BinOp {
            left,
            op: Operator::BitOr,
            right,
        } => {
            let runtime_arguments_object = runtime.getattr("__args__")?;
            let runtime_arguments = runtime_arguments_object.downcast_exact::<PyTuple>()?;
            if runtime_arguments.len() != 2 {
                return Ok(false);
            }
            annotation_revision_matches(py, function, left, &runtime_arguments.get_item(0)?)
                .and_then(|left_matches| {
                    if !left_matches {
                        return Ok(false);
                    }
                    annotation_revision_matches(
                        py,
                        function,
                        right,
                        &runtime_arguments.get_item(1)?,
                    )
                })
        }
        _ => Ok(false),
    }
}

fn normalized_annotation_origin<'py>(
    py: Python<'py>,
    annotation: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    match annotation.getattr("__origin__") {
        Ok(origin) => Ok(origin),
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => Ok(annotation.clone()),
        Err(error) => Err(error),
    }
}

fn render_annotation(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { id, .. } => Some(id.to_string()),
        ExprKind::Attribute { value, attr, .. } => {
            Some(format!("{}.{}", render_annotation(value)?, attr))
        }
        ExprKind::Subscript { value, slice, .. } => Some(format!(
            "{}[{}]",
            render_annotation(value)?,
            render_annotation(slice)?
        )),
        ExprKind::BinOp {
            left,
            op: Operator::BitOr,
            right,
        } => Some(format!(
            "{}|{}",
            render_annotation(left)?,
            render_annotation(right)?
        )),
        ExprKind::Constant {
            value: Constant::None,
            ..
        } => Some("None".to_owned()),
        _ => None,
    }
}

fn compact_annotation(annotation: &str) -> String {
    annotation
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect()
}

fn resolve_direct_annotation<'py>(
    function: &Bound<'py, PyFunction>,
    expression: &Expr,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    let Some(path) = render_direct_path(expression) else {
        return Ok(None);
    };
    let mut segments = path.split('.');
    let root = segments
        .next()
        .expect("rendered annotation paths are non-empty");
    let globals_object = function.getattr("__globals__")?;
    let globals = globals_object.downcast_exact::<PyDict>()?;
    let mut value = if let Some(value) = globals.get_item(root)? {
        value
    } else {
        let builtins_object = function.getattr("__builtins__")?;
        let builtins = builtins_object.downcast_exact::<PyDict>()?;
        let Some(value) = builtins.get_item(root)? else {
            return Ok(None);
        };
        value
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

fn render_direct_path(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { id, .. } => Some(id.to_string()),
        ExprKind::Attribute { value, attr, .. } => {
            Some(format!("{}.{}", render_direct_path(value)?, attr))
        }
        _ => None,
    }
}

fn code_revision_mismatch(
    left: &Bound<'_, PyAny>,
    right: &Bound<'_, PyAny>,
) -> PyResult<Option<&'static str>> {
    for attribute in [
        "co_argcount",
        "co_posonlyargcount",
        "co_kwonlyargcount",
        "co_nlocals",
        "co_stacksize",
        "co_code",
        "co_consts",
        "co_names",
        "co_varnames",
        "co_freevars",
        "co_cellvars",
        "co_exceptiontable",
    ] {
        if !left.getattr(attribute)?.eq(right.getattr(attribute)?)? {
            return Ok(Some(attribute));
        }
    }
    Ok(None)
}

fn find_compiled_definition_code<'py>(
    module_code: &Bound<'py, PyAny>,
    code_type: &Bound<'py, PyAny>,
    qualified_name: &str,
    source_start_line: usize,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    let mut pending = vec![module_code.clone()];
    while let Some(code) = pending.pop() {
        let candidate_name = code.getattr("co_qualname")?.extract::<String>()?;
        let candidate_line = code.getattr("co_firstlineno")?.extract::<usize>()?;
        if candidate_name == qualified_name && candidate_line == source_start_line {
            return Ok(Some(code));
        }
        let constants_object = code.getattr("co_consts")?;
        let constants = constants_object.downcast_exact::<PyTuple>()?;
        for constant in constants.iter() {
            if constant.get_type().is(code_type) {
                pending.push(constant);
            }
        }
    }
    Ok(None)
}

fn source_revision_error(
    frontend: &RegisteredKernelModules,
    definition_id: usize,
    mismatch: &str,
) -> PyErr {
    let definition = frontend
        .definition(definition_id)
        .expect("source revision checks use a registered definition id");
    let module = frontend
        .modules()
        .iter()
        .find(|module| module.id() == definition.module_id())
        .expect("registered definitions retain their module");
    PyRuntimeError::new_err(format!(
        "registered definition {}.{} does not match the source revision at {}:{} ({mismatch})",
        module.import_name(),
        definition.qualified_name(),
        module.file_name(),
        definition.location().row,
    ))
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

pub(crate) const fn compute_type_name(compute_type: ComputeType) -> &'static str {
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
        CollectedDefinitionRole::Intrinsic => RegisteredDefinitionRole::Intrinsic,
    }
}
