//! NAC3-owned validation of exact registered Compute closures.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::error::Error;
use std::fmt::{Debug, Display, Formatter};
use std::rc::Rc;
use std::sync::Arc;

use nac3ast::{
    Cmpop, Constant, Expr, ExprKind, FileName, Location, Operator, Stmt, StmtKind, StrRef, Unaryop,
};
use nac3core::codegen::CodeGenContext;
use nac3core::symbol_resolver::{SymbolResolver, SymbolValue, ValueEnum};
use nac3core::toplevel::composer::{BuiltinRegistry, SourceProfile, TopLevelComposer};
use nac3core::toplevel::helper::PrimDef;
use nac3core::toplevel::{DefinitionId, TopLevelContext, TopLevelDef};
use nac3core::typecheck::type_inferencer::PrimitiveStore;
use nac3core::typecheck::typedef::{AttrKind, Type, TypeEnum, Unifier, VarMap};
use parking_lot::{Mutex, RwLock};
use sha3::{Digest, Sha3_256};

use crate::registered_modules::{
    RegisteredBuiltin, RegisteredDefinition, RegisteredDefinitionRole, RegisteredKernelModules,
};

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum ComputeType {
    Bool,
    Int32,
}

impl ComputeType {
    const fn abi_name(self) -> &'static str {
        match self {
            Self::Bool => "bool",
            Self::Int32 => "i32",
        }
    }
}

struct CatSeqBuiltinRegistry {
    bindings: HashMap<(FileName, StrRef), PrimDef>,
}

impl CatSeqBuiltinRegistry {
    fn for_reachable(
        registered: &RegisteredKernelModules,
        reachable: &[usize],
    ) -> Result<Self, ComputeValidationError> {
        let mut per_definition = reachable
            .iter()
            .map(|definition_id| (*definition_id, BTreeMap::new()))
            .collect::<BTreeMap<_, BTreeMap<String, RegisteredBuiltin>>>();
        for (definition_id, name, builtin) in registered.builtin_name_bindings() {
            if let Some(bindings) = per_definition.get_mut(&definition_id) {
                bindings.insert(name.to_owned(), builtin);
            }
        }

        let mut authority_by_file = HashMap::<String, BTreeMap<String, RegisteredBuiltin>>::new();
        let mut bindings = HashMap::new();
        for (definition_id, definition_bindings) in per_definition {
            let definition = registered
                .definition(definition_id)
                .expect("reachable Compute ids always remain registered");
            let module = registered
                .modules()
                .iter()
                .find(|module| module.id() == definition.module_id())
                .expect("reachable Compute definitions retain their module");
            if let Some(previous) = authority_by_file.get(module.file_name())
                && previous != &definition_bindings
            {
                return Err(ComputeValidationError::at(
                    format!(
                        "reachable Compute modules share source file {} and cannot retain distinct builtin authority",
                        module.file_name()
                    ),
                    definition_provenance(registered, definition),
                ));
            }
            authority_by_file
                .entry(module.file_name().to_owned())
                .or_insert_with(|| definition_bindings.clone());
            for (name, builtin) in definition_bindings {
                let primitive = match builtin {
                    RegisteredBuiltin::Int32 => PrimDef::Int32,
                    RegisteredBuiltin::Bool => PrimDef::Bool,
                    RegisteredBuiltin::Range => PrimDef::Range,
                };
                bindings.insert(
                    (FileName::from(module.file_name().to_owned()), name.into()),
                    primitive,
                );
            }
        }
        Ok(Self { bindings })
    }
}

impl BuiltinRegistry for CatSeqBuiltinRegistry {
    fn source_profile(&self) -> SourceProfile {
        SourceProfile::CatSeqInt32V1
    }

    fn match_builtin(&self, expression: &Expr) -> Option<PrimDef> {
        let ExprKind::Name { id, .. } = &expression.node else {
            return None;
        };
        self.bindings.get(&(expression.location.file, *id)).copied()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ComputeSourceProvenance {
    module: String,
    file_name: String,
    line: usize,
    column: usize,
}

impl ComputeSourceProvenance {
    pub fn module(&self) -> &str {
        &self.module
    }

    pub fn file_name(&self) -> &str {
        &self.file_name
    }

    pub const fn line(&self) -> usize {
        self.line
    }

    pub const fn column(&self) -> usize {
        self.column
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedComputeInterface {
    definition_id: usize,
    parameters: Vec<ComputeType>,
    result: ComputeType,
    abi_signature: String,
    abi_hash: String,
    provenance: ComputeSourceProvenance,
}

impl ValidatedComputeInterface {
    pub const fn definition_id(&self) -> usize {
        self.definition_id
    }

    pub fn parameters(&self) -> &[ComputeType] {
        &self.parameters
    }

    pub const fn result(&self) -> ComputeType {
        self.result
    }

    pub fn abi_signature(&self) -> &str {
        &self.abi_signature
    }

    pub fn abi_hash(&self) -> &str {
        &self.abi_hash
    }

    pub const fn provenance(&self) -> &ComputeSourceProvenance {
        &self.provenance
    }
}

pub struct ComputeTypedUnit {
    definition_id: usize,
    nac3_definition_id: DefinitionId,
}

impl ComputeTypedUnit {
    pub const fn definition_id(&self) -> usize {
        self.definition_id
    }

    pub const fn nac3_definition_id(&self) -> DefinitionId {
        self.nac3_definition_id
    }
}

pub struct FrozenComputeSourceUnit {
    module_id: usize,
    import_name: String,
    file_name: String,
    source: Arc<str>,
}

impl FrozenComputeSourceUnit {
    pub const fn module_id(&self) -> usize {
        self.module_id
    }

    pub fn import_name(&self) -> &str {
        &self.import_name
    }

    pub fn file_name(&self) -> &str {
        &self.file_name
    }

    pub const fn source(&self) -> &Arc<str> {
        &self.source
    }
}

pub struct ComputeUnitStore {
    source_units: Vec<FrozenComputeSourceUnit>,
    typed_units: Vec<ComputeTypedUnit>,
    top_level_context: Arc<TopLevelContext>,
}

impl ComputeUnitStore {
    pub fn unit_count(&self) -> usize {
        self.typed_units.len()
    }

    pub fn source_unit_count(&self) -> usize {
        self.source_units.len()
    }

    pub fn typed_units(&self) -> &[ComputeTypedUnit] {
        &self.typed_units
    }

    pub fn source_units(&self) -> &[FrozenComputeSourceUnit] {
        &self.source_units
    }

    pub const fn top_level_context(&self) -> &Arc<TopLevelContext> {
        &self.top_level_context
    }
}

impl Debug for ComputeUnitStore {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ComputeUnitStore")
            .field("source_unit_count", &self.source_units.len())
            .field("unit_count", &self.typed_units.len())
            .finish_non_exhaustive()
    }
}

pub struct ComputeValidation {
    interfaces: Vec<ValidatedComputeInterface>,
    unit_store: ComputeUnitStore,
}

impl ComputeValidation {
    pub fn interfaces(&self) -> &[ValidatedComputeInterface] {
        &self.interfaces
    }

    pub fn source_profile_id(&self) -> &'static str {
        self.unit_store
            .top_level_context
            .builtin_registry
            .source_profile()
            .profile_id()
            .expect("Compute validation always retains a stable NAC3 source profile")
    }

    pub const fn unit_store(&self) -> &ComputeUnitStore {
        &self.unit_store
    }
}

impl Debug for ComputeValidation {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ComputeValidation")
            .field("interfaces", &self.interfaces)
            .field("unit_store", &self.unit_store)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ComputeValidationError {
    message: String,
    provenance: Option<ComputeSourceProvenance>,
}

impl ComputeValidationError {
    fn plain(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            provenance: None,
        }
    }

    fn at(message: impl Into<String>, provenance: ComputeSourceProvenance) -> Self {
        Self {
            message: message.into(),
            provenance: Some(provenance),
        }
    }
}

impl Display for ComputeValidationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)?;
        if let Some(provenance) = &self.provenance {
            write!(
                formatter,
                " at {}:{}:{}",
                provenance.file_name, provenance.line, provenance.column
            )?;
        }
        Ok(())
    }
}

impl Error for ComputeValidationError {}

pub fn validate_compute_roots(
    registered: &RegisteredKernelModules,
    root_definition_ids: &[usize],
) -> Result<ComputeValidation, ComputeValidationError> {
    let reachable = compute_reachable_closure(registered, root_definition_ids)?;
    validate_with_nac3(registered, &reachable)
}

fn compute_reachable_closure(
    registered: &RegisteredKernelModules,
    roots: &[usize],
) -> Result<Vec<usize>, ComputeValidationError> {
    let mut complete = HashSet::new();
    let mut active = HashSet::new();
    let mut reachable = Vec::new();
    let mut unique_roots = BTreeSet::new();
    unique_roots.extend(roots.iter().copied());
    for root in unique_roots {
        let definition = registered.definition(root).ok_or_else(|| {
            ComputeValidationError::plain(format!(
                "Compute root id {root} is not registered in this request"
            ))
        })?;
        if definition.role() != RegisteredDefinitionRole::Compute {
            return Err(ComputeValidationError::at(
                format!(
                    "definition {} is not registered as Compute",
                    definition.qualified_name()
                ),
                definition_provenance(registered, definition),
            ));
        }
        visit_compute_definition(registered, root, &mut active, &mut complete, &mut reachable)?;
    }
    Ok(reachable)
}

fn visit_compute_definition(
    registered: &RegisteredKernelModules,
    definition_id: usize,
    active: &mut HashSet<usize>,
    complete: &mut HashSet<usize>,
    reachable: &mut Vec<usize>,
) -> Result<(), ComputeValidationError> {
    if complete.contains(&definition_id) {
        return Ok(());
    }
    active.insert(definition_id);
    let definition = registered
        .definition(definition_id)
        .expect("reachable definition ids were validated before traversal");
    let statement = registered
        .definition_ast(definition_id)
        .expect("registered definitions always retain their exact AST statement");
    let callees = scan_compute_function(registered, definition, statement)?;
    for (callee, call_location) in callees {
        if active.contains(&callee) {
            return Err(ComputeValidationError::at(
                "recursive Compute call is outside the initial Compute profile",
                location_provenance(registered, definition.module_id(), call_location),
            ));
        }
        visit_compute_definition(registered, callee, active, complete, reachable)?;
    }
    active.remove(&definition_id);
    complete.insert(definition_id);
    reachable.push(definition_id);
    Ok(())
}

fn role_name(role: RegisteredDefinitionRole) -> &'static str {
    match role {
        RegisteredDefinitionRole::Kernel => "Kernel",
        RegisteredDefinitionRole::Compute => "Compute",
        RegisteredDefinitionRole::MorphismDefinition => "Morphism",
        RegisteredDefinitionRole::Atomic => "Atomic",
    }
}

fn scan_compute_function(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    statement: &Stmt,
) -> Result<Vec<(usize, Location)>, ComputeValidationError> {
    // This pass owns only exact call closure, purity policy, and static work bounds. It must not
    // infer expression types, assign operator semantics, or rewrite the body accepted by NAC3.
    let StmtKind::FunctionDef {
        args,
        body,
        returns,
        ..
    } = &statement.node
    else {
        return Err(ComputeValidationError::at(
            "Compute registration must resolve to a synchronous function definition",
            definition_provenance(registered, definition),
        ));
    };
    if definition.qualified_name().contains('.') {
        return Err(ComputeValidationError::at(
            "nested or class-owned Compute definitions are not in the initial Compute profile",
            definition_provenance(registered, definition),
        ));
    }
    if args.vararg.is_some()
        || args.kwarg.is_some()
        || !args.kwonlyargs.is_empty()
        || !args.defaults.is_empty()
        || args.kw_defaults.iter().any(Option::is_some)
    {
        return Err(ComputeValidationError::at(
            "Compute parameters must be required positional parameters",
            definition_provenance(registered, definition),
        ));
    }
    for argument in args.posonlyargs.iter().chain(&args.args) {
        validate_annotation_authority(registered, definition, argument.node.annotation.as_deref())?;
    }
    validate_annotation_authority(registered, definition, returns.as_deref())?;
    validate_static_while_blocks(registered, definition, body, &mut BTreeMap::new())?;

    let mut local_names = args
        .posonlyargs
        .iter()
        .chain(&args.args)
        .map(|argument| argument.node.arg.to_string())
        .collect::<HashSet<_>>();
    for child in body {
        collect_local_names(child, &mut local_names);
    }
    let mut callees = Vec::new();
    for child in body {
        scan_statement(registered, definition, child, &local_names, &mut callees)?;
    }
    Ok(callees)
}

fn collect_local_names(statement: &Stmt, local_names: &mut HashSet<String>) {
    match &statement.node {
        StmtKind::Assign { targets, .. } => {
            for target in targets {
                collect_local_target(target, local_names);
            }
        }
        StmtKind::AnnAssign { target, .. } | StmtKind::AugAssign { target, .. } => {
            collect_local_target(target, local_names);
        }
        StmtKind::If { body, orelse, .. } | StmtKind::While { body, orelse, .. } => {
            for child in body.iter().chain(orelse) {
                collect_local_names(child, local_names);
            }
        }
        StmtKind::For {
            target,
            body,
            orelse,
            ..
        } => {
            collect_local_target(target, local_names);
            for child in body.iter().chain(orelse) {
                collect_local_names(child, local_names);
            }
        }
        _ => {}
    }
}

fn collect_local_target(target: &Expr, local_names: &mut HashSet<String>) {
    if let ExprKind::Name { id, .. } = &target.node {
        local_names.insert(id.to_string());
    }
}

fn validate_static_while_blocks(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    statements: &[Stmt],
    known_integer_literals: &mut BTreeMap<String, i128>,
) -> Result<(), ComputeValidationError> {
    for statement in statements {
        match &statement.node {
            StmtKind::If { body, orelse, .. } => {
                validate_static_while_blocks(
                    registered,
                    definition,
                    body,
                    &mut known_integer_literals.clone(),
                )?;
                validate_static_while_blocks(
                    registered,
                    definition,
                    orelse,
                    &mut known_integer_literals.clone(),
                )?;
                forget_assigned_names(statement, known_integer_literals);
            }
            StmtKind::For { body, orelse, .. } => {
                validate_static_while_blocks(
                    registered,
                    definition,
                    body,
                    &mut known_integer_literals.clone(),
                )?;
                validate_static_while_blocks(
                    registered,
                    definition,
                    orelse,
                    &mut known_integer_literals.clone(),
                )?;
                forget_assigned_names(statement, known_integer_literals);
            }
            StmtKind::While {
                test, body, orelse, ..
            } => {
                validate_static_while_contract(
                    registered,
                    definition,
                    statement,
                    test,
                    body,
                    known_integer_literals,
                )?;
                validate_static_while_blocks(
                    registered,
                    definition,
                    body,
                    &mut known_integer_literals.clone(),
                )?;
                validate_static_while_blocks(
                    registered,
                    definition,
                    orelse,
                    &mut known_integer_literals.clone(),
                )?;
                forget_assigned_names(statement, known_integer_literals);
            }
            StmtKind::Assign { targets, value, .. } => {
                let value = integer_literal_value(value);
                for target in targets {
                    update_known_integer_literal(target, value, known_integer_literals);
                }
            }
            StmtKind::AnnAssign { target, value, .. } => {
                update_known_integer_literal(
                    target,
                    value.as_deref().and_then(integer_literal_value),
                    known_integer_literals,
                );
            }
            StmtKind::AugAssign { target, .. } => {
                update_known_integer_literal(target, None, known_integer_literals);
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_static_while_contract(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    statement: &Stmt,
    test: &Expr,
    body: &[Stmt],
    known_integer_literals: &BTreeMap<String, i128>,
) -> Result<(), ComputeValidationError> {
    let Some(condition) = static_while_condition(test) else {
        return Err(static_while_error(registered, definition, statement));
    };
    let Some(initial) = known_integer_literals.get(&condition.counter).copied() else {
        return Err(static_while_error(registered, definition, statement));
    };
    if body.is_empty() {
        return Err(static_while_error(registered, definition, statement));
    }
    let (prefix, update) = body.split_at(body.len() - 1);
    if prefix.iter().any(contains_current_loop_control)
        || prefix
            .iter()
            .any(|child| statement_assigns_name(child, &condition.counter))
    {
        return Err(static_while_error(registered, definition, statement));
    }
    let StmtKind::AugAssign {
        target, op, value, ..
    } = &update[0].node
    else {
        return Err(static_while_error(registered, definition, statement));
    };
    let ExprKind::Name { id, .. } = &target.node else {
        return Err(static_while_error(registered, definition, statement));
    };
    if id.to_string() != condition.counter.as_str() {
        return Err(static_while_error(registered, definition, statement));
    }
    let Some(step) = integer_literal_value(value) else {
        return Err(static_while_error(registered, definition, statement));
    };
    let step = match op {
        Operator::Add => step,
        Operator::Sub => step
            .checked_neg()
            .ok_or_else(|| static_while_error(registered, definition, statement))?,
        _ => return Err(static_while_error(registered, definition, statement)),
    };
    if (condition.direction == WhileDirection::Increasing && step <= 0)
        || (condition.direction == WhileDirection::Decreasing && step >= 0)
        || !static_while_update_stays_in_i32(initial, &condition, step)
    {
        return Err(static_while_error(registered, definition, statement));
    }
    Ok(())
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum WhileDirection {
    Increasing,
    Decreasing,
}

#[derive(Clone)]
struct StaticWhileCondition {
    counter: String,
    direction: WhileDirection,
    bound: i128,
    inclusive: bool,
}

fn static_while_condition(test: &Expr) -> Option<StaticWhileCondition> {
    let ExprKind::Compare {
        left,
        ops,
        comparators,
    } = &test.node
    else {
        return None;
    };
    if ops.len() != 1 || comparators.len() != 1 {
        return None;
    }
    let right = &comparators[0];
    match (&left.node, ops[0], &right.node) {
        (ExprKind::Name { id, .. }, Cmpop::Lt | Cmpop::LtE, _) => Some(StaticWhileCondition {
            counter: id.to_string(),
            direction: WhileDirection::Increasing,
            bound: integer_literal_value(right)?,
            inclusive: ops[0] == Cmpop::LtE,
        }),
        (ExprKind::Name { id, .. }, Cmpop::Gt | Cmpop::GtE, _) => Some(StaticWhileCondition {
            counter: id.to_string(),
            direction: WhileDirection::Decreasing,
            bound: integer_literal_value(right)?,
            inclusive: ops[0] == Cmpop::GtE,
        }),
        (_, Cmpop::Gt | Cmpop::GtE, ExprKind::Name { id, .. }) => Some(StaticWhileCondition {
            counter: id.to_string(),
            direction: WhileDirection::Increasing,
            bound: integer_literal_value(left)?,
            inclusive: ops[0] == Cmpop::GtE,
        }),
        (_, Cmpop::Lt | Cmpop::LtE, ExprKind::Name { id, .. }) => Some(StaticWhileCondition {
            counter: id.to_string(),
            direction: WhileDirection::Decreasing,
            bound: integer_literal_value(left)?,
            inclusive: ops[0] == Cmpop::LtE,
        }),
        _ => None,
    }
}

fn static_while_update_stays_in_i32(
    initial: i128,
    condition: &StaticWhileCondition,
    step: i128,
) -> bool {
    if i32::try_from(initial).is_err()
        || i32::try_from(condition.bound).is_err()
        || i32::try_from(step).is_err()
    {
        return false;
    }
    let (distance, step_magnitude, active) = match condition.direction {
        WhileDirection::Increasing => (
            condition.bound - initial,
            step,
            if condition.inclusive {
                initial <= condition.bound
            } else {
                initial < condition.bound
            },
        ),
        WhileDirection::Decreasing => (
            initial - condition.bound,
            -step,
            if condition.inclusive {
                initial >= condition.bound
            } else {
                initial > condition.bound
            },
        ),
    };
    if !active {
        return true;
    }
    let iterations = if condition.inclusive {
        distance / step_magnitude + 1
    } else {
        (distance + step_magnitude - 1) / step_magnitude
    };
    let displacement = iterations * step;
    i32::try_from(initial + displacement).is_ok()
}

fn contains_current_loop_control(statement: &Stmt) -> bool {
    match &statement.node {
        StmtKind::Break { .. } | StmtKind::Continue { .. } => true,
        StmtKind::If { body, orelse, .. } => {
            body.iter().chain(orelse).any(contains_current_loop_control)
        }
        StmtKind::For { orelse, .. } | StmtKind::While { orelse, .. } => {
            orelse.iter().any(contains_current_loop_control)
        }
        _ => false,
    }
}

fn statement_assigns_name(statement: &Stmt, name: &str) -> bool {
    match &statement.node {
        StmtKind::Assign { targets, .. } => {
            targets.iter().any(|target| target_is_name(target, name))
        }
        StmtKind::AnnAssign { target, .. } | StmtKind::AugAssign { target, .. } => {
            target_is_name(target, name)
        }
        StmtKind::If { body, orelse, .. } | StmtKind::While { body, orelse, .. } => body
            .iter()
            .chain(orelse)
            .any(|child| statement_assigns_name(child, name)),
        StmtKind::For {
            target,
            body,
            orelse,
            ..
        } => {
            target_is_name(target, name)
                || body
                    .iter()
                    .chain(orelse)
                    .any(|child| statement_assigns_name(child, name))
        }
        _ => false,
    }
}

fn target_is_name(target: &Expr, name: &str) -> bool {
    matches!(&target.node, ExprKind::Name { id, .. } if id.to_string() == name)
}

fn update_known_integer_literal(
    target: &Expr,
    value: Option<i128>,
    known_integer_literals: &mut BTreeMap<String, i128>,
) {
    let ExprKind::Name { id, .. } = &target.node else {
        return;
    };
    let name = id.to_string();
    if let Some(value) = value {
        known_integer_literals.insert(name, value);
    } else {
        known_integer_literals.remove(&name);
    }
}

fn forget_assigned_names(statement: &Stmt, known_integer_literals: &mut BTreeMap<String, i128>) {
    let mut assigned = HashSet::new();
    collect_local_names(statement, &mut assigned);
    for name in assigned {
        known_integer_literals.remove(&name);
    }
}

fn static_while_error(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    statement: &Stmt,
) -> ComputeValidationError {
    ComputeValidationError::at(
        "Compute while loops require a literal-initialized counter, a literal bound, and an unconditional monotonic counter update as the final body statement",
        location_provenance(registered, definition.module_id(), statement.location),
    )
}

fn validate_annotation_authority(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    annotation: Option<&Expr>,
) -> Result<(), ComputeValidationError> {
    let Some(Expr {
        node: ExprKind::Name { id, .. },
        location,
        ..
    }) = annotation
    else {
        return Ok(());
    };
    let expected = match id.to_string().as_str() {
        "int" | "int32" => RegisteredBuiltin::Int32,
        "bool" => RegisteredBuiltin::Bool,
        _ => return Ok(()),
    };
    if registered.builtin_name_binding(definition.id(), &id.to_string()) == Some(expected) {
        Ok(())
    } else {
        Err(ComputeValidationError::at(
            format!("Compute ABI builtin `{id}` is shadowed by a module binding"),
            location_provenance(registered, definition.module_id(), *location),
        ))
    }
}

fn scan_statement(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    statement: &Stmt,
    local_names: &HashSet<String>,
    callees: &mut Vec<(usize, Location)>,
) -> Result<(), ComputeValidationError> {
    match &statement.node {
        StmtKind::Return { value, .. } => {
            if let Some(value) = value {
                scan_expression(registered, definition, value, local_names, callees)?;
            }
        }
        StmtKind::Assign { targets, value, .. } => {
            for target in targets {
                validate_local_target(registered, definition, target)?;
            }
            scan_expression(registered, definition, value, local_names, callees)?;
        }
        StmtKind::AnnAssign {
            target,
            annotation,
            value,
            ..
        } => {
            validate_local_target(registered, definition, target)?;
            validate_annotation_authority(registered, definition, Some(annotation))?;
            if let Some(value) = value {
                scan_expression(registered, definition, value, local_names, callees)?;
            }
        }
        StmtKind::AugAssign { target, value, .. } => {
            validate_local_target(registered, definition, target)?;
            scan_expression(registered, definition, value, local_names, callees)?;
        }
        StmtKind::Expr { value, .. } => {
            scan_expression(registered, definition, value, local_names, callees)?;
        }
        StmtKind::If {
            test, body, orelse, ..
        } => {
            scan_expression(registered, definition, test, local_names, callees)?;
            for child in body.iter().chain(orelse) {
                scan_statement(registered, definition, child, local_names, callees)?;
            }
        }
        StmtKind::While {
            test, body, orelse, ..
        } => {
            scan_expression(registered, definition, test, local_names, callees)?;
            for child in body.iter().chain(orelse) {
                scan_statement(registered, definition, child, local_names, callees)?;
            }
        }
        StmtKind::For {
            target,
            iter,
            body,
            orelse,
            ..
        } => {
            validate_local_target(registered, definition, target)?;
            validate_static_range(registered, definition, iter, local_names)?;
            for child in body.iter().chain(orelse) {
                scan_statement(registered, definition, child, local_names, callees)?;
            }
        }
        StmtKind::Pass { .. } | StmtKind::Break { .. } | StmtKind::Continue { .. } => {}
        _ => {
            return Err(ComputeValidationError::at(
                "unsupported or effectful statement in Compute",
                location_provenance(registered, definition.module_id(), statement.location),
            ));
        }
    }
    Ok(())
}

fn validate_static_range(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    iterator: &Expr,
    local_names: &HashSet<String>,
) -> Result<(), ComputeValidationError> {
    let ExprKind::Call {
        func,
        args,
        keywords,
    } = &iterator.node
    else {
        return Err(ComputeValidationError::at(
            "Compute for loops require a statically bounded range of integer literals",
            location_provenance(registered, definition.module_id(), iterator.location),
        ));
    };
    let is_builtin_range = matches!(
        &func.node,
        ExprKind::Name { id, .. }
            if id.to_string() == "range"
                && !local_names.contains("range")
                && registered
                    .resolve_definition_name(definition.module_id(), "range")
                    .is_none()
                && registered.builtin_name_binding(definition.id(), "range")
                    == Some(RegisteredBuiltin::Range)
    );
    if !is_builtin_range {
        let message = if registered.builtin_name_binding(definition.id(), "range")
            != Some(RegisteredBuiltin::Range)
        {
            "Compute builtin `range` is shadowed by a module binding"
        } else {
            "Compute for loops require the builtin statically bounded range"
        };
        return Err(ComputeValidationError::at(
            message,
            location_provenance(registered, definition.module_id(), func.location),
        ));
    }
    if !(1..=3).contains(&args.len())
        || !keywords.is_empty()
        || !args
            .iter()
            .all(|argument| integer_literal_value(argument).is_some())
    {
        return Err(ComputeValidationError::at(
            "Compute for loops require a statically bounded range of integer literals",
            location_provenance(registered, definition.module_id(), iterator.location),
        ));
    }
    if args.len() == 3 && integer_literal_value(&args[2]) == Some(0) {
        return Err(ComputeValidationError::at(
            "Compute range step must not be zero",
            location_provenance(registered, definition.module_id(), args[2].location),
        ));
    }
    Ok(())
}

fn integer_literal_value(expression: &Expr) -> Option<i128> {
    match &expression.node {
        ExprKind::Constant {
            value: Constant::Int(value),
            ..
        } => Some(*value),
        ExprKind::UnaryOp { op, operand } => match op {
            Unaryop::UAdd => integer_literal_value(operand),
            Unaryop::USub => integer_literal_value(operand)?.checked_neg(),
            _ => None,
        },
        _ => None,
    }
}

fn validate_local_target(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    target: &Expr,
) -> Result<(), ComputeValidationError> {
    if matches!(&target.node, ExprKind::Name { .. }) {
        Ok(())
    } else {
        Err(ComputeValidationError::at(
            "Compute assignments may mutate only local scalar names",
            location_provenance(registered, definition.module_id(), target.location),
        ))
    }
}

fn scan_expression(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
    expression: &Expr,
    local_names: &HashSet<String>,
    callees: &mut Vec<(usize, Location)>,
) -> Result<(), ComputeValidationError> {
    let mut children = Vec::new();
    match &expression.node {
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            let Some((root_name, binding_name)) = direct_callee_binding(func) else {
                return Err(ComputeValidationError::at(
                    "dynamic Compute callees are unsupported",
                    location_provenance(registered, definition.module_id(), func.location),
                ));
            };
            if local_names.contains(&root_name) {
                return Err(ComputeValidationError::at(
                    format!(
                        "Host RPC or dynamic callee {binding_name} is unsupported from Compute"
                    ),
                    location_provenance(registered, definition.module_id(), func.location),
                ));
            }
            let Some(callee_id) =
                registered.resolve_definition_name(definition.module_id(), &binding_name)
            else {
                return Err(ComputeValidationError::at(
                    format!(
                        "Host RPC or dynamic callee {binding_name} is unsupported from Compute"
                    ),
                    location_provenance(registered, definition.module_id(), func.location),
                ));
            };
            let callee = registered
                .definition(callee_id)
                .expect("Compute binding definition ids were validated before closure traversal");
            if callee.role() != RegisteredDefinitionRole::Compute {
                return Err(ComputeValidationError::at(
                    format!(
                        "Compute cannot call {} definition {}",
                        role_name(callee.role()),
                        callee.qualified_name()
                    ),
                    location_provenance(registered, definition.module_id(), func.location),
                ));
            }
            callees.push((callee_id, func.location));
            children.extend(args.iter());
            for keyword in keywords {
                if keyword.node.arg.is_none() {
                    return Err(ComputeValidationError::at(
                        "dynamic keyword unpacking is unsupported in Compute calls",
                        location_provenance(registered, definition.module_id(), keyword.location),
                    ));
                }
                children.push(keyword.node.value.as_ref());
            }
        }
        ExprKind::BinOp { left, right, .. } => {
            children.extend([left.as_ref(), right.as_ref()]);
        }
        ExprKind::BoolOp { values, .. } => children.extend(values),
        ExprKind::UnaryOp { operand, .. } => children.push(operand),
        ExprKind::IfExp { test, body, orelse } => {
            children.extend([test.as_ref(), body.as_ref(), orelse.as_ref()]);
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            children.push(left);
            children.extend(comparators);
        }
        ExprKind::Name { id, .. } if local_names.contains(&id.to_string()) => {}
        ExprKind::Name { id, .. } => {
            let message = if registered
                .resolve_definition_name(definition.module_id(), &id.to_string())
                .is_some()
            {
                format!("registered definition `{id}` cannot be used as a first-class value")
            } else {
                format!("ambient Compute value `{id}` is unsupported")
            };
            return Err(ComputeValidationError::at(
                message,
                location_provenance(registered, definition.module_id(), expression.location),
            ));
        }
        ExprKind::Constant { .. } => {}
        _ => {
            return Err(ComputeValidationError::at(
                "unsupported expression in the initial pure scalar Compute profile",
                location_provenance(registered, definition.module_id(), expression.location),
            ));
        }
    }
    for child in children {
        scan_expression(registered, definition, child, local_names, callees)?;
    }
    Ok(())
}

fn direct_callee_binding(function: &Expr) -> Option<(String, String)> {
    match &function.node {
        ExprKind::Name { id, .. } => {
            let name = id.to_string();
            Some((name.clone(), name))
        }
        ExprKind::Attribute { value, attr, .. } => {
            let ExprKind::Name { id, .. } = &value.node else {
                return None;
            };
            let root = id.to_string();
            Some((root.clone(), format!("{root}.{attr}")))
        }
        _ => None,
    }
}

#[derive(Default)]
struct ComputeResolverState {
    definition_ids: Mutex<HashMap<StrRef, DefinitionId>>,
    types: Mutex<HashMap<StrRef, Type>>,
    strings: Mutex<HashMap<String, i32>>,
}

#[derive(Clone)]
struct ComputeResolver(Arc<ComputeResolverState>);

impl ComputeResolverState {
    fn bind(&self, name: &str, definition_id: DefinitionId, ty: Type) {
        self.definition_ids
            .lock()
            .insert(name.into(), definition_id);
        self.types.lock().insert(name.into(), ty);
    }
}

impl SymbolResolver for ComputeResolver {
    fn get_default_param_value(&self, _: &Expr) -> anyhow::Result<Option<SymbolValue>> {
        Ok(None)
    }

    fn get_symbol_type(
        &self,
        _: &mut Unifier,
        _: &[Arc<RwLock<TopLevelDef>>],
        _: &PrimitiveStore,
        name: StrRef,
    ) -> anyhow::Result<Type> {
        self.0
            .types
            .lock()
            .get(&name)
            .copied()
            .ok_or_else(|| anyhow::anyhow!("unsupported ambient Compute value `{name}`"))
    }

    fn get_symbol_value<'ctx>(
        &self,
        name: StrRef,
        _: &mut CodeGenContext<'ctx, '_>,
    ) -> anyhow::Result<Option<ValueEnum<'ctx>>> {
        Err(anyhow::anyhow!(
            "Compute validation has no runtime value for `{name}`"
        ))
    }

    fn get_identifier_def(&self, name: StrRef) -> Result<DefinitionId, Vec<anyhow::Error>> {
        self.0
            .definition_ids
            .lock()
            .get(&name)
            .copied()
            .ok_or_else(|| vec![anyhow::anyhow!("unsupported Compute identifier `{name}`")])
    }

    fn get_string_id(&self, value: &str) -> i32 {
        let mut strings = self.0.strings.lock();
        let next = i32::try_from(strings.len()).expect("NAC3 string table exceeds i32 capacity");
        *strings.entry(value.to_owned()).or_insert(next)
    }

    fn get_exception_id(&self, _: usize) -> usize {
        unreachable!("exceptions are rejected by the initial Compute profile")
    }
}

fn validate_with_nac3(
    registered: &RegisteredKernelModules,
    reachable: &[usize],
) -> Result<ComputeValidation, ComputeValidationError> {
    let builtin_registry = Arc::new(CatSeqBuiltinRegistry::for_reachable(registered, reachable)?);
    let source_profile_id = builtin_registry
        .source_profile()
        .profile_id()
        .expect("CatSeqInt32V1 has a stable profile identity");
    let (mut composer, _, _) = TopLevelComposer::new(Vec::new(), Vec::new(), builtin_registry, 32);
    let mut module_resolvers = HashMap::<usize, Arc<ComputeResolverState>>::new();
    let mut nac3_definitions = BTreeMap::<usize, (DefinitionId, Type)>::new();

    for definition_id in reachable {
        let definition = registered
            .definition(*definition_id)
            .expect("reachable Compute ids always remain registered");
        let module = registered
            .modules()
            .iter()
            .find(|module| module.id() == definition.module_id())
            .expect("registered definitions always refer to a retained module");
        let resolver_state = module_resolvers
            .entry(module.id())
            .or_insert_with(|| Arc::new(ComputeResolverState::default()))
            .clone();
        let resolver = Arc::new(ComputeResolver(resolver_state.clone()))
            as Arc<dyn SymbolResolver + Send + Sync>;
        let mut statement = registered
            .definition_ast(*definition_id)
            .expect("reachable Compute ids always retain an AST")
            .clone();
        let StmtKind::FunctionDef {
            name,
            decorator_list,
            ..
        } = &mut statement.node
        else {
            unreachable!("Compute shape was checked before NAC3 validation")
        };
        decorator_list.clear();
        let source_name = name.to_string();
        let analysis_module_name = format!("__catseq_module_{}", module.id());
        let (_, nac3_definition_id, ty) = composer
            .register_top_level(statement, Some(resolver), &analysis_module_name, true)
            .map_err(|error| {
                ComputeValidationError::at(error, definition_provenance(registered, definition))
            })?;
        let ty = ty.expect("registered Compute functions always have function types");
        resolver_state.bind(&source_name, nac3_definition_id, ty);
        nac3_definitions.insert(*definition_id, (nac3_definition_id, ty));
    }

    for (module_id, name, registered_definition_id) in registered.definition_name_bindings() {
        let Some((definition_id, ty)) = nac3_definitions.get(&registered_definition_id) else {
            continue;
        };
        let Some(resolver) = module_resolvers.get(&module_id) else {
            continue;
        };
        resolver.bind(name, *definition_id, *ty);
    }

    let mut imported_module_members =
        BTreeMap::<(usize, String), BTreeMap<String, (DefinitionId, Type)>>::new();
    for (caller_module_id, binding_name, registered_definition_id) in
        registered.definition_name_bindings()
    {
        let Some((root_name, attribute_name)) = binding_name.split_once('.') else {
            continue;
        };
        if attribute_name.contains('.') || !module_resolvers.contains_key(&caller_module_id) {
            continue;
        }
        let Some((nac3_definition_id, ty)) = nac3_definitions.get(&registered_definition_id) else {
            continue;
        };
        let root_key = (caller_module_id, root_name.to_owned());
        imported_module_members
            .entry(root_key)
            .or_default()
            .insert(attribute_name.to_owned(), (*nac3_definition_id, *ty));
    }

    for ((caller_module_id, root_name), members) in imported_module_members {
        let resolver_state = Arc::new(ComputeResolverState::default());
        for (name, (definition_id, ty)) in &members {
            resolver_state.bind(name, *definition_id, *ty);
        }
        let resolver =
            Arc::new(ComputeResolver(resolver_state)) as Arc<dyn SymbolResolver + Send + Sync>;
        let member_names = Rc::new(
            members
                .keys()
                .map(|name| (name.as_str().into(), 0))
                .collect(),
        );
        let analysis_name = format!("__catseq_compute_namespace_{caller_module_id}_{root_name}");
        let module_definition_id = composer
            .register_top_level_module(&analysis_name, &member_names, resolver, None)
            .map_err(ComputeValidationError::plain)?;
        let module_type = composer.unifier.add_ty(TypeEnum::TObj {
            obj_id: module_definition_id,
            fields: members
                .into_iter()
                .map(|(name, (_, ty))| (name.into(), (ty, AttrKind::Method)))
                .collect(),
            params: VarMap::new(),
        });
        let resolver = module_resolvers
            .get(&caller_module_id)
            .expect("module roots are collected only for reachable caller modules");
        resolver.bind(&root_name, module_definition_id, module_type);
    }

    composer.start_analysis(true).map_err(|errors| {
        ComputeValidationError::plain(
            errors
                .into_iter()
                .map(|error| error.to_string())
                .collect::<Vec<_>>()
                .join("\n"),
        )
    })?;

    let mut interfaces = Vec::with_capacity(reachable.len());
    for definition_id in reachable {
        let definition = registered
            .definition(*definition_id)
            .expect("reachable Compute ids always remain registered");
        let (nac3_definition_id, _) = nac3_definitions[definition_id];
        let signature_type = {
            let nac3_definition = composer.definition_ast_list[nac3_definition_id.0].0.read();
            let TopLevelDef::Function { signature, .. } = &*nac3_definition else {
                unreachable!("registered Compute definitions are NAC3 functions")
            };
            *signature
        };
        let TypeEnum::TFunc(signature) = composer.unifier.get_ty(signature_type).as_ref().clone()
        else {
            unreachable!("registered Compute definitions retain function signatures")
        };
        let parameters = signature
            .args
            .iter()
            .map(|argument| {
                compute_type(
                    &mut composer.unifier,
                    &composer.primitives_ty,
                    argument.ty,
                    registered,
                    definition,
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
        let result = compute_type(
            &mut composer.unifier,
            &composer.primitives_ty,
            signature.ret,
            registered,
            definition,
        )?;
        let abi_signature = format!(
            "({})->{}",
            parameters
                .iter()
                .map(|parameter| parameter.abi_name())
                .collect::<Vec<_>>()
                .join(","),
            result.abi_name()
        );
        let mut abi_identity = Sha3_256::new();
        abi_identity.update(b"catseq-compute-abi\0");
        abi_identity.update(source_profile_id.as_bytes());
        abi_identity.update(b"\0");
        abi_identity.update(abi_signature.as_bytes());
        let abi_hash = abi_identity
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        interfaces.push(ValidatedComputeInterface {
            definition_id: *definition_id,
            parameters,
            result,
            abi_signature,
            abi_hash,
            provenance: definition_provenance(registered, definition),
        });
    }

    let source_module_ids = reachable
        .iter()
        .map(|definition_id| {
            registered
                .definition(*definition_id)
                .expect("reachable Compute ids always remain registered")
                .module_id()
        })
        .collect::<BTreeSet<_>>();
    let source_units = registered
        .modules()
        .iter()
        .filter(|module| source_module_ids.contains(&module.id()))
        .map(|module| FrozenComputeSourceUnit {
            module_id: module.id(),
            import_name: module.import_name().to_owned(),
            file_name: module.file_name().to_owned(),
            source: module.source().clone(),
        })
        .collect();
    let typed_units = reachable
        .iter()
        .map(|definition_id| ComputeTypedUnit {
            definition_id: *definition_id,
            nac3_definition_id: nac3_definitions[definition_id].0,
        })
        .collect();
    let top_level_context = Arc::new(composer.make_top_level_context());

    Ok(ComputeValidation {
        interfaces,
        unit_store: ComputeUnitStore {
            source_units,
            typed_units,
            top_level_context,
        },
    })
}

fn compute_type(
    unifier: &mut Unifier,
    primitives: &PrimitiveStore,
    ty: Type,
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
) -> Result<ComputeType, ComputeValidationError> {
    let ty = unifier.get_representative(ty);
    if ty == unifier.get_representative(primitives.int32) {
        Ok(ComputeType::Int32)
    } else if ty == unifier.get_representative(primitives.bool) {
        Ok(ComputeType::Bool)
    } else if ty == unifier.get_representative(primitives.float) {
        Err(ComputeValidationError::at(
            "floating-point types and operations are unsupported in Compute",
            definition_provenance(registered, definition),
        ))
    } else {
        Err(ComputeValidationError::at(
            "NAC3 inferred a type outside the initial Compute ABI profile",
            definition_provenance(registered, definition),
        ))
    }
}

fn definition_provenance(
    registered: &RegisteredKernelModules,
    definition: &RegisteredDefinition,
) -> ComputeSourceProvenance {
    location_provenance(registered, definition.module_id(), definition.location())
}

fn location_provenance(
    registered: &RegisteredKernelModules,
    module_id: usize,
    location: Location,
) -> ComputeSourceProvenance {
    let module = registered
        .modules()
        .iter()
        .find(|module| module.id() == module_id)
        .expect("registered source locations always have an owning module");
    ComputeSourceProvenance {
        module: module.import_name().to_owned(),
        file_name: module.file_name().to_owned(),
        line: location.row,
        column: location.column,
    }
}
