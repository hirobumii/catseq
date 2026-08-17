//! Entry-rooted analysis over the exact source session registered by #76.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use nac3ast::{Constant, Expr, ExprKind, Keyword, Location, Operator, Stmt, StmtKind, Unaryop};

use crate::compute_validation::{
    ComputeType, ComputeValidation, ValidatedComputeInterface, validate_compute_roots,
};
use crate::registered_modules::{
    RegisteredDefinition, RegisteredDefinitionRole, RegisteredKernelModules,
};
use crate::source_hir::{
    CallArgumentBinding, CallArgumentOrigin, ComputeCallReference, DefinitionCallEdge,
    DependencyRole, DurationUnit, ExternalRead, MorphismComposition, ResolvedCallTarget,
    SemanticFact, SourceAnchor, SourceBinding, SourceHirKind, SourceHirNode, SourceIntrinsic,
    SourceLiteral, SourceValueOperation, TopologyEffect, TypedSourceHir, ValueAvailability,
    ValueType, ValueTypeConstructor,
};
use crate::typed::{
    ParameterAuthority, ParameterKind, ParameterSemantics, TypeSignature, TypedCheckReport,
    TypedDefinition, TypedParameter,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestResolutionError {
    message: String,
}

impl RequestResolutionError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for RequestResolutionError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for RequestResolutionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedExternalRead {
    pub id: u32,
    pub name: String,
    pub value_type: ValueType,
    pub availability: ValueAvailability,
    pub value: SourceLiteral,
}

pub trait RegisteredRequestResolver {
    fn is_entry_owner_method(
        &mut self,
        definition_id: usize,
        anchor: &SourceAnchor,
    ) -> Result<bool, RequestResolutionError>;

    fn resolve_annotation_binding(
        &mut self,
        definition_id: usize,
        path: &str,
        anchor: &SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError>;

    fn resolve_callable_binding(
        &mut self,
        definition_id: usize,
        path: &str,
        bound_entry_owner: bool,
        anchor: &SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError>;

    fn resolve_duration_unit(
        &mut self,
        definition_id: usize,
        path: &str,
        anchor: &SourceAnchor,
    ) -> Result<DurationUnit, RequestResolutionError>;

    fn resolve_exp_param(
        &mut self,
        definition_id: usize,
        owner_attribute: &str,
        anchor: &SourceAnchor,
    ) -> Result<ResolvedExternalRead, RequestResolutionError>;
}

pub struct RegisteredEntryAnalysis {
    report: TypedCheckReport,
    compute: Option<ComputeValidation>,
}

impl RegisteredEntryAnalysis {
    pub const fn report(&self) -> &TypedCheckReport {
        &self.report
    }

    pub const fn compute(&self) -> Option<&ComputeValidation> {
        self.compute.as_ref()
    }

    pub fn into_parts(self) -> (TypedCheckReport, Option<ComputeValidation>) {
        (self.report, self.compute)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredAnalysisError {
    message: String,
    anchor: Option<SourceAnchor>,
}

impl RegisteredAnalysisError {
    fn plain(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            anchor: None,
        }
    }

    fn at(message: impl Into<String>, anchor: SourceAnchor) -> Self {
        Self {
            message: message.into(),
            anchor: Some(anchor),
        }
    }
}

impl Display for RegisteredAnalysisError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)?;
        if let Some(anchor) = &self.anchor {
            write!(
                formatter,
                " at {}:{}:{}",
                anchor.file_name(),
                anchor.line(),
                anchor.column()
            )?;
        }
        Ok(())
    }
}

impl Error for RegisteredAnalysisError {}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct LocationKey {
    row: usize,
    column: usize,
}

impl From<Location> for LocationKey {
    fn from(location: Location) -> Self {
        Self {
            row: location.row,
            column: location.column,
        }
    }
}

#[derive(Clone, Debug)]
enum PlannedCall {
    Definition {
        definition_id: usize,
        role: RegisteredDefinitionRole,
        bound_entry_owner: bool,
    },
    Intrinsic(SourceIntrinsic),
    Compute {
        definition_id: usize,
        work_id: u32,
    },
}

#[derive(Clone, Debug)]
struct DefinitionPlan {
    signature: TypeSignature,
    resolved_expressions: ResolvedExpressions,
}

#[derive(Clone, Debug, Default)]
struct ResolvedExpressions {
    calls: BTreeMap<LocationKey, PlannedCall>,
    external_reads: BTreeMap<LocationKey, ResolvedExternalRead>,
    duration_units: BTreeMap<LocationKey, DurationUnit>,
}

pub fn analyze_registered_entry<R: RegisteredRequestResolver>(
    registered: &RegisteredKernelModules,
    resolver: &mut R,
) -> Result<RegisteredEntryAnalysis, RegisteredAnalysisError> {
    Analyzer::new(registered, resolver).analyze()
}

struct Analyzer<'a, R> {
    registered: &'a RegisteredKernelModules,
    resolver: &'a mut R,
    active: Vec<usize>,
    discovery_order: Vec<usize>,
    plans: BTreeMap<usize, DefinitionPlan>,
    signatures: BTreeMap<usize, TypeSignature>,
    compute_roots: BTreeSet<usize>,
    call_edges: Vec<DefinitionCallEdge>,
    external_reads: BTreeMap<u32, ExternalRead>,
    next_work_id: u32,
}

impl<'a, R: RegisteredRequestResolver> Analyzer<'a, R> {
    fn new(registered: &'a RegisteredKernelModules, resolver: &'a mut R) -> Self {
        Self {
            registered,
            resolver,
            active: Vec::new(),
            discovery_order: Vec::new(),
            plans: BTreeMap::new(),
            signatures: BTreeMap::new(),
            compute_roots: BTreeSet::new(),
            call_edges: Vec::new(),
            external_reads: BTreeMap::new(),
            next_work_id: 0,
        }
    }

    fn analyze(mut self) -> Result<RegisteredEntryAnalysis, RegisteredAnalysisError> {
        let entry_id = self.registered.entry_definition_id();
        let entry = self.definition(entry_id)?.clone();
        if entry.role() != RegisteredDefinitionRole::Kernel {
            return Err(RegisteredAnalysisError::at(
                "registered entry must have the Kernel role",
                self.definition_anchor(&entry),
            ));
        }
        self.discover_definition(entry_id, None)?;

        let compute = if self.compute_roots.is_empty() {
            None
        } else {
            let roots = self.compute_roots.iter().copied().collect::<Vec<_>>();
            Some(
                validate_compute_roots(self.registered, &roots)
                    .map_err(|error| RegisteredAnalysisError::plain(error.to_string()))?,
            )
        };
        let interfaces = compute
            .as_ref()
            .map(|validation| {
                validation
                    .interfaces()
                    .iter()
                    .map(|interface| (interface.definition_id(), interface))
                    .collect::<BTreeMap<_, _>>()
            })
            .unwrap_or_default();

        let mut definitions = Vec::with_capacity(self.discovery_order.len());
        let mut compute_calls = Vec::new();
        for definition_id in &self.discovery_order {
            let definition = self.definition(*definition_id)?;
            let plan = self
                .plans
                .get(definition_id)
                .expect("discovered definitions always retain analysis plans");
            let hir = if matches!(
                definition.role(),
                RegisteredDefinitionRole::Atomic | RegisteredDefinitionRole::Intrinsic
            ) {
                TypedSourceHir::new(
                    *definition_id,
                    definition.qualified_name().to_owned(),
                    Vec::new(),
                    Vec::new(),
                    Vec::new(),
                    Vec::new(),
                )
            } else {
                let body = self.function_body(*definition_id)?;
                DefinitionLowerer::new(
                    self.registered,
                    definition,
                    plan,
                    &self.signatures,
                    &interfaces,
                    &mut compute_calls,
                )
                .lower(body)?
            };
            let module = self.module(definition.module_id());
            definitions.push(TypedDefinition::from_registered(
                definition,
                module,
                plan.signature.clone(),
                hir,
            ));
        }

        let queried_modules = definitions
            .iter()
            .map(|definition| definition.module().to_owned())
            .chain(compute.as_ref().into_iter().flat_map(|validation| {
                validation
                    .unit_store()
                    .source_units()
                    .iter()
                    .map(|unit| unit.import_name().to_owned())
            }))
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let report = TypedCheckReport::new(
            entry_id,
            format!(
                "{}.{}",
                self.module(entry.module_id()).import_name(),
                entry.qualified_name()
            ),
            definitions,
            self.call_edges,
            self.external_reads.into_values().collect(),
            compute_calls,
            queried_modules,
        );
        Ok(RegisteredEntryAnalysis { report, compute })
    }

    fn discover_definition(
        &mut self,
        definition_id: usize,
        call_anchor: Option<SourceAnchor>,
    ) -> Result<(), RegisteredAnalysisError> {
        if self.plans.contains_key(&definition_id) {
            return Ok(());
        }
        if self.active.contains(&definition_id) {
            return Err(RegisteredAnalysisError::at(
                "recursive Kernel/Morphism calls are unsupported",
                call_anchor.expect("recursive discovery always originates at a call"),
            ));
        }
        let definition = self.definition(definition_id)?.clone();
        match definition.role() {
            RegisteredDefinitionRole::Compute => {
                self.compute_roots.insert(definition_id);
                return Ok(());
            }
            RegisteredDefinitionRole::Atomic | RegisteredDefinitionRole::Intrinsic => {
                let signature = self.signature(definition_id)?;
                self.discovery_order.push(definition_id);
                self.plans.insert(
                    definition_id,
                    DefinitionPlan {
                        signature,
                        resolved_expressions: ResolvedExpressions::default(),
                    },
                );
                return Ok(());
            }
            RegisteredDefinitionRole::Kernel | RegisteredDefinitionRole::MorphismDefinition => {}
        }

        self.active.push(definition_id);
        self.discovery_order.push(definition_id);
        let signature = self.signature(definition_id)?;
        let body = self.function_body(definition_id)?.to_vec();
        let mut resolved_expressions = ResolvedExpressions::default();
        self.validate_body(&definition, &signature, &body, &mut resolved_expressions)?;
        self.plans.insert(
            definition_id,
            DefinitionPlan {
                signature,
                resolved_expressions,
            },
        );
        let popped = self.active.pop();
        assert_eq!(popped, Some(definition_id));
        Ok(())
    }

    fn signature(
        &mut self,
        definition_id: usize,
    ) -> Result<TypeSignature, RegisteredAnalysisError> {
        if let Some(signature) = self.signatures.get(&definition_id) {
            return Ok(signature.clone());
        }
        let definition = self.definition(definition_id)?.clone();
        let statement = self
            .registered
            .definition_ast(definition_id)
            .expect("registered definitions always retain an exact AST");
        let StmtKind::FunctionDef {
            args,
            returns,
            body: _,
            ..
        } = &statement.node
        else {
            return Err(RegisteredAnalysisError::at(
                "registered source definition must be a synchronous function",
                self.definition_anchor(&definition),
            ));
        };
        if args.vararg.is_some() || args.kwarg.is_some() {
            return Err(RegisteredAnalysisError::at(
                "registered source parameters do not admit variadic arguments",
                self.definition_anchor(&definition),
            ));
        }

        let entry_id = self.registered.entry_definition_id();
        let mut parameters = Vec::new();
        let positional_count = args.posonlyargs.len() + args.args.len();
        let defaults_start = positional_count - args.defaults.len();
        for (index, argument) in args.posonlyargs.iter().chain(&args.args).enumerate() {
            let name = argument.node.arg.to_string();
            let anchor = self.anchor(definition.module_id(), argument.location);
            let is_entry_owner = index == 0
                && self
                    .resolver
                    .is_entry_owner_method(definition_id, &anchor)
                    .map_err(|error| {
                        RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                    })?;
            let binding = if is_entry_owner {
                if argument.node.annotation.is_some() {
                    return Err(RegisteredAnalysisError::at(
                        "entry owner receiver must not declare a source ABI type",
                        anchor,
                    ));
                }
                SourceBinding::EntryOwner
            } else {
                let annotation = argument.node.annotation.as_deref().ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        format!("parameter `{name}` requires an admitted annotation"),
                        anchor.clone(),
                    )
                })?;
                self.resolve_annotation(&definition, annotation)?
            };
            let default = if index >= defaults_start {
                let value_type = binding.value_type().ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "source authority parameters cannot declare defaults",
                        anchor.clone(),
                    )
                })?;
                Some(self.resolve_default(
                    &definition,
                    &args.defaults[index - defaults_start],
                    value_type,
                )?)
            } else {
                None
            };
            let kind = if index < args.posonlyargs.len() {
                ParameterKind::PositionalOnly
            } else {
                ParameterKind::PositionalOrKeyword
            };
            parameters.push(match binding {
                SourceBinding::ValueType(value_type) => {
                    TypedParameter::value(name, value_type, kind, default)
                }
                SourceBinding::EntryOwner => {
                    TypedParameter::source(name, ParameterAuthority::EntryOwner, kind)
                }
                SourceBinding::ExpParams => {
                    TypedParameter::source(name, ParameterAuthority::ExpParams, kind)
                }
                _ => {
                    return Err(RegisteredAnalysisError::at(
                        "parameter annotation does not denote an admitted value or source authority",
                        anchor,
                    ));
                }
            });
        }
        for (argument, default) in args.kwonlyargs.iter().zip(&args.kw_defaults) {
            let name = argument.node.arg.to_string();
            let anchor = self.anchor(definition.module_id(), argument.location);
            let annotation = argument.node.annotation.as_deref().ok_or_else(|| {
                RegisteredAnalysisError::at(
                    format!("parameter `{name}` requires an admitted annotation"),
                    anchor.clone(),
                )
            })?;
            let binding = self.resolve_annotation(&definition, annotation)?;
            let default = default
                .as_ref()
                .map(|default| {
                    let value_type = binding.value_type().ok_or_else(|| {
                        RegisteredAnalysisError::at(
                            "source authority parameters cannot declare defaults",
                            anchor.clone(),
                        )
                    })?;
                    self.resolve_default(&definition, default, value_type)
                })
                .transpose()?;
            parameters.push(match binding {
                SourceBinding::ValueType(value_type) => {
                    TypedParameter::value(name, value_type, ParameterKind::KeywordOnly, default)
                }
                SourceBinding::ExpParams => TypedParameter::source(
                    name,
                    ParameterAuthority::ExpParams,
                    ParameterKind::KeywordOnly,
                ),
                _ => {
                    return Err(RegisteredAnalysisError::at(
                        "parameter annotation does not denote an admitted value or source authority",
                        anchor,
                    ));
                }
            });
        }
        let returns = returns.as_deref().ok_or_else(|| {
            RegisteredAnalysisError::at(
                "registered source definitions require a return annotation",
                self.definition_anchor(&definition),
            )
        })?;
        let return_type = self.resolve_value_annotation(&definition, returns)?;
        let sequencing_role = match definition.role() {
            RegisteredDefinitionRole::MorphismDefinition => Some("Morphism Definition"),
            RegisteredDefinitionRole::Atomic => Some("Atomic Morphism"),
            _ => None,
        };
        if let Some(role) = sequencing_role
            && return_type != ValueType::Morphism
        {
            return Err(RegisteredAnalysisError::at(
                format!("{role} return annotation must be Morphism"),
                self.anchor(definition.module_id(), returns.location),
            ));
        }
        if definition_id == entry_id
            && (parameters.len() != 2
                || parameters[0].authority() != Some(&ParameterAuthority::EntryOwner)
                || parameters[1].authority() != Some(&ParameterAuthority::ExpParams)
                || return_type != ValueType::Morphism)
        {
            return Err(RegisteredAnalysisError::at(
                "entry signature must be (entry owner, ExpParams) -> Morphism",
                self.definition_anchor(&definition),
            ));
        }
        let signature = TypeSignature::new(parameters, return_type);
        self.signatures.insert(definition_id, signature.clone());
        Ok(signature)
    }

    fn resolve_annotation(
        &mut self,
        definition: &RegisteredDefinition,
        annotation: &Expr,
    ) -> Result<SourceBinding, RegisteredAnalysisError> {
        let anchor = self.anchor(definition.module_id(), annotation.location);
        match &annotation.node {
            ExprKind::Subscript { value, slice, .. } => {
                let path = direct_path(value).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "source type constructor must resolve through one direct exact binding",
                        anchor.clone(),
                    )
                })?;
                let binding = self
                    .resolver
                    .resolve_annotation_binding(definition.id(), &path, &anchor)
                    .map_err(|error| {
                        RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                    })?;
                let item = self.resolve_value_annotation(definition, slice)?;
                match binding {
                    SourceBinding::TypeConstructor(ValueTypeConstructor::List) => {
                        Ok(SourceBinding::ValueType(ValueType::List(Box::new(item))))
                    }
                    SourceBinding::TypeConstructor(ValueTypeConstructor::Sequence) => Ok(
                        SourceBinding::ValueType(ValueType::Sequence(Box::new(item))),
                    ),
                    _ => Err(RegisteredAnalysisError::at(
                        format!("annotation `{path}` is not an admitted source type constructor"),
                        anchor,
                    )),
                }
            }
            ExprKind::BinOp {
                left,
                op: Operator::BitOr,
                right,
            } if matches!(
                left.node,
                ExprKind::Constant {
                    value: Constant::None,
                    ..
                }
            ) =>
            {
                Ok(SourceBinding::ValueType(ValueType::Optional(Box::new(
                    self.resolve_value_annotation(definition, right)?,
                ))))
            }
            ExprKind::BinOp {
                left,
                op: Operator::BitOr,
                right,
            } if matches!(
                right.node,
                ExprKind::Constant {
                    value: Constant::None,
                    ..
                }
            ) =>
            {
                Ok(SourceBinding::ValueType(ValueType::Optional(Box::new(
                    self.resolve_value_annotation(definition, left)?,
                ))))
            }
            _ => {
                let path = direct_path(annotation).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "annotation must resolve through one direct exact binding",
                        anchor.clone(),
                    )
                })?;
                self.resolver
                    .resolve_annotation_binding(definition.id(), &path, &anchor)
                    .map_err(|error| RegisteredAnalysisError::at(error.to_string(), anchor.clone()))
            }
        }
    }

    fn resolve_value_annotation(
        &mut self,
        definition: &RegisteredDefinition,
        annotation: &Expr,
    ) -> Result<ValueType, RegisteredAnalysisError> {
        match self.resolve_annotation(definition, annotation)? {
            SourceBinding::ValueType(value_type) => Ok(value_type),
            _ => Err(RegisteredAnalysisError::at(
                "annotation does not denote an admitted value type",
                self.anchor(definition.module_id(), annotation.location),
            )),
        }
    }

    fn resolve_default(
        &self,
        definition: &RegisteredDefinition,
        expression: &Expr,
        expected: &ValueType,
    ) -> Result<SourceLiteral, RegisteredAnalysisError> {
        let literal = source_literal(expression).ok_or_else(|| {
            RegisteredAnalysisError::at(
                "registered source defaults must be scalar literal values",
                self.anchor(definition.module_id(), expression.location),
            )
        })?;
        if source_literal_matches(&literal, expected) {
            Ok(literal)
        } else {
            Err(RegisteredAnalysisError::at(
                format!("source default does not match declared type {expected}"),
                self.anchor(definition.module_id(), expression.location),
            ))
        }
    }

    fn validate_body(
        &mut self,
        definition: &RegisteredDefinition,
        signature: &TypeSignature,
        body: &[Stmt],
        resolved_expressions: &mut ResolvedExpressions,
    ) -> Result<(), RegisteredAnalysisError> {
        if body.is_empty()
            || !matches!(
                body.last().map(|stmt| &stmt.node),
                Some(StmtKind::Return { .. })
            )
        {
            return Err(RegisteredAnalysisError::at(
                "reachable Kernel/Morphism definitions require one final top-level return",
                self.definition_anchor(definition),
            ));
        }
        let mut locals = signature
            .parameters()
            .iter()
            .map(|parameter| parameter.name().to_owned())
            .collect::<BTreeSet<_>>();
        let mut parameter_bindings = signature
            .parameters()
            .iter()
            .map(|parameter| {
                let binding = match parameter.semantics() {
                    ParameterSemantics::Value { value_type, .. } => {
                        SourceBinding::ValueType(value_type.clone())
                    }
                    ParameterSemantics::SourceAuthority(authority) => authority.source_binding(),
                };
                (parameter.name().to_owned(), binding)
            })
            .collect::<BTreeMap<_, _>>();
        for (index, statement) in body.iter().enumerate() {
            match &statement.node {
                StmtKind::Assign { targets, value, .. } => {
                    if targets.len() != 1 {
                        return Err(self.unsupported_statement(definition, statement));
                    }
                    let ExprKind::Name { id, .. } = &targets[0].node else {
                        return Err(self.unsupported_statement(definition, statement));
                    };
                    self.scan_expression(
                        definition,
                        value,
                        &locals,
                        &parameter_bindings,
                        resolved_expressions,
                    )?;
                    let name = id.to_string();
                    locals.insert(name.clone());
                    parameter_bindings.remove(&name);
                }
                StmtKind::Return {
                    value: Some(value), ..
                } if index + 1 == body.len() => {
                    self.scan_expression(
                        definition,
                        value,
                        &locals,
                        &parameter_bindings,
                        resolved_expressions,
                    )?;
                }
                _ => return Err(self.unsupported_statement(definition, statement)),
            }
        }
        Ok(())
    }

    fn scan_expression(
        &mut self,
        definition: &RegisteredDefinition,
        expression: &Expr,
        locals: &BTreeSet<String>,
        parameter_bindings: &BTreeMap<String, SourceBinding>,
        resolved_expressions: &mut ResolvedExpressions,
    ) -> Result<(), RegisteredAnalysisError> {
        match &expression.node {
            ExprKind::Name { .. } | ExprKind::Constant { .. } => Ok(()),
            ExprKind::UnaryOp { .. }
                if matches!(
                    source_literal(expression),
                    Some(SourceLiteral::Int32(_)) | Some(SourceLiteral::Float64(_))
                ) =>
            {
                Ok(())
            }
            ExprKind::Subscript { value, slice, .. } => {
                let (params_name, owner_name, attribute) = exp_param_path(value, slice)
                    .ok_or_else(|| {
                        RegisteredAnalysisError::at(
                            "only params[self.<ExpParam>] subscripts are admitted",
                            self.anchor(definition.module_id(), expression.location),
                        )
                    })?;
                if parameter_bindings.get(&params_name) != Some(&SourceBinding::ExpParams)
                    || parameter_bindings.get(&owner_name) != Some(&SourceBinding::EntryOwner)
                {
                    return Err(RegisteredAnalysisError::at(
                        "parameter reads require the exact entry owner and ExpParams parameters",
                        self.anchor(definition.module_id(), expression.location),
                    ));
                }
                let anchor = self.anchor(definition.module_id(), expression.location);
                let resolved = self
                    .resolver
                    .resolve_exp_param(definition.id(), &attribute, &anchor)
                    .map_err(|error| {
                        RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                    })?;
                if !matches!(
                    resolved.value_type,
                    ValueType::Bool | ValueType::Int32 | ValueType::Float64 | ValueType::String
                ) {
                    return Err(RegisteredAnalysisError::at(
                        format!(
                            "ExpParam `{}` has unsupported type {}",
                            resolved.name, resolved.value_type
                        ),
                        anchor,
                    ));
                }
                let external = ExternalRead::new(
                    resolved.id,
                    resolved.name.clone(),
                    resolved.value_type.clone(),
                    resolved.availability,
                    resolved.value.clone(),
                    anchor,
                );
                if let Some(previous) = self.external_reads.get(&resolved.id)
                    && (previous.value_type() != external.value_type()
                        || previous.availability() != external.availability()
                        || previous.value() != external.value())
                {
                    return Err(RegisteredAnalysisError::at(
                        "one request-local external value resolved inconsistently",
                        external.anchor().clone(),
                    ));
                }
                self.external_reads.entry(resolved.id).or_insert(external);
                resolved_expressions
                    .external_reads
                    .insert(LocationKey::from(expression.location), resolved);
                Ok(())
            }
            ExprKind::BinOp {
                left,
                op: Operator::Mult,
                right,
            } => {
                self.scan_expression(
                    definition,
                    left,
                    locals,
                    parameter_bindings,
                    resolved_expressions,
                )?;
                let path = direct_path(right).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "physical Duration units must resolve through one direct exact binding",
                        self.anchor(definition.module_id(), right.location),
                    )
                })?;
                let root = path.split('.').next().expect("direct paths are non-empty");
                if locals.contains(root) {
                    return Err(RegisteredAnalysisError::at(
                        format!("physical Duration unit `{path}` is not an exact source binding"),
                        self.anchor(definition.module_id(), right.location),
                    ));
                }
                let anchor = self.anchor(definition.module_id(), right.location);
                let unit = self
                    .resolver
                    .resolve_duration_unit(definition.id(), &path, &anchor)
                    .map_err(|error| {
                        RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                    })?;
                if resolved_expressions
                    .duration_units
                    .insert(LocationKey::from(expression.location), unit)
                    .is_some()
                {
                    return Err(RegisteredAnalysisError::at(
                        "two physical Duration expressions share one source identity",
                        self.anchor(definition.module_id(), expression.location),
                    ));
                }
                Ok(())
            }
            ExprKind::BinOp {
                left,
                op: Operator::RShift,
                right,
            } => {
                self.scan_expression(
                    definition,
                    left,
                    locals,
                    parameter_bindings,
                    resolved_expressions,
                )?;
                self.scan_expression(
                    definition,
                    right,
                    locals,
                    parameter_bindings,
                    resolved_expressions,
                )
            }
            ExprKind::Call {
                func,
                args,
                keywords,
            } => {
                if args
                    .iter()
                    .any(|argument| matches!(argument.node, ExprKind::Starred { .. }))
                    || keywords.iter().any(|keyword| keyword.node.arg.is_none())
                {
                    return Err(RegisteredAnalysisError::at(
                        "argument unpacking is outside the initial source subset",
                        self.anchor(definition.module_id(), expression.location),
                    ));
                }
                let path = direct_path(func).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "indirect or dynamically selected calls are unsupported",
                        self.anchor(definition.module_id(), func.location),
                    )
                })?;
                let root = path.split('.').next().expect("direct paths are non-empty");
                let bound_entry_owner =
                    parameter_bindings.get(root) == Some(&SourceBinding::EntryOwner);
                if locals.contains(root) && !bound_entry_owner {
                    return Err(RegisteredAnalysisError::at(
                        "indirect or dynamically selected calls are unsupported",
                        self.anchor(definition.module_id(), func.location),
                    ));
                }
                let anchor = self.anchor(definition.module_id(), expression.location);
                let planned = if let Some(callee_id) = self
                    .registered
                    .resolve_definition_name(definition.module_id(), &path)
                {
                    self.plan_registered_call(
                        definition.id(),
                        callee_id,
                        bound_entry_owner,
                        &anchor,
                    )?
                } else {
                    match self
                        .resolver
                        .resolve_callable_binding(
                            definition.id(),
                            &path,
                            bound_entry_owner,
                            &anchor,
                        )
                        .map_err(|error| {
                            RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                        })? {
                        SourceBinding::Definition {
                            definition_id,
                            role: _,
                        } => self.plan_registered_call(
                            definition.id(),
                            definition_id,
                            bound_entry_owner,
                            &anchor,
                        )?,
                        SourceBinding::Intrinsic(intrinsic) => PlannedCall::Intrinsic(intrinsic),
                        SourceBinding::HostRpc { display_name } => {
                            return Err(RegisteredAnalysisError::at(
                                format!(
                                    "unimplemented: host RPC calls are not implemented ({display_name})"
                                ),
                                anchor,
                            ));
                        }
                        SourceBinding::Unsupported { display_name } => {
                            return Err(RegisteredAnalysisError::at(
                                format!(
                                    "indirect or dynamically selected callable `{display_name}` is unsupported"
                                ),
                                anchor,
                            ));
                        }
                        SourceBinding::ValueType(_)
                        | SourceBinding::TypeConstructor(_)
                        | SourceBinding::DurationUnit(_)
                        | SourceBinding::EntryOwner
                        | SourceBinding::ExpParams
                        | SourceBinding::ExpParam { .. } => {
                            return Err(RegisteredAnalysisError::at(
                                format!("source binding `{path}` is not callable"),
                                anchor,
                            ));
                        }
                    }
                };
                if resolved_expressions
                    .calls
                    .insert(LocationKey::from(expression.location), planned)
                    .is_some()
                {
                    return Err(RegisteredAnalysisError::at(
                        "two calls share one source identity",
                        anchor,
                    ));
                }
                for argument in args {
                    self.scan_expression(
                        definition,
                        argument,
                        locals,
                        parameter_bindings,
                        resolved_expressions,
                    )?;
                }
                for keyword in keywords {
                    self.scan_expression(
                        definition,
                        &keyword.node.value,
                        locals,
                        parameter_bindings,
                        resolved_expressions,
                    )?;
                }
                Ok(())
            }
            _ => Err(RegisteredAnalysisError::at(
                "unsupported expression in the initial Kernel/Morphism source subset",
                self.anchor(definition.module_id(), expression.location),
            )),
        }
    }

    fn plan_registered_call(
        &mut self,
        caller_definition_id: usize,
        callee_definition_id: usize,
        bound_entry_owner: bool,
        anchor: &SourceAnchor,
    ) -> Result<PlannedCall, RegisteredAnalysisError> {
        let callee = self.definition(callee_definition_id)?.clone();
        let callee_name = format!(
            "{}.{}",
            self.module(callee.module_id()).import_name(),
            callee.qualified_name()
        );
        self.call_edges.push(DefinitionCallEdge::new(
            caller_definition_id,
            callee_definition_id,
            callee_name,
            callee.role(),
            anchor.clone(),
        ));
        match callee.role() {
            RegisteredDefinitionRole::Compute => {
                self.compute_roots.insert(callee_definition_id);
                let work_id = self.next_work_id;
                self.next_work_id = self.next_work_id.checked_add(1).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "Compute work identity exceeds u32 capacity",
                        anchor.clone(),
                    )
                })?;
                Ok(PlannedCall::Compute {
                    definition_id: callee_definition_id,
                    work_id,
                })
            }
            role => {
                self.discover_definition(callee_definition_id, Some(anchor.clone()))?;
                Ok(PlannedCall::Definition {
                    definition_id: callee_definition_id,
                    role,
                    bound_entry_owner,
                })
            }
        }
    }

    fn unsupported_statement(
        &self,
        definition: &RegisteredDefinition,
        statement: &Stmt,
    ) -> RegisteredAnalysisError {
        RegisteredAnalysisError::at(
            "unsupported statement in the initial loop-free Kernel/Morphism source subset",
            self.anchor(definition.module_id(), statement.location),
        )
    }

    fn function_body(&self, definition_id: usize) -> Result<&[Stmt], RegisteredAnalysisError> {
        let definition = self.definition(definition_id)?;
        let statement = self
            .registered
            .definition_ast(definition_id)
            .expect("registered definitions always retain an exact AST");
        let StmtKind::FunctionDef { body, .. } = &statement.node else {
            return Err(RegisteredAnalysisError::at(
                "registered source definition must be a synchronous function",
                self.definition_anchor(definition),
            ));
        };
        Ok(match body.first().map(|statement| &statement.node) {
            Some(StmtKind::Expr { value, .. })
                if matches!(
                    value.node,
                    ExprKind::Constant {
                        value: Constant::Str(_),
                        ..
                    }
                ) =>
            {
                &body[1..]
            }
            _ => body,
        })
    }

    fn definition(&self, id: usize) -> Result<&RegisteredDefinition, RegisteredAnalysisError> {
        self.registered.definition(id).ok_or_else(|| {
            RegisteredAnalysisError::plain(format!(
                "registered definition id {id} is absent from this request"
            ))
        })
    }

    fn module(&self, id: usize) -> &crate::registered_modules::RegisteredModule {
        self.registered
            .modules()
            .iter()
            .find(|module| module.id() == id)
            .expect("registered definitions always refer to retained modules")
    }

    fn definition_anchor(&self, definition: &RegisteredDefinition) -> SourceAnchor {
        self.anchor(definition.module_id(), definition.location())
    }

    fn anchor(&self, module_id: usize, location: Location) -> SourceAnchor {
        let module = self.module(module_id);
        SourceAnchor::new(
            module.import_name(),
            module.file_name(),
            location.row,
            location.column,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum LocalBinding {
    Value {
        node_id: u32,
        value_type: ValueType,
        availability: ValueAvailability,
        topology_effect: TopologyEffect,
    },
    Source(SourceBinding),
}

#[derive(Clone)]
struct LoweredExpression {
    node_id: u32,
    value_type: ValueType,
    availability: ValueAvailability,
    topology_effect: TopologyEffect,
}

#[derive(Clone)]
struct CallParameter {
    name: String,
    semantics: CallParameterSemantics,
    kind: ParameterKind,
}

#[derive(Clone)]
enum CallParameterSemantics {
    Value {
        value_type: ValueType,
        default: Option<SourceLiteral>,
    },
    SourceAuthority,
}

#[derive(Clone, Copy)]
enum ExplicitCallArgumentOrigin {
    Positional,
    Keyword,
}

enum BoundCallArgumentValue {
    Explicit {
        argument_index: usize,
        origin: ExplicitCallArgumentOrigin,
    },
    Default(SourceLiteral),
}

struct BoundCallArgument {
    parameter_id: usize,
    value: BoundCallArgumentValue,
}

struct DefinitionLowerer<'a, 'b> {
    registered: &'a RegisteredKernelModules,
    definition: &'a RegisteredDefinition,
    plan: &'a DefinitionPlan,
    signatures: &'a BTreeMap<usize, TypeSignature>,
    compute_interfaces: &'a BTreeMap<usize, &'b ValidatedComputeInterface>,
    compute_calls: &'a mut Vec<ComputeCallReference>,
    nodes: Vec<SourceHirNode>,
    edges: Vec<u32>,
    roots: Vec<u32>,
    facts: Vec<SemanticFact>,
    locals: BTreeMap<String, LocalBinding>,
}

impl<'a, 'b> DefinitionLowerer<'a, 'b> {
    fn new(
        registered: &'a RegisteredKernelModules,
        definition: &'a RegisteredDefinition,
        plan: &'a DefinitionPlan,
        signatures: &'a BTreeMap<usize, TypeSignature>,
        compute_interfaces: &'a BTreeMap<usize, &'b ValidatedComputeInterface>,
        compute_calls: &'a mut Vec<ComputeCallReference>,
    ) -> Self {
        Self {
            registered,
            definition,
            plan,
            signatures,
            compute_interfaces,
            compute_calls,
            nodes: Vec::new(),
            edges: Vec::new(),
            roots: Vec::new(),
            facts: Vec::new(),
            locals: BTreeMap::new(),
        }
    }

    fn lower(mut self, body: &[Stmt]) -> Result<TypedSourceHir, RegisteredAnalysisError> {
        for parameter in self.plan.signature.parameters() {
            let binding = match parameter.semantics() {
                ParameterSemantics::Value { value_type, .. } => LocalBinding::Value {
                    node_id: u32::MAX,
                    value_type: value_type.clone(),
                    availability: ValueAvailability::Compile,
                    topology_effect: TopologyEffect::Empty,
                },
                ParameterSemantics::SourceAuthority(authority) => {
                    LocalBinding::Source(authority.source_binding())
                }
            };
            self.locals.insert(parameter.name().to_owned(), binding);
        }
        for statement in body {
            let root = self.lower_statement(statement)?;
            self.roots.push(root);
        }
        self.propagate_roles();
        Ok(TypedSourceHir::new(
            self.definition.id(),
            self.definition.qualified_name().to_owned(),
            self.nodes,
            self.edges,
            self.roots,
            self.facts,
        ))
    }

    fn lower_statement(&mut self, statement: &Stmt) -> Result<u32, RegisteredAnalysisError> {
        match &statement.node {
            StmtKind::Assign { targets, value, .. } => {
                let ExprKind::Name { id, .. } = &targets[0].node else {
                    unreachable!("the discovery pass admitted only simple-name assignments")
                };
                let value = self.lower_expression(value)?;
                let target_anchor = self.anchor(targets[0].location);
                let mut target_fact = SemanticFact::value(
                    value.value_type.clone(),
                    value.availability,
                    TopologyEffect::Empty,
                );
                target_fact.set_resolved_node(value.node_id);
                let target = self.push_node(
                    SourceHirKind::Name,
                    Some(id.to_string()),
                    None,
                    None,
                    &[],
                    target_anchor,
                    target_fact,
                );
                self.locals.insert(
                    id.to_string(),
                    LocalBinding::Value {
                        node_id: value.node_id,
                        value_type: value.value_type,
                        availability: value.availability,
                        topology_effect: value.topology_effect,
                    },
                );
                let fact =
                    SemanticFact::value(ValueType::Unit, value.availability, value.topology_effect);
                Ok(self.push_node(
                    SourceHirKind::Assignment,
                    None,
                    None,
                    None,
                    &[target, value.node_id],
                    self.anchor(statement.location),
                    fact,
                ))
            }
            StmtKind::Return {
                value: Some(value), ..
            } => {
                let value = self.lower_expression(value)?;
                self.require_type(
                    self.plan.signature.return_type(),
                    &value.value_type,
                    value.node_id,
                )?;
                self.add_role(
                    value.node_id,
                    if value.value_type == ValueType::Morphism {
                        DependencyRole::Structural
                    } else {
                        DependencyRole::Relocatable
                    },
                );
                let fact = SemanticFact::value(
                    value.value_type,
                    value.availability,
                    value.topology_effect,
                );
                Ok(self.push_node(
                    SourceHirKind::Return,
                    None,
                    None,
                    None,
                    &[value.node_id],
                    self.anchor(statement.location),
                    fact,
                ))
            }
            _ => unreachable!("the discovery pass rejected unsupported statements"),
        }
    }

    fn lower_expression(
        &mut self,
        expression: &Expr,
    ) -> Result<LoweredExpression, RegisteredAnalysisError> {
        match &expression.node {
            ExprKind::Name { id, .. } => {
                let name = id.to_string();
                let binding = self.locals.get(&name).cloned().ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        format!("unresolved source name `{name}`"),
                        self.anchor(expression.location),
                    )
                })?;
                let LocalBinding::Value {
                    node_id: resolved_node,
                    value_type,
                    availability,
                    topology_effect,
                } = binding
                else {
                    return Err(RegisteredAnalysisError::at(
                        format!("source authority `{name}` is not an ordinary value"),
                        self.anchor(expression.location),
                    ));
                };
                let mut fact =
                    SemanticFact::value(value_type.clone(), availability, topology_effect);
                if resolved_node != u32::MAX {
                    fact.set_resolved_node(resolved_node);
                }
                let node_id = self.push_node(
                    SourceHirKind::Name,
                    Some(name),
                    None,
                    None,
                    &[],
                    self.anchor(expression.location),
                    fact,
                );
                Ok(LoweredExpression {
                    node_id,
                    value_type,
                    availability,
                    topology_effect,
                })
            }
            ExprKind::Constant { .. } | ExprKind::UnaryOp { .. } => {
                let (value_type, literal) = match &expression.node {
                    ExprKind::Constant { value, .. } => match value {
                        Constant::None => (ValueType::None, SourceLiteral::None),
                        Constant::Bool(value) => (ValueType::Bool, SourceLiteral::Bool(*value)),
                        Constant::Int(value) => {
                            let value = i32::try_from(*value).map_err(|_| {
                                RegisteredAnalysisError::at(
                                    "integer literal is outside the CatSeq Int32 source profile",
                                    self.anchor(expression.location),
                                )
                            })?;
                            (ValueType::Int32, SourceLiteral::Int32(value))
                        }
                        Constant::Float(value) => {
                            (ValueType::Float64, SourceLiteral::Float64(value.to_bits()))
                        }
                        Constant::Str(value) => {
                            (ValueType::String, SourceLiteral::String(value.clone()))
                        }
                        _ => {
                            return Err(RegisteredAnalysisError::at(
                                "unsupported literal in the initial Kernel/Morphism source subset",
                                self.anchor(expression.location),
                            ));
                        }
                    },
                    ExprKind::UnaryOp { .. } => {
                        let literal = source_literal(expression)
                            .expect("the discovery pass admitted only signed numeric literals");
                        (source_literal_value_type(&literal), literal)
                    }
                    _ => unreachable!("this arm matches only literals"),
                };
                let fact = SemanticFact::value(
                    value_type.clone(),
                    ValueAvailability::Compile,
                    TopologyEffect::Empty,
                );
                let node_id = self.push_node(
                    SourceHirKind::Constant,
                    None,
                    Some(literal),
                    None,
                    &[],
                    self.anchor(expression.location),
                    fact,
                );
                Ok(LoweredExpression {
                    node_id,
                    value_type,
                    availability: ValueAvailability::Compile,
                    topology_effect: TopologyEffect::Empty,
                })
            }
            ExprKind::Subscript { value, slice, .. } => {
                self.lower_exp_param_read(expression, value, slice)
            }
            ExprKind::BinOp {
                left,
                op: Operator::Mult,
                right,
            } => {
                let scalar = self.lower_expression(left)?;
                if !matches!(scalar.value_type, ValueType::Int32 | ValueType::Float64) {
                    return Err(RegisteredAnalysisError::at(
                        format!(
                            "physical Duration scale must be i32 or f64, found {}",
                            scalar.value_type
                        ),
                        self.nodes[scalar.node_id as usize].anchor().clone(),
                    ));
                }
                let unit = *self
                    .plan
                    .resolved_expressions
                    .duration_units
                    .get(&LocationKey::from(expression.location))
                    .expect("every admitted physical Duration retains its exact unit");
                let path = direct_path(right)
                    .expect("the discovery pass admitted only direct exact Duration units");
                let unit_node = self.push_node(
                    if path.contains('.') {
                        SourceHirKind::Attribute
                    } else {
                        SourceHirKind::Name
                    },
                    Some(path),
                    None,
                    None,
                    &[],
                    self.anchor(right.location),
                    SemanticFact::binding(SourceBinding::DurationUnit(unit)),
                );
                let fact = SemanticFact::value(
                    ValueType::Duration,
                    scalar.availability,
                    TopologyEffect::Empty,
                );
                let node_id = self.push_value_operation_node(
                    SourceHirKind::Binary,
                    SourceValueOperation::ScaleDuration,
                    &[scalar.node_id, unit_node],
                    self.anchor(expression.location),
                    fact,
                );
                Ok(LoweredExpression {
                    node_id,
                    value_type: ValueType::Duration,
                    availability: scalar.availability,
                    topology_effect: TopologyEffect::Empty,
                })
            }
            ExprKind::BinOp {
                left,
                op: Operator::RShift,
                right,
            } => {
                let left = self.lower_expression(left)?;
                let right = self.lower_expression(right)?;
                self.require_type(&ValueType::Morphism, &left.value_type, left.node_id)?;
                self.require_type(&ValueType::Morphism, &right.value_type, right.node_id)?;
                self.add_role(left.node_id, DependencyRole::Structural);
                self.add_role(right.node_id, DependencyRole::Structural);
                let availability = left.availability.max(right.availability);
                let fact = SemanticFact::value(
                    ValueType::Morphism,
                    availability,
                    TopologyEffect::Morphism,
                );
                let node_id = self.push_node(
                    SourceHirKind::Binary,
                    None,
                    None,
                    Some(MorphismComposition::AutoSerial),
                    &[left.node_id, right.node_id],
                    self.anchor(expression.location),
                    fact,
                );
                Ok(LoweredExpression {
                    node_id,
                    value_type: ValueType::Morphism,
                    availability,
                    topology_effect: TopologyEffect::Morphism,
                })
            }
            ExprKind::Call {
                func,
                args,
                keywords,
            } => self.lower_call(expression, func, args, keywords),
            _ => unreachable!("the discovery pass rejected unsupported expressions"),
        }
    }

    fn lower_exp_param_read(
        &mut self,
        expression: &Expr,
        value: &Expr,
        slice: &Expr,
    ) -> Result<LoweredExpression, RegisteredAnalysisError> {
        let (params_name, owner_name, attribute) = exp_param_path(value, slice)
            .expect("the discovery pass admitted only exact ExpParam reads");
        let resolved = self
            .plan
            .resolved_expressions
            .external_reads
            .get(&LocationKey::from(expression.location))
            .expect("every admitted ExpParam read retains its exact resolution");
        assert_eq!(
            self.locals.get(&params_name),
            Some(&LocalBinding::Source(SourceBinding::ExpParams)),
            "the discovery pass retained exact ExpParams authority",
        );
        assert_eq!(
            self.locals.get(&owner_name),
            Some(&LocalBinding::Source(SourceBinding::EntryOwner)),
            "the discovery pass retained exact entry-owner authority",
        );
        let params = self.push_node(
            SourceHirKind::Name,
            Some(params_name.clone()),
            None,
            None,
            &[],
            self.anchor(value.location),
            SemanticFact::binding(SourceBinding::ExpParams),
        );
        let owner = self.push_node(
            SourceHirKind::Name,
            Some(owner_name.clone()),
            None,
            None,
            &[],
            self.anchor(slice.location),
            SemanticFact::binding(SourceBinding::EntryOwner),
        );
        let attribute_node = self.push_node(
            SourceHirKind::Attribute,
            Some(format!("{owner_name}.{attribute}")),
            None,
            None,
            &[owner],
            self.anchor(slice.location),
            SemanticFact::binding(SourceBinding::ExpParam {
                id: resolved.id,
                name: resolved.name.clone(),
                value_type: resolved.value_type.clone(),
            }),
        );
        let mut fact = SemanticFact::value(
            resolved.value_type.clone(),
            resolved.availability,
            TopologyEffect::Empty,
        );
        fact.set_external_read_id(resolved.id);
        let node_id = self.push_node(
            SourceHirKind::Subscript,
            Some(format!("{params_name}[{owner_name}.{attribute}]")),
            None,
            None,
            &[params, attribute_node],
            self.anchor(expression.location),
            fact,
        );
        Ok(LoweredExpression {
            node_id,
            value_type: resolved.value_type.clone(),
            availability: resolved.availability,
            topology_effect: TopologyEffect::Empty,
        })
    }

    fn lower_call(
        &mut self,
        expression: &Expr,
        function: &Expr,
        arguments: &[Expr],
        keywords: &[Keyword],
    ) -> Result<LoweredExpression, RegisteredAnalysisError> {
        let path = direct_path(function).expect("the discovery pass admitted only direct calls");
        let planned = self
            .plan
            .resolved_expressions
            .calls
            .get(&LocationKey::from(expression.location))
            .expect("every admitted call retains exact resolution")
            .clone();
        let callee_binding = match &planned {
            PlannedCall::Intrinsic(intrinsic) => SourceBinding::Intrinsic(*intrinsic),
            PlannedCall::Definition {
                definition_id,
                role,
                ..
            } => SourceBinding::Definition {
                definition_id: *definition_id,
                role: *role,
            },
            PlannedCall::Compute { definition_id, .. } => SourceBinding::Definition {
                definition_id: *definition_id,
                role: RegisteredDefinitionRole::Compute,
            },
        };
        let callee_fact = SemanticFact::binding(callee_binding);
        let callee = self.push_node(
            if path.contains('.') {
                SourceHirKind::Attribute
            } else {
                SourceHirKind::Name
            },
            Some(path),
            None,
            None,
            &[],
            self.anchor(function.location),
            callee_fact,
        );
        self.add_role(callee, DependencyRole::Structural);
        let mut lowered_arguments = Vec::with_capacity(arguments.len() + keywords.len());
        for argument in arguments {
            lowered_arguments.push(self.lower_expression(argument)?);
        }
        for keyword in keywords {
            lowered_arguments.push(self.lower_expression(&keyword.node.value)?);
        }
        let availability = lowered_arguments
            .iter()
            .map(|argument| argument.availability)
            .max()
            .unwrap_or(ValueAvailability::Compile);
        let (parameters, result_type, topology_effect, resolved_call) = match planned {
            PlannedCall::Intrinsic(intrinsic) => {
                let (parameters, result, effect) = match intrinsic {
                    SourceIntrinsic::Cycles => (
                        vec![CallParameter {
                            name: "count".to_owned(),
                            semantics: CallParameterSemantics::Value {
                                value_type: ValueType::Int32,
                                default: None,
                            },
                            kind: ParameterKind::PositionalOrKeyword,
                        }],
                        ValueType::Duration,
                        TopologyEffect::Empty,
                    ),
                    SourceIntrinsic::Id => {
                        (Vec::new(), ValueType::Morphism, TopologyEffect::Morphism)
                    }
                    SourceIntrinsic::Wait => (
                        vec![CallParameter {
                            name: "duration".to_owned(),
                            semantics: CallParameterSemantics::Value {
                                value_type: ValueType::Duration,
                                default: None,
                            },
                            kind: ParameterKind::PositionalOrKeyword,
                        }],
                        ValueType::Morphism,
                        TopologyEffect::Morphism,
                    ),
                };
                (
                    parameters,
                    result,
                    effect,
                    ResolvedCallTarget::Intrinsic(intrinsic),
                )
            }
            PlannedCall::Definition {
                definition_id,
                role,
                bound_entry_owner,
            } => {
                let signature = self
                    .signatures
                    .get(&definition_id)
                    .expect("reachable registered calls retain signatures");
                let mut parameters = Vec::new();
                for parameter in signature.parameters() {
                    if bound_entry_owner
                        && parameter.authority() == Some(&ParameterAuthority::EntryOwner)
                    {
                        continue;
                    }
                    parameters.push(CallParameter {
                        name: parameter.name().to_owned(),
                        semantics: match parameter.semantics() {
                            ParameterSemantics::Value {
                                value_type,
                                default,
                            } => CallParameterSemantics::Value {
                                value_type: value_type.clone(),
                                default: default.clone(),
                            },
                            ParameterSemantics::SourceAuthority(_) => {
                                CallParameterSemantics::SourceAuthority
                            }
                        },
                        kind: parameter.kind(),
                    });
                }
                (
                    parameters,
                    signature.return_type().clone(),
                    if signature.return_type() == &ValueType::Morphism {
                        TopologyEffect::Morphism
                    } else {
                        TopologyEffect::Empty
                    },
                    ResolvedCallTarget::Definition {
                        definition_id,
                        role,
                    },
                )
            }
            PlannedCall::Compute {
                definition_id,
                work_id,
            } => {
                let interface = self.compute_interfaces.get(&definition_id).ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        "validated Compute closure did not publish the called interface",
                        self.anchor(expression.location),
                    )
                })?;
                let statement = self
                    .registered
                    .definition_ast(definition_id)
                    .expect("validated Compute definitions retain their registered AST");
                let StmtKind::FunctionDef { args, .. } = &statement.node else {
                    unreachable!("validated Compute definitions are synchronous functions")
                };
                let source_parameters = args
                    .posonlyargs
                    .iter()
                    .map(|argument| (argument.node.arg.to_string(), ParameterKind::PositionalOnly))
                    .chain(args.args.iter().map(|argument| {
                        (
                            argument.node.arg.to_string(),
                            ParameterKind::PositionalOrKeyword,
                        )
                    }))
                    .collect::<Vec<_>>();
                assert_eq!(
                    source_parameters.len(),
                    interface.parameters().len(),
                    "validated Compute interface must match its registered source arity"
                );
                let parameters = source_parameters
                    .into_iter()
                    .zip(interface.parameters().iter().copied())
                    .map(|((name, kind), value_type)| CallParameter {
                        name,
                        semantics: CallParameterSemantics::Value {
                            value_type: value_type_from_compute(value_type),
                            default: None,
                        },
                        kind,
                    })
                    .collect::<Vec<_>>();
                let result = value_type_from_compute(interface.result());
                let provenance = interface.provenance();
                let reference = ComputeCallReference::new(
                    work_id,
                    definition_id,
                    interface.parameters().to_vec(),
                    interface.result(),
                    interface.abi_signature().to_owned(),
                    interface.abi_hash().to_owned(),
                    availability,
                    SourceAnchor::new(
                        provenance.module(),
                        provenance.file_name(),
                        provenance.line(),
                        provenance.column(),
                    ),
                    self.anchor(expression.location),
                );
                self.compute_calls.push(reference.clone());
                (
                    parameters,
                    result,
                    TopologyEffect::Empty,
                    ResolvedCallTarget::Compute(Box::new(reference)),
                )
            }
        };
        let keyword_names = keywords
            .iter()
            .map(|keyword| {
                keyword
                    .node
                    .arg
                    .as_ref()
                    .expect("the discovery pass rejected keyword unpacking")
                    .to_string()
            })
            .collect::<Vec<_>>();
        let bound_arguments = bind_call_arguments(
            &parameters,
            arguments.len(),
            &keyword_names,
            self.anchor(expression.location),
        )?;
        let mut ordered_arguments = Vec::with_capacity(bound_arguments.len());
        let mut call_arguments = Vec::with_capacity(bound_arguments.len());
        for bound in bound_arguments {
            let parameter = &parameters[bound.parameter_id];
            let (actual, origin) = match bound.value {
                BoundCallArgumentValue::Explicit {
                    argument_index,
                    origin,
                } => (
                    lowered_arguments[argument_index].clone(),
                    match origin {
                        ExplicitCallArgumentOrigin::Positional => CallArgumentOrigin::Positional,
                        ExplicitCallArgumentOrigin::Keyword => CallArgumentOrigin::Keyword,
                    },
                ),
                BoundCallArgumentValue::Default(literal) => {
                    let value_type = source_literal_value_type(&literal);
                    let fact = SemanticFact::value(
                        value_type.clone(),
                        ValueAvailability::Compile,
                        TopologyEffect::Empty,
                    );
                    let node_id = self.push_node(
                        SourceHirKind::Constant,
                        None,
                        Some(literal),
                        None,
                        &[],
                        self.anchor(expression.location),
                        fact,
                    );
                    (
                        LoweredExpression {
                            node_id,
                            value_type,
                            availability: ValueAvailability::Compile,
                            topology_effect: TopologyEffect::Empty,
                        },
                        CallArgumentOrigin::Default,
                    )
                }
            };
            let expected = match &parameter.semantics {
                CallParameterSemantics::Value { value_type, .. } => value_type,
                CallParameterSemantics::SourceAuthority => {
                    return Err(RegisteredAnalysisError::at(
                        "source-authority parameters require their exact bound source value",
                        self.nodes[actual.node_id as usize].anchor().clone(),
                    ));
                }
            };
            self.require_type(expected, &actual.value_type, actual.node_id)?;
            self.add_role(
                actual.node_id,
                if actual.value_type == ValueType::Morphism {
                    DependencyRole::Structural
                } else {
                    DependencyRole::Relocatable
                },
            );
            call_arguments.push(CallArgumentBinding::new(
                parameter.name.clone(),
                actual.node_id,
                origin,
            ));
            ordered_arguments.push(actual);
        }
        let mut children = Vec::with_capacity(ordered_arguments.len() + 1);
        children.push(callee);
        children.extend(ordered_arguments.iter().map(|argument| argument.node_id));
        let mut fact = SemanticFact::value(result_type.clone(), availability, topology_effect);
        fact.set_resolved_call(resolved_call);
        fact.set_call_arguments(call_arguments);
        let node_id = self.push_node(
            SourceHirKind::Call,
            None,
            None,
            None,
            &children,
            self.anchor(expression.location),
            fact,
        );
        Ok(LoweredExpression {
            node_id,
            value_type: result_type,
            availability,
            topology_effect,
        })
    }

    fn require_type(
        &self,
        expected: &ValueType,
        found: &ValueType,
        node_id: u32,
    ) -> Result<(), RegisteredAnalysisError> {
        if expected == found
            || matches!(expected, ValueType::Optional(inner) if found == inner.as_ref() || found == &ValueType::None)
        {
            return Ok(());
        }
        Err(RegisteredAnalysisError::at(
            format!(
                "value type mismatch: expected {}, found {}",
                expected.as_str(),
                found.as_str()
            ),
            self.nodes[node_id as usize].anchor().clone(),
        ))
    }

    #[allow(clippy::too_many_arguments)]
    fn push_node(
        &mut self,
        kind: SourceHirKind,
        symbol: Option<String>,
        literal: Option<SourceLiteral>,
        composition: Option<MorphismComposition>,
        children: &[u32],
        anchor: SourceAnchor,
        fact: SemanticFact,
    ) -> u32 {
        self.push_node_with_operation(
            kind,
            symbol,
            literal,
            composition,
            None,
            children,
            anchor,
            fact,
        )
    }

    fn push_value_operation_node(
        &mut self,
        kind: SourceHirKind,
        operation: SourceValueOperation,
        children: &[u32],
        anchor: SourceAnchor,
        fact: SemanticFact,
    ) -> u32 {
        self.push_node_with_operation(
            kind,
            None,
            None,
            None,
            Some(operation),
            children,
            anchor,
            fact,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn push_node_with_operation(
        &mut self,
        kind: SourceHirKind,
        symbol: Option<String>,
        literal: Option<SourceLiteral>,
        composition: Option<MorphismComposition>,
        value_operation: Option<SourceValueOperation>,
        children: &[u32],
        anchor: SourceAnchor,
        mut fact: SemanticFact,
    ) -> u32 {
        let edge_start =
            u32::try_from(self.edges.len()).expect("Source HIR edge count exceeds u32");
        self.edges.extend_from_slice(children);
        let edge_count = u32::try_from(children.len()).expect("Source HIR node arity exceeds u32");
        let node_id = u32::try_from(self.nodes.len()).expect("Source HIR node count exceeds u32");
        fact.add_role(default_role(fact.value_type()));
        self.nodes.push(SourceHirNode::new(
            kind,
            symbol,
            literal,
            composition,
            value_operation,
            edge_start,
            edge_count,
            anchor,
        ));
        self.facts.push(fact);
        node_id
    }

    fn add_role(&mut self, node_id: u32, role: DependencyRole) {
        self.facts[node_id as usize].add_role(role);
    }

    fn propagate_roles(&mut self) {
        loop {
            let before = self
                .facts
                .iter()
                .map(|fact| fact.roles().len())
                .sum::<usize>();
            for node_id in 0..self.facts.len() {
                let roles = self.facts[node_id].roles().to_vec();
                if let Some(resolved) = self.facts[node_id].resolved_node() {
                    for role in &roles {
                        self.facts[resolved as usize].add_role(*role);
                    }
                }
                let node = &self.nodes[node_id];
                let children = &self.edges
                    [node.edge_start() as usize..(node.edge_start() + node.edge_count()) as usize];
                if node.kind() == SourceHirKind::Return
                    && let Some(value) = children.last()
                {
                    for role in &roles {
                        self.facts[*value as usize].add_role(*role);
                    }
                }
            }
            let after = self
                .facts
                .iter()
                .map(|fact| fact.roles().len())
                .sum::<usize>();
            if after == before {
                break;
            }
        }
    }

    fn anchor(&self, location: Location) -> SourceAnchor {
        let module = self
            .registered
            .modules()
            .iter()
            .find(|module| module.id() == self.definition.module_id())
            .expect("registered definitions always retain their module");
        SourceAnchor::new(
            module.import_name(),
            module.file_name(),
            location.row,
            location.column,
        )
    }
}

fn bind_call_arguments(
    parameters: &[CallParameter],
    positional_count: usize,
    keyword_names: &[String],
    anchor: SourceAnchor,
) -> Result<Vec<BoundCallArgument>, RegisteredAnalysisError> {
    let positional_parameters = parameters
        .iter()
        .enumerate()
        .filter(|(_, parameter)| parameter.kind != ParameterKind::KeywordOnly)
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if positional_count > positional_parameters.len() {
        return Err(RegisteredAnalysisError::at(
            format!(
                "call accepts at most {} positional arguments, found {positional_count}",
                positional_parameters.len()
            ),
            anchor,
        ));
    }

    let mut bound = (0..parameters.len())
        .map(|_| None)
        .collect::<Vec<Option<BoundCallArgumentValue>>>();
    for (argument_index, parameter_id) in positional_parameters
        .into_iter()
        .take(positional_count)
        .enumerate()
    {
        bound[parameter_id] = Some(BoundCallArgumentValue::Explicit {
            argument_index,
            origin: ExplicitCallArgumentOrigin::Positional,
        });
    }
    for (keyword_index, name) in keyword_names.iter().enumerate() {
        let parameter_id = parameters
            .iter()
            .position(|parameter| parameter.name == *name)
            .ok_or_else(|| {
                RegisteredAnalysisError::at(
                    format!("call has no parameter named `{name}`"),
                    anchor.clone(),
                )
            })?;
        let parameter = &parameters[parameter_id];
        if parameter.kind == ParameterKind::PositionalOnly {
            return Err(RegisteredAnalysisError::at(
                format!("positional-only parameter `{name}` cannot be passed by keyword"),
                anchor,
            ));
        }
        if bound[parameter_id].is_some() {
            return Err(RegisteredAnalysisError::at(
                format!("parameter `{name}` is supplied more than once"),
                anchor,
            ));
        }
        bound[parameter_id] = Some(BoundCallArgumentValue::Explicit {
            argument_index: positional_count + keyword_index,
            origin: ExplicitCallArgumentOrigin::Keyword,
        });
    }
    let missing = parameters
        .iter()
        .zip(&bound)
        .filter(|(parameter, bound)| {
            bound.is_none()
                && !matches!(
                    &parameter.semantics,
                    CallParameterSemantics::Value {
                        default: Some(_),
                        ..
                    }
                )
        })
        .map(|(parameter, _)| parameter.name.as_str())
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(RegisteredAnalysisError::at(
            format!(
                "call is missing required parameters: {}",
                missing.join(", ")
            ),
            anchor,
        ));
    }
    Ok(parameters
        .iter()
        .enumerate()
        .map(|(parameter_id, parameter)| BoundCallArgument {
            parameter_id,
            value: bound[parameter_id]
                .take()
                .or_else(|| match &parameter.semantics {
                    CallParameterSemantics::Value { default, .. } => {
                        default.clone().map(BoundCallArgumentValue::Default)
                    }
                    CallParameterSemantics::SourceAuthority => None,
                })
                .expect("every required call parameter was validated as bound"),
        })
        .collect())
}

fn source_literal(expression: &Expr) -> Option<SourceLiteral> {
    match &expression.node {
        ExprKind::Constant { value, .. } => match value {
            Constant::None => Some(SourceLiteral::None),
            Constant::Bool(value) => Some(SourceLiteral::Bool(*value)),
            Constant::Int(value) => i32::try_from(*value).ok().map(SourceLiteral::Int32),
            Constant::Float(value) => Some(SourceLiteral::Float64(value.to_bits())),
            Constant::Str(value) => Some(SourceLiteral::String(value.clone())),
            _ => None,
        },
        ExprKind::UnaryOp { op, operand } => match (op, source_literal(operand)?) {
            (Unaryop::UAdd, SourceLiteral::Int32(value)) => Some(SourceLiteral::Int32(value)),
            (Unaryop::USub, SourceLiteral::Int32(value)) => {
                value.checked_neg().map(SourceLiteral::Int32)
            }
            (Unaryop::UAdd, SourceLiteral::Float64(value)) => Some(SourceLiteral::Float64(value)),
            (Unaryop::USub, SourceLiteral::Float64(value)) => {
                Some(SourceLiteral::Float64((-f64::from_bits(value)).to_bits()))
            }
            _ => None,
        },
        _ => None,
    }
}

fn source_literal_matches(literal: &SourceLiteral, expected: &ValueType) -> bool {
    match (literal, expected) {
        (SourceLiteral::None, ValueType::None | ValueType::Optional(_))
        | (SourceLiteral::Bool(_), ValueType::Bool)
        | (SourceLiteral::Int32(_), ValueType::Int32)
        | (SourceLiteral::Float64(_), ValueType::Float64)
        | (SourceLiteral::String(_), ValueType::String) => true,
        (_, ValueType::Optional(inner)) => source_literal_matches(literal, inner),
        _ => false,
    }
}

fn source_literal_value_type(literal: &SourceLiteral) -> ValueType {
    match literal {
        SourceLiteral::None => ValueType::None,
        SourceLiteral::Bool(_) => ValueType::Bool,
        SourceLiteral::Int32(_) => ValueType::Int32,
        SourceLiteral::Float64(_) => ValueType::Float64,
        SourceLiteral::String(_) => ValueType::String,
    }
}

fn default_role(value_type: Option<&ValueType>) -> DependencyRole {
    if value_type.is_none() || matches!(value_type, Some(ValueType::Morphism | ValueType::Unit)) {
        DependencyRole::Structural
    } else {
        DependencyRole::Relocatable
    }
}

fn value_type_from_compute(compute_type: ComputeType) -> ValueType {
    match compute_type {
        ComputeType::Bool => ValueType::Bool,
        ComputeType::Int32 => ValueType::Int32,
    }
}

fn direct_path(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { id, .. } => Some(id.to_string()),
        ExprKind::Attribute { value, attr, .. } => {
            let root = direct_path(value)?;
            Some(format!("{root}.{attr}"))
        }
        _ => None,
    }
}

fn exp_param_path(value: &Expr, slice: &Expr) -> Option<(String, String, String)> {
    let ExprKind::Name { id: params, .. } = &value.node else {
        return None;
    };
    let ExprKind::Attribute {
        value: owner, attr, ..
    } = &slice.node
    else {
        return None;
    };
    let ExprKind::Name { id: owner, .. } = &owner.node else {
        return None;
    };
    Some((params.to_string(), owner.to_string(), attr.to_string()))
}
