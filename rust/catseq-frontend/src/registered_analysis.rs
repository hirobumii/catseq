//! Entry-rooted analysis over the exact source session registered by #76.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use nac3ast::{Constant, Expr, ExprKind, Location, Operator, Stmt, StmtKind};

use crate::compute_validation::{
    ComputeType, ComputeValidation, ValidatedComputeInterface, validate_compute_roots,
};
use crate::registered_modules::{
    RegisteredDefinition, RegisteredDefinitionRole, RegisteredKernelModules,
};
use crate::source_hir::{
    ComputeCallReference, DefinitionCallEdge, DependencyRole, ExternalRead, MorphismComposition,
    ResolvedCallTarget, SemanticFact, SourceAnchor, SourceHirKind, SourceHirNode, SourceIntrinsic,
    SourceLiteral, SourceType, TopologyEffect, TypedSourceHir, ValueAvailability,
};
use crate::typed::{TypeSignature, TypedCheckReport, TypedDefinition, TypedParameter};

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
pub enum ResolvedSourceCallable {
    Definition { definition_id: usize },
    Intrinsic(SourceIntrinsic),
    HostRpc { display_name: String },
    Unsupported { display_name: String },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedExternalRead {
    pub id: u32,
    pub name: String,
    pub source_type: SourceType,
    pub availability: ValueAvailability,
    pub value: SourceLiteral,
}

pub trait RegisteredRequestResolver {
    fn is_entry_owner_method(
        &mut self,
        definition_id: usize,
        anchor: &SourceAnchor,
    ) -> Result<bool, RequestResolutionError>;

    fn resolve_annotation(
        &mut self,
        definition_id: usize,
        path: &str,
        anchor: &SourceAnchor,
    ) -> Result<SourceType, RequestResolutionError>;

    fn resolve_callable(
        &mut self,
        definition_id: usize,
        path: &str,
        bound_entry_owner: bool,
        anchor: &SourceAnchor,
    ) -> Result<ResolvedSourceCallable, RequestResolutionError>;

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
    calls: BTreeMap<LocationKey, PlannedCall>,
    external_reads: BTreeMap<LocationKey, ResolvedExternalRead>,
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
            let hir = if definition.role() == RegisteredDefinitionRole::Atomic {
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
            RegisteredDefinitionRole::Atomic => {
                let signature = self.signature(definition_id)?;
                self.discovery_order.push(definition_id);
                self.plans.insert(
                    definition_id,
                    DefinitionPlan {
                        signature,
                        calls: BTreeMap::new(),
                        external_reads: BTreeMap::new(),
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
        let mut calls = BTreeMap::new();
        let mut reads = BTreeMap::new();
        self.validate_body(&definition, &signature, &body, &mut calls, &mut reads)?;
        self.plans.insert(
            definition_id,
            DefinitionPlan {
                signature,
                calls,
                external_reads: reads,
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
        if args.vararg.is_some()
            || args.kwarg.is_some()
            || !args.kwonlyargs.is_empty()
            || !args.defaults.is_empty()
            || args.kw_defaults.iter().any(Option::is_some)
        {
            return Err(RegisteredAnalysisError::at(
                "registered source parameters must be required positional parameters",
                self.definition_anchor(&definition),
            ));
        }

        let entry_id = self.registered.entry_definition_id();
        let mut parameters = Vec::new();
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
            let source_type = if is_entry_owner {
                if argument.node.annotation.is_some() {
                    return Err(RegisteredAnalysisError::at(
                        "entry owner receiver must not declare a source ABI type",
                        anchor,
                    ));
                }
                SourceType::EntryOwner
            } else {
                let annotation = argument.node.annotation.as_deref().ok_or_else(|| {
                    RegisteredAnalysisError::at(
                        format!("parameter `{name}` requires an admitted annotation"),
                        anchor,
                    )
                })?;
                self.resolve_annotation(&definition, annotation)?
            };
            parameters.push(TypedParameter::new(name, source_type));
        }
        let returns = returns.as_deref().ok_or_else(|| {
            RegisteredAnalysisError::at(
                "registered source definitions require a return annotation",
                self.definition_anchor(&definition),
            )
        })?;
        let return_type = self.resolve_annotation(&definition, returns)?;
        if definition_id == entry_id
            && (parameters.len() != 2
                || parameters[0].source_type() != &SourceType::EntryOwner
                || parameters[1].source_type() != &SourceType::ExpParams
                || return_type != SourceType::Morphism)
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
    ) -> Result<SourceType, RegisteredAnalysisError> {
        let path = direct_path(annotation).ok_or_else(|| {
            RegisteredAnalysisError::at(
                "annotation must resolve through one direct exact binding",
                self.anchor(definition.module_id(), annotation.location),
            )
        })?;
        let anchor = self.anchor(definition.module_id(), annotation.location);
        self.resolver
            .resolve_annotation(definition.id(), &path, &anchor)
            .map_err(|error| RegisteredAnalysisError::at(error.to_string(), anchor))
    }

    fn validate_body(
        &mut self,
        definition: &RegisteredDefinition,
        signature: &TypeSignature,
        body: &[Stmt],
        calls: &mut BTreeMap<LocationKey, PlannedCall>,
        reads: &mut BTreeMap<LocationKey, ResolvedExternalRead>,
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
        let mut parameter_authorities = signature
            .parameters()
            .iter()
            .map(|parameter| (parameter.name().to_owned(), parameter.source_type().clone()))
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
                        &parameter_authorities,
                        calls,
                        reads,
                    )?;
                    let name = id.to_string();
                    locals.insert(name.clone());
                    parameter_authorities.remove(&name);
                }
                StmtKind::Return {
                    value: Some(value), ..
                } if index + 1 == body.len() => {
                    self.scan_expression(
                        definition,
                        value,
                        &locals,
                        &parameter_authorities,
                        calls,
                        reads,
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
        parameter_authorities: &BTreeMap<String, SourceType>,
        calls: &mut BTreeMap<LocationKey, PlannedCall>,
        reads: &mut BTreeMap<LocationKey, ResolvedExternalRead>,
    ) -> Result<(), RegisteredAnalysisError> {
        match &expression.node {
            ExprKind::Name { .. } | ExprKind::Constant { .. } => Ok(()),
            ExprKind::Subscript { value, slice, .. } => {
                let (params_name, owner_name, attribute) = exp_param_path(value, slice)
                    .ok_or_else(|| {
                        RegisteredAnalysisError::at(
                            "only params[self.<ExpParam>] subscripts are admitted",
                            self.anchor(definition.module_id(), expression.location),
                        )
                    })?;
                if parameter_authorities.get(&params_name) != Some(&SourceType::ExpParams)
                    || parameter_authorities.get(&owner_name) != Some(&SourceType::EntryOwner)
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
                if !matches!(resolved.source_type, SourceType::Bool | SourceType::Int32) {
                    return Err(RegisteredAnalysisError::at(
                        format!(
                            "ExpParam `{}` has unsupported type {}",
                            resolved.name,
                            resolved.source_type.as_str()
                        ),
                        anchor,
                    ));
                }
                let external = ExternalRead::new(
                    resolved.id,
                    resolved.name.clone(),
                    resolved.source_type.clone(),
                    resolved.availability,
                    resolved.value.clone(),
                    anchor,
                );
                if let Some(previous) = self.external_reads.get(&resolved.id)
                    && (previous.source_type() != external.source_type()
                        || previous.availability() != external.availability()
                        || previous.value() != external.value())
                {
                    return Err(RegisteredAnalysisError::at(
                        "one request-local external value resolved inconsistently",
                        external.anchor().clone(),
                    ));
                }
                self.external_reads.entry(resolved.id).or_insert(external);
                reads.insert(LocationKey::from(expression.location), resolved);
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
                    parameter_authorities,
                    calls,
                    reads,
                )?;
                self.scan_expression(
                    definition,
                    right,
                    locals,
                    parameter_authorities,
                    calls,
                    reads,
                )
            }
            ExprKind::Call {
                func,
                args,
                keywords,
            } => {
                if !keywords.is_empty()
                    || args
                        .iter()
                        .any(|argument| matches!(argument.node, ExprKind::Starred { .. }))
                {
                    return Err(RegisteredAnalysisError::at(
                        "argument unpacking and keyword calls are outside the initial source subset",
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
                    parameter_authorities.get(root) == Some(&SourceType::EntryOwner);
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
                        .resolve_callable(definition.id(), &path, bound_entry_owner, &anchor)
                        .map_err(|error| {
                            RegisteredAnalysisError::at(error.to_string(), anchor.clone())
                        })? {
                        ResolvedSourceCallable::Definition { definition_id } => self
                            .plan_registered_call(
                                definition.id(),
                                definition_id,
                                bound_entry_owner,
                                &anchor,
                            )?,
                        ResolvedSourceCallable::Intrinsic(intrinsic) => {
                            PlannedCall::Intrinsic(intrinsic)
                        }
                        ResolvedSourceCallable::HostRpc { display_name } => {
                            return Err(RegisteredAnalysisError::at(
                                format!(
                                    "unimplemented: host RPC calls are not implemented ({display_name})"
                                ),
                                anchor,
                            ));
                        }
                        ResolvedSourceCallable::Unsupported { display_name } => {
                            return Err(RegisteredAnalysisError::at(
                                format!(
                                    "indirect or dynamically selected callable `{display_name}` is unsupported"
                                ),
                                anchor,
                            ));
                        }
                    }
                };
                if calls
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
                        parameter_authorities,
                        calls,
                        reads,
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
        Ok(body)
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

#[derive(Clone)]
struct LocalBinding {
    node_id: u32,
    source_type: SourceType,
    availability: ValueAvailability,
    topology_effect: TopologyEffect,
}

struct LoweredExpression {
    node_id: u32,
    source_type: SourceType,
    availability: ValueAvailability,
    topology_effect: TopologyEffect,
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
            self.locals.insert(
                parameter.name().to_owned(),
                LocalBinding {
                    node_id: u32::MAX,
                    source_type: parameter.source_type().clone(),
                    availability: ValueAvailability::Compile,
                    topology_effect: TopologyEffect::Empty,
                },
            );
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
                let mut target_fact = SemanticFact::new(
                    value.source_type.clone(),
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
                    LocalBinding {
                        node_id: value.node_id,
                        source_type: value.source_type,
                        availability: value.availability,
                        topology_effect: value.topology_effect,
                    },
                );
                let fact =
                    SemanticFact::new(SourceType::Unit, value.availability, value.topology_effect);
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
                    &value.source_type,
                    value.node_id,
                )?;
                self.add_role(
                    value.node_id,
                    if value.source_type == SourceType::Morphism {
                        DependencyRole::Structural
                    } else {
                        DependencyRole::Relocatable
                    },
                );
                let fact =
                    SemanticFact::new(value.source_type, value.availability, value.topology_effect);
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
                let mut fact = SemanticFact::new(
                    binding.source_type.clone(),
                    binding.availability,
                    binding.topology_effect,
                );
                if binding.node_id != u32::MAX {
                    fact.set_resolved_node(binding.node_id);
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
                    source_type: binding.source_type,
                    availability: binding.availability,
                    topology_effect: binding.topology_effect,
                })
            }
            ExprKind::Constant { value, .. } => {
                let (source_type, literal) = match value {
                    Constant::Bool(value) => (SourceType::Bool, SourceLiteral::Bool(*value)),
                    Constant::Int(value) => {
                        let value = i32::try_from(*value).map_err(|_| {
                            RegisteredAnalysisError::at(
                                "integer literal is outside the CatSeq Int32 source profile",
                                self.anchor(expression.location),
                            )
                        })?;
                        (SourceType::Int32, SourceLiteral::Int32(value))
                    }
                    _ => {
                        return Err(RegisteredAnalysisError::at(
                            "unsupported literal in the initial Kernel/Morphism source subset",
                            self.anchor(expression.location),
                        ));
                    }
                };
                let fact = SemanticFact::new(
                    source_type.clone(),
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
                    source_type,
                    availability: ValueAvailability::Compile,
                    topology_effect: TopologyEffect::Empty,
                })
            }
            ExprKind::Subscript { value, slice, .. } => {
                self.lower_exp_param_read(expression, value, slice)
            }
            ExprKind::BinOp {
                left,
                op: Operator::RShift,
                right,
            } => {
                let left = self.lower_expression(left)?;
                let right = self.lower_expression(right)?;
                self.require_type(&SourceType::Morphism, &left.source_type, left.node_id)?;
                self.require_type(&SourceType::Morphism, &right.source_type, right.node_id)?;
                self.add_role(left.node_id, DependencyRole::Structural);
                self.add_role(right.node_id, DependencyRole::Structural);
                let availability = left.availability.max(right.availability);
                let fact =
                    SemanticFact::new(SourceType::Morphism, availability, TopologyEffect::Morphism);
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
                    source_type: SourceType::Morphism,
                    availability,
                    topology_effect: TopologyEffect::Morphism,
                })
            }
            ExprKind::Call { func, args, .. } => self.lower_call(expression, func, args),
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
            .external_reads
            .get(&LocationKey::from(expression.location))
            .expect("every admitted ExpParam read retains its exact resolution");
        let params = self.lower_expression(value)?;
        let owner_binding = self
            .locals
            .get(&owner_name)
            .expect("entry owner parameters are retained")
            .clone();
        let owner_fact = SemanticFact::new(
            SourceType::EntryOwner,
            ValueAvailability::Compile,
            TopologyEffect::Empty,
        );
        let owner = self.push_node(
            SourceHirKind::Name,
            Some(owner_name.clone()),
            None,
            None,
            &[],
            self.anchor(slice.location),
            owner_fact,
        );
        let mut attribute_fact = SemanticFact::new(
            SourceType::ExpParam(Box::new(resolved.source_type.clone())),
            ValueAvailability::Compile,
            TopologyEffect::Empty,
        );
        if owner_binding.node_id != u32::MAX {
            attribute_fact.set_resolved_node(owner_binding.node_id);
        }
        let attribute_node = self.push_node(
            SourceHirKind::Attribute,
            Some(format!("{owner_name}.{attribute}")),
            None,
            None,
            &[owner],
            self.anchor(slice.location),
            attribute_fact,
        );
        let mut fact = SemanticFact::new(
            resolved.source_type.clone(),
            resolved.availability,
            TopologyEffect::Empty,
        );
        fact.set_external_read_id(resolved.id);
        let node_id = self.push_node(
            SourceHirKind::Subscript,
            Some(format!("{params_name}[{owner_name}.{attribute}]")),
            None,
            None,
            &[params.node_id, attribute_node],
            self.anchor(expression.location),
            fact,
        );
        Ok(LoweredExpression {
            node_id,
            source_type: resolved.source_type.clone(),
            availability: resolved.availability,
            topology_effect: TopologyEffect::Empty,
        })
    }

    fn lower_call(
        &mut self,
        expression: &Expr,
        function: &Expr,
        arguments: &[Expr],
    ) -> Result<LoweredExpression, RegisteredAnalysisError> {
        let path = direct_path(function).expect("the discovery pass admitted only direct calls");
        let planned = self
            .plan
            .calls
            .get(&LocationKey::from(expression.location))
            .expect("every admitted call retains exact resolution")
            .clone();
        let callee_fact = SemanticFact::new(
            SourceType::Callable,
            ValueAvailability::Compile,
            TopologyEffect::Empty,
        );
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
        let lowered_arguments = arguments
            .iter()
            .map(|argument| self.lower_expression(argument))
            .collect::<Result<Vec<_>, _>>()?;
        let availability = lowered_arguments
            .iter()
            .map(|argument| argument.availability)
            .max()
            .unwrap_or(ValueAvailability::Compile);
        let (parameter_types, result_type, topology_effect, resolved_call) = match planned {
            PlannedCall::Intrinsic(intrinsic) => {
                let (parameters, result, effect) = match intrinsic {
                    SourceIntrinsic::Cycles => (
                        vec![SourceType::Int32],
                        SourceType::Duration,
                        TopologyEffect::Empty,
                    ),
                    SourceIntrinsic::Identity => (
                        vec![SourceType::Duration],
                        SourceType::Morphism,
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
                (
                    signature
                        .parameters()
                        .iter()
                        .filter(|parameter| {
                            !bound_entry_owner || parameter.source_type() != &SourceType::EntryOwner
                        })
                        .map(|parameter| parameter.source_type().clone())
                        .collect(),
                    signature.return_type().clone(),
                    if signature.return_type() == &SourceType::Morphism {
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
                let parameters = interface
                    .parameters()
                    .iter()
                    .copied()
                    .map(source_type_from_compute)
                    .collect::<Vec<_>>();
                let result = source_type_from_compute(interface.result());
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
        if parameter_types.len() != lowered_arguments.len() {
            return Err(RegisteredAnalysisError::at(
                format!(
                    "call expects {} positional arguments, found {}",
                    parameter_types.len(),
                    lowered_arguments.len()
                ),
                self.anchor(expression.location),
            ));
        }
        for (expected, actual) in parameter_types.iter().zip(&lowered_arguments) {
            self.require_type(expected, &actual.source_type, actual.node_id)?;
            self.add_role(
                actual.node_id,
                if actual.source_type == SourceType::Morphism {
                    DependencyRole::Structural
                } else {
                    DependencyRole::Relocatable
                },
            );
        }
        let mut children = Vec::with_capacity(lowered_arguments.len() + 1);
        children.push(callee);
        children.extend(lowered_arguments.iter().map(|argument| argument.node_id));
        let mut fact = SemanticFact::new(result_type.clone(), availability, topology_effect);
        fact.set_resolved_call(resolved_call);
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
            source_type: result_type,
            availability,
            topology_effect,
        })
    }

    fn require_type(
        &self,
        expected: &SourceType,
        found: &SourceType,
        node_id: u32,
    ) -> Result<(), RegisteredAnalysisError> {
        if expected == found {
            return Ok(());
        }
        Err(RegisteredAnalysisError::at(
            format!(
                "source type mismatch: expected {}, found {}",
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
        mut fact: SemanticFact,
    ) -> u32 {
        let edge_start =
            u32::try_from(self.edges.len()).expect("Source HIR edge count exceeds u32");
        self.edges.extend_from_slice(children);
        let edge_count = u32::try_from(children.len()).expect("Source HIR node arity exceeds u32");
        let node_id = u32::try_from(self.nodes.len()).expect("Source HIR node count exceeds u32");
        fact.add_role(default_role(fact.source_type()));
        self.nodes.push(SourceHirNode::new(
            kind,
            symbol,
            literal,
            composition,
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

fn default_role(source_type: &SourceType) -> DependencyRole {
    if matches!(
        source_type,
        SourceType::Morphism | SourceType::Callable | SourceType::Unit
    ) {
        DependencyRole::Structural
    } else {
        DependencyRole::Relocatable
    }
}

fn source_type_from_compute(compute_type: ComputeType) -> SourceType {
    match compute_type {
        ComputeType::Bool => SourceType::Bool,
        ComputeType::Int32 => SourceType::Int32,
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
