//! Typed declaration surface produced from NAC3's Python AST.
//!
//! This module is the first production seam of the 0.3 source frontend.  It
//! deliberately owns CatSeq types instead of leaking NAC3 AST nodes past the
//! parsing/indexing boundary.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::error::Error;
use std::fmt::{Display, Formatter};

use nac3ast::{Arg, Arguments, Expr, ExprKind, FileName, Stmt, StmtKind};
use serde::{Deserialize, Serialize};

use crate::intrinsics;
use crate::source_hir::{TypedSourceHir, lower_definition_hir};

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum SourceType {
    Unit,
    Bool,
    Int64,
    Float64,
    Duration,
    String,
    Morphism,
    MorphismTemplate,
    AtomicOp,
    Board,
    Channel,
    ScanBindings,
    ScanParam(Box<SourceType>),
    ChannelBindings,
    FixedAggregate,
    Optional(Box<SourceType>),
    Instance(String),
    NativeRecord(String),
}

impl Display for SourceType {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unit => formatter.write_str("Unit"),
            Self::Bool => formatter.write_str("Bool"),
            Self::Int64 => formatter.write_str("Int64"),
            Self::Float64 => formatter.write_str("Float64"),
            Self::Duration => formatter.write_str("Duration"),
            Self::String => formatter.write_str("String"),
            Self::Morphism => formatter.write_str("Morphism"),
            Self::MorphismTemplate => formatter.write_str("MorphismTemplate"),
            Self::AtomicOp => formatter.write_str("AtomicOp"),
            Self::Board => formatter.write_str("Board"),
            Self::Channel => formatter.write_str("Channel"),
            Self::ScanBindings => formatter.write_str("ScanBindings"),
            Self::ScanParam(inner) => write!(formatter, "ScanParam<{inner}>"),
            Self::ChannelBindings => formatter.write_str("ChannelBindings"),
            Self::FixedAggregate => formatter.write_str("FixedAggregate"),
            Self::Optional(inner) => write!(formatter, "Optional<{inner}>"),
            Self::Instance(schema) => write!(formatter, "Instance<{schema}>"),
            Self::NativeRecord(schema) => write!(formatter, "NativeRecord<{schema}>"),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypedParameter {
    name: String,
    source_type: SourceType,
}

impl TypedParameter {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn source_type(&self) -> &SourceType {
        &self.source_type
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypeSignature {
    parameters: Vec<TypedParameter>,
    return_type: SourceType,
}

impl TypeSignature {
    pub fn parameters(&self) -> &[TypedParameter] {
        &self.parameters
    }

    pub fn return_type(&self) -> &SourceType {
        &self.return_type
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypedDefinition {
    module: String,
    qualified_name: String,
    signature: TypeSignature,
    hir: TypedSourceHir,
}

impl TypedDefinition {
    pub fn module(&self) -> &str {
        &self.module
    }

    pub fn qualified_name(&self) -> &str {
        &self.qualified_name
    }

    pub fn signature(&self) -> &TypeSignature {
        &self.signature
    }

    pub fn hir(&self) -> &TypedSourceHir {
        &self.hir
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct IncrementalStats {
    executed: u64,
    green: u64,
    red: u64,
    result_cache_loads: u64,
    bytes_read: u64,
    bytes_written: u64,
    fingerprint_nanos: u64,
    executed_by_kind: BTreeMap<String, u64>,
}

pub(crate) struct IncrementalStatsSnapshot {
    pub executed: u64,
    pub green: u64,
    pub red: u64,
    pub result_cache_loads: u64,
    pub bytes_read: u64,
    pub bytes_written: u64,
    pub fingerprint_nanos: u64,
    pub executed_by_kind: BTreeMap<String, u64>,
}

impl IncrementalStats {
    pub(crate) fn new(executed: u64, green: u64) -> Self {
        Self {
            executed,
            green,
            ..Self::default()
        }
    }

    pub(crate) fn from_snapshot(snapshot: IncrementalStatsSnapshot) -> Self {
        Self {
            executed: snapshot.executed,
            green: snapshot.green,
            red: snapshot.red,
            result_cache_loads: snapshot.result_cache_loads,
            bytes_read: snapshot.bytes_read,
            bytes_written: snapshot.bytes_written,
            fingerprint_nanos: snapshot.fingerprint_nanos,
            executed_by_kind: snapshot.executed_by_kind,
        }
    }

    pub const fn executed(&self) -> u64 {
        self.executed
    }

    pub const fn green(&self) -> u64 {
        self.green
    }

    pub const fn red(&self) -> u64 {
        self.red
    }

    pub const fn result_cache_loads(&self) -> u64 {
        self.result_cache_loads
    }

    pub const fn bytes_read(&self) -> u64 {
        self.bytes_read
    }

    pub const fn bytes_written(&self) -> u64 {
        self.bytes_written
    }

    pub const fn fingerprint_nanos(&self) -> u64 {
        self.fingerprint_nanos
    }

    pub fn executed_by_kind(&self) -> &BTreeMap<String, u64> {
        &self.executed_by_kind
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedCheckReport {
    entry: String,
    definitions: Vec<TypedDefinition>,
    diagnostics: Vec<String>,
    queried_modules: Vec<String>,
    incremental: IncrementalStats,
}

impl TypedCheckReport {
    pub const fn schema_version(&self) -> u32 {
        1
    }

    pub fn entry(&self) -> &str {
        &self.entry
    }

    pub fn definitions(&self) -> &[TypedDefinition] {
        &self.definitions
    }

    pub fn diagnostics(&self) -> &[String] {
        &self.diagnostics
    }

    pub fn queried_modules(&self) -> &[String] {
        &self.queried_modules
    }

    pub const fn incremental(&self) -> &IncrementalStats {
        &self.incremental
    }

    pub(crate) fn with_incremental(mut self, incremental: IncrementalStats) -> Self {
        self.incremental = incremental;
        self
    }

    pub(crate) fn from_cached(
        entry: String,
        definitions: Vec<TypedDefinition>,
        diagnostics: Vec<String>,
        queried_modules: Vec<String>,
        incremental: IncrementalStats,
    ) -> Self {
        Self {
            entry,
            definitions,
            diagnostics,
            queried_modules,
            incremental,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedCheckError {
    Parse {
        file_name: String,
        message: String,
    },
    EntryNotFound {
        file_name: String,
        entry: String,
    },
    MissingAnnotation {
        file_name: String,
        definition: String,
        parameter: String,
    },
    UnsupportedAnnotation {
        file_name: String,
        definition: String,
        annotation: String,
    },
    UnsupportedStatement {
        file_name: String,
        definition: String,
        statement: String,
        line: usize,
        column: usize,
    },
    TypeMismatch {
        file_name: String,
        definition: String,
        expected: Box<SourceType>,
        found: Box<SourceType>,
        line: usize,
        column: usize,
    },
    MigrationRequired {
        file_name: String,
        definition: String,
        construct: String,
    },
    LinkControlledTopology {
        file_name: String,
        definition: String,
        line: usize,
        column: usize,
    },
    SourceLoad {
        module: String,
        message: String,
    },
    ReachableHostCall {
        file_name: String,
        definition: String,
        target: String,
        line: usize,
        column: usize,
    },
}

impl Display for TypedCheckError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Parse { file_name, message } => {
                write!(formatter, "Python syntax error in {file_name}: {message}")
            }
            Self::EntryNotFound { file_name, entry } => {
                write!(
                    formatter,
                    "sequence entry {entry:?} not found in {file_name}"
                )
            }
            Self::MissingAnnotation {
                file_name,
                definition,
                parameter,
            } => write!(
                formatter,
                "parameter {parameter:?} of {definition} in {file_name} needs a CatSeq type annotation"
            ),
            Self::UnsupportedAnnotation {
                file_name,
                definition,
                annotation,
            } => write!(
                formatter,
                "unsupported CatSeq type annotation {annotation:?} on {definition} in {file_name}"
            ),
            Self::UnsupportedStatement {
                file_name,
                definition,
                statement,
                line,
                column,
            } => write!(
                formatter,
                "unsupported reachable {statement} statement in {definition} at {file_name}:{line}:{column}"
            ),
            Self::TypeMismatch {
                file_name,
                definition,
                expected,
                found,
                line,
                column,
            } => write!(
                formatter,
                "type mismatch in {definition} at {file_name}:{line}:{column}: expected {expected}, found {found}"
            ),
            Self::MigrationRequired {
                file_name,
                definition,
                construct,
            } => write!(
                formatter,
                "{construct} in {definition} ({file_name}) must be migrated to implicit Morphism state flow"
            ),
            Self::LinkControlledTopology {
                file_name,
                definition,
                line,
                column,
            } => write!(
                formatter,
                "Link value has a Structural dependency role in {definition} at {file_name}:{line}:{column}"
            ),
            Self::SourceLoad { module, message } => {
                write!(formatter, "cannot load source module {module}: {message}")
            }
            Self::ReachableHostCall {
                file_name,
                definition,
                target,
                line,
                column,
            } => write!(
                formatter,
                "reachable Host call {target} in {definition} at {file_name}:{line}:{column} is outside the CatSeq source language"
            ),
        }
    }
}

impl Error for TypedCheckError {}

pub fn check_typed_entry(
    file_name: &str,
    source: &str,
    requested_entry: &str,
) -> Result<TypedCheckReport, TypedCheckError> {
    let modules = BTreeMap::from([(file_name.to_owned(), source.to_owned())]);
    check_typed_bundle_entry(file_name, &modules, requested_entry)
}

pub fn check_typed_bundle_entry(
    entry_module: &str,
    modules: &BTreeMap<String, String>,
    requested_entry: &str,
) -> Result<TypedCheckReport, TypedCheckError> {
    let mut loader = |module: &str| Ok(modules.get(module).cloned());
    check_typed_bundle_entry_with_loader(entry_module, requested_entry, &mut loader)
}

pub fn check_typed_bundle_entry_with_loader<F>(
    entry_module: &str,
    requested_entry: &str,
    loader: &mut F,
) -> Result<TypedCheckReport, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let mut pending = VecDeque::from([(entry_module.to_owned(), requested_entry.to_owned())]);
    let mut visited = HashSet::new();
    let mut parsed = HashMap::new();
    let mut sources = HashMap::<String, String>::new();
    let mut definitions = Vec::new();

    while let Some((module_name, lexical_name)) = pending.pop_front() {
        if !visited.insert((module_name.clone(), lexical_name.clone())) {
            continue;
        }
        if !load_source_module(&module_name, &mut sources, loader)? {
            return Err(TypedCheckError::EntryNotFound {
                file_name: module_name.clone(),
                entry: lexical_name.clone(),
            });
        }
        if !parsed.contains_key(&module_name) {
            let source = &sources[&module_name];
            parsed.insert(module_name.clone(), parse_module(&module_name, source)?);
        }
        let suite = &parsed[&module_name];
        let imports = module_imports(&module_name, suite);
        let mut analysis =
            find_definition(&module_name, suite, &mut Vec::new(), &lexical_name, None)?
                .ok_or_else(|| TypedCheckError::EntryNotFound {
                    file_name: module_name.clone(),
                    entry: lexical_name.clone(),
                })?;

        if module_name != entry_module || lexical_name != requested_entry {
            analysis.definition.qualified_name = format!("{module_name}.{lexical_name}");
        }
        for source_call in analysis.calls {
            let call = resolve_self_call(&lexical_name, &source_call);
            let resolved = resolve_call_path(&module_name, &imports, &call);
            let resolved =
                resolve_compile_instance_call(&mut sources, &mut parsed, loader, &resolved)?;
            analysis
                .definition
                .hir
                .resolve_call(&source_call, &resolved);
            if resolved == "rb1system.utils.get_end_state" {
                return Err(TypedCheckError::MigrationRequired {
                    file_name: module_name,
                    definition: lexical_name,
                    construct: "get_end_state".to_owned(),
                });
            }
            if intrinsics::is_compiler_special_form(&resolved) {
                continue;
            }
            if let Some((target_module, target_definition)) =
                locate_source_definition(&resolved, &mut sources, loader)?
            {
                if !parsed.contains_key(&target_module) {
                    let source = &sources[&target_module];
                    parsed.insert(target_module.clone(), parse_module(&target_module, source)?);
                }
                if definition_exists(&parsed[&target_module], &target_definition) {
                    pending.push_back((target_module, target_definition));
                    continue;
                }
            }
            if intrinsics::is_registered(&resolved) {
                continue;
            }
            let anchor = analysis
                .definition
                .hir
                .call_anchor(&source_call)
                .expect("a collected call must have a Source HIR node");
            return Err(TypedCheckError::ReachableHostCall {
                file_name: module_name,
                definition: lexical_name,
                target: resolved,
                line: anchor.line(),
                column: anchor.column(),
            });
        }
        definitions.push(analysis.definition);
    }

    let return_types: HashMap<_, _> = definitions
        .iter()
        .map(|definition| {
            (
                format!("{}.{}", definition.module, definition.hir.definition()),
                definition.signature.return_type.clone(),
            )
        })
        .collect();
    for definition in &mut definitions {
        definition.hir.apply_definition_signatures(&return_types);
    }
    let executed = parsed.len() as u64 + definitions.len() as u64;
    let mut queried_modules: Vec<_> = parsed.into_keys().collect();
    queried_modules.sort();
    Ok(TypedCheckReport {
        entry: requested_entry.to_owned(),
        incremental: IncrementalStats::new(executed, 0),
        definitions,
        diagnostics: Vec::new(),
        queried_modules,
    })
}

fn definition_exists(statements: &[Stmt], requested: &str) -> bool {
    let mut pending = vec![(statements, Vec::<String>::new())];
    while let Some((statements, scope)) = pending.pop() {
        for statement in statements {
            match &statement.node {
                StmtKind::ClassDef { name, body, .. } => {
                    let mut nested = scope.clone();
                    nested.push(name.to_string());
                    pending.push((body, nested));
                }
                StmtKind::FunctionDef { name, .. } => {
                    let mut qualified = scope.clone();
                    qualified.push(name.to_string());
                    if qualified.join(".") == requested {
                        return true;
                    }
                }
                _ => {}
            }
        }
    }
    false
}

fn parse_module(file_name: &str, source: &str) -> Result<Vec<Stmt>, TypedCheckError> {
    nac3parser::parser::parse_program(source, FileName::from(file_name.to_owned())).map_err(
        |error| TypedCheckError::Parse {
            file_name: file_name.to_owned(),
            message: error.to_string(),
        },
    )
}

struct DefinitionAnalysis {
    definition: TypedDefinition,
    calls: Vec<String>,
}

#[derive(Default)]
struct ClassFields {
    types: HashMap<String, SourceType>,
    values: HashMap<String, String>,
}

fn find_definition(
    file_name: &str,
    statements: &[Stmt],
    scope: &mut Vec<String>,
    requested: &str,
    class_context: Option<&ClassFields>,
) -> Result<Option<DefinitionAnalysis>, TypedCheckError> {
    for statement in statements {
        match &statement.node {
            StmtKind::ClassDef { name, body, .. } => {
                scope.push(name.to_string());
                let fields = class_fields(body);
                let found = find_definition(file_name, body, scope, requested, Some(&fields))?;
                scope.pop();
                if found.is_some() {
                    return Ok(found);
                }
            }
            StmtKind::FunctionDef {
                name,
                args,
                body,
                returns,
                ..
            } => {
                let mut qualified = scope.clone();
                qualified.push(name.to_string());
                let qualified_name = qualified.join(".");
                if qualified_name != requested {
                    continue;
                }
                validate_restricted_statements(file_name, &qualified_name, body)?;
                let mut signature = signature(
                    file_name,
                    &qualified_name,
                    scope.last().map(String::as_str),
                    args,
                    body,
                    returns.as_deref(),
                )?;
                let erased_state_names = legacy_state_bindings(body);
                let hir = lower_definition_hir(
                    file_name,
                    &qualified_name,
                    body,
                    &signature,
                    class_context.map_or(&HashMap::new(), |fields| &fields.types),
                    class_context.map_or(&HashMap::new(), |fields| &fields.values),
                    &erased_state_names,
                );
                if returns.is_none() {
                    if let Some(inferred) = hir.inferred_return_type() {
                        signature.return_type = inferred;
                    }
                }
                if let Some(anchor) = hir.first_link_structural_use() {
                    return Err(TypedCheckError::LinkControlledTopology {
                        file_name: file_name.to_owned(),
                        definition: qualified_name,
                        line: anchor.line(),
                        column: anchor.column(),
                    });
                }
                if returns.is_some()
                    && let Some((anchor, found)) =
                        hir.first_return_type_mismatch(signature.return_type())
                {
                    return Err(TypedCheckError::TypeMismatch {
                        file_name: file_name.to_owned(),
                        definition: qualified_name,
                        expected: Box::new(signature.return_type().clone()),
                        found: Box::new(found.clone()),
                        line: anchor.line(),
                        column: anchor.column(),
                    });
                }
                return Ok(Some(DefinitionAnalysis {
                    definition: TypedDefinition {
                        module: file_name.to_owned(),
                        signature,
                        qualified_name,
                        hir,
                    },
                    calls: calls_in_statements(body, &erased_state_names),
                }));
            }
            _ => {}
        }
    }
    Ok(None)
}

fn validate_restricted_statements(
    file_name: &str,
    definition: &str,
    body: &[Stmt],
) -> Result<(), TypedCheckError> {
    let mut pending: Vec<_> = body.iter().rev().collect();
    while let Some(statement) = pending.pop() {
        match &statement.node {
            StmtKind::Return { .. }
            | StmtKind::Assign { .. }
            | StmtKind::AugAssign { .. }
            | StmtKind::AnnAssign { .. }
            | StmtKind::Expr { .. }
            | StmtKind::Pass { .. } => {}
            StmtKind::If { body, orelse, .. } | StmtKind::For { body, orelse, .. } => {
                pending.extend(orelse.iter().rev());
                pending.extend(body.iter().rev());
            }
            unsupported => {
                return Err(TypedCheckError::UnsupportedStatement {
                    file_name: file_name.to_owned(),
                    definition: definition.to_owned(),
                    statement: statement_kind_name(unsupported).to_owned(),
                    line: statement.location.row,
                    column: statement.location.column,
                });
            }
        }
    }
    Ok(())
}

const fn statement_kind_name(statement: &StmtKind) -> &'static str {
    match statement {
        StmtKind::FunctionDef { .. } => "nested function",
        StmtKind::AsyncFunctionDef { .. } => "async function",
        StmtKind::ClassDef { .. } => "nested class",
        StmtKind::Return { .. } => "return",
        StmtKind::Delete { .. } => "del",
        StmtKind::Assign { .. } => "assignment",
        StmtKind::AugAssign { .. } => "augmented assignment",
        StmtKind::AnnAssign { .. } => "annotated assignment",
        StmtKind::For { .. } => "for",
        StmtKind::AsyncFor { .. } => "async for",
        StmtKind::While { .. } => "while",
        StmtKind::If { .. } => "if",
        StmtKind::With { .. } => "with",
        StmtKind::AsyncWith { .. } => "async with",
        StmtKind::Raise { .. } => "raise",
        StmtKind::Try { .. } => "try",
        StmtKind::Assert { .. } => "assert",
        StmtKind::Import { .. } => "import",
        StmtKind::ImportFrom { .. } => "from import",
        StmtKind::Global { .. } => "global",
        StmtKind::Nonlocal { .. } => "nonlocal",
        StmtKind::Expr { .. } => "expression",
        StmtKind::Pass { .. } => "pass",
        StmtKind::Break { .. } => "break",
        StmtKind::Continue { .. } => "continue",
    }
}

fn class_fields(statements: &[Stmt]) -> ClassFields {
    let mut fields = ClassFields::default();
    for statement in statements {
        match &statement.node {
            StmtKind::AnnAssign {
                target,
                annotation,
                value,
                ..
            } => {
                let ExprKind::Name { id, .. } = &target.node else {
                    continue;
                };
                if let Some(source_type) = class_annotation_type(annotation) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(value) = value {
                    if let Some(normalized) = normalized_compile_expression(value) {
                        fields.values.insert(id.to_string(), normalized);
                    }
                }
            }
            StmtKind::Assign { targets, value, .. } => {
                let [target] = targets.as_slice() else {
                    continue;
                };
                let ExprKind::Name { id, .. } = &target.node else {
                    continue;
                };
                if let Some(source_type) = inferred_compile_value_type(value) {
                    fields.types.insert(id.to_string(), source_type);
                }
                if let Some(normalized) = normalized_compile_expression(value) {
                    fields.values.insert(id.to_string(), normalized);
                }
            }
            _ => {}
        }
    }
    fields
}

fn inferred_compile_value_type(expression: &Expr) -> Option<SourceType> {
    match &expression.node {
        ExprKind::Constant { value, .. } => match value {
            nac3ast::Constant::Bool(_) => Some(SourceType::Bool),
            nac3ast::Constant::Int(_) => Some(SourceType::Int64),
            nac3ast::Constant::Float(_) => Some(SourceType::Float64),
            nac3ast::Constant::Str(_) => Some(SourceType::String),
            _ => None,
        },
        ExprKind::Call { func, .. } => expression_path(func).map(|path| {
            SourceType::NativeRecord(path.rsplit('.').next().unwrap_or(&path).to_owned())
        }),
        ExprKind::Tuple { .. } | ExprKind::List { .. } => Some(SourceType::FixedAggregate),
        _ => None,
    }
}

fn normalized_compile_expression(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Constant { value, .. } => Some(format!("constant:{value:?}")),
        ExprKind::Name { id, .. } => Some(format!("name:{id}")),
        ExprKind::Attribute { .. } => {
            expression_path(expression).map(|path| format!("path:{path}"))
        }
        ExprKind::BinOp { left, op, right } => Some(format!(
            "bin:{op:?}({},{})",
            normalized_compile_expression(left)?,
            normalized_compile_expression(right)?
        )),
        ExprKind::UnaryOp { op, operand } => Some(format!(
            "unary:{op:?}({})",
            normalized_compile_expression(operand)?
        )),
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            let function = expression_path(func)?;
            let args = args
                .iter()
                .map(normalized_compile_expression)
                .collect::<Option<Vec<_>>>()?;
            let keywords = keywords
                .iter()
                .map(|keyword| {
                    Some(format!(
                        "{}={}",
                        keyword
                            .node
                            .arg
                            .map_or("**".to_owned(), |arg| arg.to_string()),
                        normalized_compile_expression(&keyword.node.value)?
                    ))
                })
                .collect::<Option<Vec<_>>>()?;
            Some(format!(
                "call:{function}({};{})",
                args.join(","),
                keywords.join(",")
            ))
        }
        ExprKind::Tuple { elts, .. } | ExprKind::List { elts, .. } => {
            let values = elts
                .iter()
                .map(normalized_compile_expression)
                .collect::<Option<Vec<_>>>()?;
            Some(format!("aggregate:[{}]", values.join(",")))
        }
        _ => None,
    }
}

fn class_annotation_type(annotation: &Expr) -> Option<SourceType> {
    if let ExprKind::Subscript { value, slice, .. } = &annotation.node {
        let container = expression_path(value)?;
        let leaf = container.rsplit('.').next().unwrap_or(&container);
        return match leaf {
            "ClassVar" => class_annotation_type(slice),
            "ExpParam" | "ScanParam" => {
                class_annotation_type(slice).map(|inner| SourceType::ScanParam(Box::new(inner)))
            }
            "tuple" | "Tuple" | "list" | "List" => Some(SourceType::FixedAggregate),
            _ => None,
        };
    }
    let path = expression_path(annotation)?;
    match path.rsplit('.').next().unwrap_or(&path) {
        "bool" | "Bool" => Some(SourceType::Bool),
        "int" | "Int64" => Some(SourceType::Int64),
        "float" | "Float64" => Some(SourceType::Float64),
        "Duration" => Some(SourceType::Duration),
        "str" | "String" => Some(SourceType::String),
        "Morphism" => Some(SourceType::Morphism),
        "MorphismDef" | "MorphismTemplate" => Some(SourceType::MorphismTemplate),
        "Channel" => Some(SourceType::Channel),
        "Board" => Some(SourceType::Board),
        schema => Some(SourceType::NativeRecord(schema.to_owned())),
    }
}

fn module_imports(module_name: &str, statements: &[Stmt]) -> HashMap<String, String> {
    let mut imports = HashMap::new();
    for statement in statements {
        match &statement.node {
            StmtKind::Import { names, .. } => {
                for alias in names {
                    let imported = alias.name.to_string();
                    let local = alias.asname.map_or_else(
                        || imported.split('.').next().unwrap_or(&imported).to_owned(),
                        |name| name.to_string(),
                    );
                    imports.insert(local, imported);
                }
            }
            StmtKind::ImportFrom {
                module,
                names,
                level,
                ..
            } => {
                let module = module.map(|name| name.to_string());
                let imported_module =
                    absolute_import_module(module_name, *level, module.as_deref());
                for alias in names {
                    let imported_name = alias.name.to_string();
                    let local = alias
                        .asname
                        .map_or_else(|| imported_name.clone(), |name| name.to_string());
                    let resolved = if imported_module.is_empty() {
                        imported_name
                    } else {
                        format!("{imported_module}.{imported_name}")
                    };
                    imports.insert(local, resolved);
                }
            }
            _ => {}
        }
    }
    imports
}

fn absolute_import_module(current: &str, level: usize, module: Option<&str>) -> String {
    if level == 0 {
        return module.unwrap_or_default().to_owned();
    }
    let mut package: Vec<_> = current.split('.').collect();
    package.pop();
    for _ in 1..level {
        package.pop();
    }
    if let Some(module) = module {
        package.extend(module.split('.'));
    }
    package.join(".")
}

fn resolve_call_path(
    current_module: &str,
    imports: &HashMap<String, String>,
    call: &str,
) -> String {
    let mut segments = call.split('.');
    let first = segments.next().unwrap_or(call);
    if let Some(imported) = imports.get(first) {
        let remainder = segments.collect::<Vec<_>>().join(".");
        if remainder.is_empty() {
            imported.clone()
        } else {
            format!("{imported}.{remainder}")
        }
    } else {
        format!("{current_module}.{call}")
    }
}

fn resolve_self_call(current_definition: &str, call: &str) -> String {
    let Some(method) = call.strip_prefix("self.") else {
        return call.to_owned();
    };
    let Some((class_name, _)) = current_definition.rsplit_once('.') else {
        return call.to_owned();
    };
    format!("{class_name}.{method}")
}

fn load_source_module<F>(
    module: &str,
    sources: &mut HashMap<String, String>,
    loader: &mut F,
) -> Result<bool, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    if sources.contains_key(module) {
        return Ok(true);
    }
    let source = loader(module).map_err(|message| TypedCheckError::SourceLoad {
        module: module.to_owned(),
        message,
    })?;
    if let Some(source) = source {
        sources.insert(module.to_owned(), source);
        Ok(true)
    } else {
        Ok(false)
    }
}

fn locate_source_definition<F>(
    resolved: &str,
    sources: &mut HashMap<String, String>,
    loader: &mut F,
) -> Result<Option<(String, String)>, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    for (separator, _) in resolved.rmatch_indices('.') {
        let module = &resolved[..separator];
        if load_source_module(module, sources, loader)? {
            return Ok(Some((
                module.to_owned(),
                resolved[separator + 1..].to_owned(),
            )));
        }
    }
    Ok(None)
}

fn resolve_compile_instance_call<F>(
    sources: &mut HashMap<String, String>,
    parsed: &mut HashMap<String, Vec<Stmt>>,
    loader: &mut F,
    resolved: &str,
) -> Result<String, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let Some((module_name, lexical_name)) = locate_source_definition(resolved, sources, loader)?
    else {
        return Ok(resolved.to_owned());
    };
    let Some((instance_name, method_name)) = lexical_name.split_once('.') else {
        return Ok(resolved.to_owned());
    };
    if !parsed.contains_key(&module_name) {
        let source = &sources[&module_name];
        parsed.insert(module_name.clone(), parse_module(&module_name, source)?);
    }
    let suite = &parsed[&module_name];
    let imports = module_imports(&module_name, suite);
    let Some(class_path) =
        module_compile_instances(&module_name, suite, &imports).remove(instance_name)
    else {
        return Ok(resolved.to_owned());
    };
    Ok(format!("{class_path}.{method_name}"))
}

fn module_compile_instances(
    module_name: &str,
    statements: &[Stmt],
    imports: &HashMap<String, String>,
) -> HashMap<String, String> {
    let mut instances = HashMap::new();
    for statement in statements {
        let StmtKind::Assign { targets, value, .. } = &statement.node else {
            continue;
        };
        let [target] = targets.as_slice() else {
            continue;
        };
        let ExprKind::Name { id, .. } = &target.node else {
            continue;
        };
        let ExprKind::Call { func, .. } = &value.node else {
            continue;
        };
        let Some(class_path) = expression_path(func) else {
            continue;
        };
        instances.insert(
            id.to_string(),
            resolve_call_path(module_name, imports, &class_path),
        );
    }
    instances
}

fn legacy_state_bindings(statements: &[Stmt]) -> HashSet<String> {
    let mut candidates = HashSet::new();
    let mut statement_stack: Vec<_> = statements.iter().collect();
    let mut expressions = Vec::<&Expr>::new();
    while let Some(statement) = statement_stack.pop() {
        if let StmtKind::Assign { targets, value, .. } = &statement.node {
            if is_legacy_state_initializer(value) {
                for target in targets {
                    if let ExprKind::Name { id, .. } = &target.node {
                        candidates.insert(id.to_string());
                    }
                }
            }
        }
        push_statement_analysis_children(statement, &mut statement_stack, &mut expressions);
    }

    let mut used_as_call_argument = HashSet::new();
    while let Some(expression) = expressions.pop() {
        if let ExprKind::Call { args, keywords, .. } = &expression.node {
            for argument in args
                .iter()
                .chain(keywords.iter().map(|keyword| keyword.node.value.as_ref()))
            {
                if let ExprKind::Name { id, .. } = &argument.node {
                    if candidates.contains(&id.to_string()) {
                        used_as_call_argument.insert(id.to_string());
                    }
                }
            }
        }
        push_expression_analysis_children(expression, &mut expressions);
    }
    candidates
        .intersection(&used_as_call_argument)
        .cloned()
        .collect()
}

fn push_statement_analysis_children<'a>(
    statement: &'a Stmt,
    statements: &mut Vec<&'a Stmt>,
    expressions: &mut Vec<&'a Expr>,
) {
    match &statement.node {
        StmtKind::Return { value, .. } => expressions.extend(value.iter().map(Box::as_ref)),
        StmtKind::Assign { targets, value, .. } => {
            expressions.extend(targets);
            expressions.push(value);
        }
        StmtKind::AnnAssign { target, value, .. } => {
            expressions.push(target);
            expressions.extend(value.iter().map(Box::as_ref));
        }
        StmtKind::AugAssign { target, value, .. } => {
            expressions.push(target);
            expressions.push(value);
        }
        StmtKind::Expr { value, .. } => expressions.push(value),
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            expressions.push(test);
            statements.extend(body);
            statements.extend(orelse);
        }
        StmtKind::For {
            target,
            iter,
            body,
            orelse,
            ..
        } => {
            expressions.push(target);
            expressions.push(iter);
            statements.extend(body);
            statements.extend(orelse);
        }
        _ => {}
    }
}

fn push_expression_analysis_children<'a>(expression: &'a Expr, stack: &mut Vec<&'a Expr>) {
    match &expression.node {
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            stack.push(func);
            stack.extend(args);
            stack.extend(keywords.iter().map(|keyword| keyword.node.value.as_ref()));
        }
        ExprKind::BoolOp { values, .. }
        | ExprKind::List { elts: values, .. }
        | ExprKind::Tuple { elts: values, .. }
        | ExprKind::Set { elts: values } => stack.extend(values),
        ExprKind::NamedExpr { target, value }
        | ExprKind::BinOp {
            left: target,
            right: value,
            ..
        } => {
            stack.push(target);
            stack.push(value);
        }
        ExprKind::UnaryOp { operand, .. } | ExprKind::Attribute { value: operand, .. } => {
            stack.push(operand);
        }
        ExprKind::IfExp { test, body, orelse } => {
            stack.push(test);
            stack.push(body);
            stack.push(orelse);
        }
        ExprKind::Dict { keys, values } => {
            stack.extend(keys.iter().flatten().map(Box::as_ref));
            stack.extend(values);
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            stack.push(left);
            stack.extend(comparators);
        }
        ExprKind::Subscript { value, slice, .. } => {
            stack.push(value);
            stack.push(slice);
        }
        _ => {}
    }
}

fn is_get_end_state_call(expression: &Expr) -> bool {
    let ExprKind::Call { func, .. } = &expression.node else {
        return false;
    };
    expression_path(func).is_some_and(|path| path.rsplit('.').next() == Some("get_end_state"))
}

fn is_legacy_state_initializer(expression: &Expr) -> bool {
    if is_get_end_state_call(expression) {
        return true;
    }
    let ExprKind::Call {
        func,
        args,
        keywords,
    } = &expression.node
    else {
        return false;
    };
    args.is_empty()
        && keywords.is_empty()
        && expression_path(func).is_some_and(|path| {
            path.ends_with(".default_states.copy") || path.ends_with(".default_state.copy")
        })
}

fn is_erased_state_expression(expression: &Expr, erased_names: &HashSet<String>) -> bool {
    is_legacy_state_initializer(expression)
        || matches!(&expression.node, ExprKind::Name { id, .. } if erased_names.contains(&id.to_string()))
}

fn calls_in_statements(statements: &[Stmt], erased_state_names: &HashSet<String>) -> Vec<String> {
    let mut calls = Vec::new();
    for statement in statements {
        visit_statement_calls(statement, erased_state_names, &mut calls);
    }
    calls
}

fn visit_statement_calls(
    statement: &Stmt,
    erased_state_names: &HashSet<String>,
    calls: &mut Vec<String>,
) {
    match &statement.node {
        StmtKind::Return {
            value: Some(value),
            ..
        } => visit_expression_calls(value, erased_state_names, calls),
        StmtKind::Return { value: None, .. } => {}
        StmtKind::Assign { targets, value, .. }
            if targets.iter().any(|target| {
                matches!(&target.node, ExprKind::Name { id, .. } if erased_state_names.contains(&id.to_string()))
            }) && is_legacy_state_initializer(value) => {}
        StmtKind::Assign { value, .. } | StmtKind::Expr { value, .. } => {
            visit_expression_calls(value, erased_state_names, calls);
        }
        StmtKind::AnnAssign {
            value: Some(value),
            ..
        } => visit_expression_calls(value, erased_state_names, calls),
        StmtKind::AnnAssign { value: None, .. } => {}
        StmtKind::AugAssign { value, .. } => {
            visit_expression_calls(value, erased_state_names, calls);
        }
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            visit_expression_calls(test, erased_state_names, calls);
            for statement in body.iter().chain(orelse) {
                visit_statement_calls(statement, erased_state_names, calls);
            }
        }
        StmtKind::For {
            iter, body, orelse, ..
        } => {
            visit_expression_calls(iter, erased_state_names, calls);
            for statement in body.iter().chain(orelse) {
                visit_statement_calls(statement, erased_state_names, calls);
            }
        }
        _ => {}
    }
}

fn visit_expression_calls(
    expression: &Expr,
    erased_state_names: &HashSet<String>,
    calls: &mut Vec<String>,
) {
    match &expression.node {
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            if let Some(path) = expression_path(func) {
                calls.push(path);
            }
            for argument in args {
                if is_erased_state_expression(argument, erased_state_names) {
                    continue;
                }
                visit_expression_calls(argument, erased_state_names, calls);
            }
            for keyword in keywords {
                if is_erased_state_expression(&keyword.node.value, erased_state_names) {
                    continue;
                }
                visit_expression_calls(&keyword.node.value, erased_state_names, calls);
            }
        }
        ExprKind::BoolOp { values, .. }
        | ExprKind::List { elts: values, .. }
        | ExprKind::Tuple { elts: values, .. }
        | ExprKind::Set { elts: values } => {
            for value in values {
                visit_expression_calls(value, erased_state_names, calls);
            }
        }
        ExprKind::NamedExpr { target, value }
        | ExprKind::BinOp {
            left: target,
            right: value,
            ..
        } => {
            visit_expression_calls(target, erased_state_names, calls);
            visit_expression_calls(value, erased_state_names, calls);
        }
        ExprKind::UnaryOp { operand, .. } => {
            visit_expression_calls(operand, erased_state_names, calls);
        }
        ExprKind::IfExp { test, body, orelse } => {
            visit_expression_calls(test, erased_state_names, calls);
            visit_expression_calls(body, erased_state_names, calls);
            visit_expression_calls(orelse, erased_state_names, calls);
        }
        ExprKind::Dict { keys, values } => {
            for key in keys.iter().flatten() {
                visit_expression_calls(key, erased_state_names, calls);
            }
            for value in values {
                visit_expression_calls(value, erased_state_names, calls);
            }
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            visit_expression_calls(left, erased_state_names, calls);
            for comparator in comparators {
                visit_expression_calls(comparator, erased_state_names, calls);
            }
        }
        ExprKind::Attribute { value, .. } => {
            visit_expression_calls(value, erased_state_names, calls);
        }
        ExprKind::Subscript { value, slice, .. } => {
            visit_expression_calls(value, erased_state_names, calls);
            visit_expression_calls(slice, erased_state_names, calls);
        }
        _ => {}
    }
}

fn signature(
    file_name: &str,
    definition: &str,
    class_name: Option<&str>,
    arguments: &Arguments,
    body: &[Stmt],
    returns: Option<&Expr>,
) -> Result<TypeSignature, TypedCheckError> {
    let mut parameters = Vec::new();
    for argument in arguments
        .posonlyargs
        .iter()
        .chain(&arguments.args)
        .chain(&arguments.kwonlyargs)
    {
        if let Some(parameter) = parameter(file_name, definition, class_name, argument, body)? {
            parameters.push(parameter);
        }
    }
    let return_type = match returns {
        Some(annotation) => annotation_type(file_name, definition, annotation)?,
        None => SourceType::Unit,
    };
    Ok(TypeSignature {
        parameters,
        return_type,
    })
}

fn parameter(
    file_name: &str,
    definition: &str,
    class_name: Option<&str>,
    argument: &Arg,
    body: &[Stmt],
) -> Result<Option<TypedParameter>, TypedCheckError> {
    let name = argument.node.arg.to_string();
    let source_type = match argument.node.annotation.as_deref() {
        Some(annotation) if is_legacy_state_annotation(annotation) => return Ok(None),
        Some(annotation) => annotation_type(file_name, definition, annotation)?,
        None if name == "self" => {
            SourceType::Instance(class_name.unwrap_or("<unknown>").to_owned())
        }
        // In 0.2 this conventional parameter threaded a Python OASM assembler
        // solely to `repeat_morphism`.  The 0.3 frontend normalizes that call to
        // a native Loop Region, so the migration-only handle must disappear
        // before Typed Source HIR instead of acquiring an arbitrary-object type.
        None if is_legacy_sequence_handle(&name, body) => return Ok(None),
        None if infer_unannotated_parameter(&name, body).is_some() => {
            infer_unannotated_parameter(&name, body).expect("checked above")
        }
        None => {
            return Err(TypedCheckError::MissingAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                parameter: name,
            });
        }
    };
    Ok(Some(TypedParameter { name, source_type }))
}

fn infer_unannotated_parameter(name: &str, body: &[Stmt]) -> Option<SourceType> {
    let mut statements: Vec<_> = body.iter().collect();
    let mut expressions = Vec::<&Expr>::new();
    while let Some(statement) = statements.pop() {
        push_statement_analysis_children(statement, &mut statements, &mut expressions);
    }
    while let Some(expression) = expressions.pop() {
        match &expression.node {
            ExprKind::BinOp {
                left, op, right, ..
            } if !matches!(op, nac3ast::Operator::RShift | nac3ast::Operator::BitOr) => {
                let is_parameter = |expression: &Expr| {
                    matches!(&expression.node, ExprKind::Name { id, .. } if id.to_string() == name)
                };
                if is_parameter(left) || is_parameter(right) {
                    return Some(SourceType::Float64);
                }
            }
            ExprKind::Call { func, args, .. }
                if expression_path(func).as_deref() == Some("range")
                    && args.iter().any(|argument| {
                        matches!(&argument.node, ExprKind::Name { id, .. } if id.to_string() == name)
                    }) =>
            {
                return Some(SourceType::Int64);
            }
            _ => {}
        }
        push_expression_analysis_children(expression, &mut expressions);
    }
    None
}

fn is_legacy_state_annotation(annotation: &Expr) -> bool {
    expression_path(annotation).is_some_and(|path| {
        matches!(
            path.rsplit('.').next(),
            Some("State" | "StateMap" | "MorphismEndStateView")
        )
    })
}

fn is_legacy_sequence_handle(name: &str, body: &[Stmt]) -> bool {
    matches!(name, "seq" | "assembler_seq") && !body.is_empty()
}

fn annotation_type(
    file_name: &str,
    definition: &str,
    annotation: &Expr,
) -> Result<SourceType, TypedCheckError> {
    if let ExprKind::Subscript { value, slice, .. } = &annotation.node {
        let container = expression_path(value).unwrap_or_default();
        let leaf = container.rsplit('.').next().unwrap_or(&container);
        return match leaf {
            "Optional" => annotation_type(file_name, definition, slice)
                .map(|inner| SourceType::Optional(Box::new(inner))),
            "ClassVar" => annotation_type(file_name, definition, slice),
            "ExpParam" | "ScanParam" => annotation_type(file_name, definition, slice)
                .map(|inner| SourceType::ScanParam(Box::new(inner))),
            "dict" | "Dict" => Ok(SourceType::ChannelBindings),
            "tuple" | "Tuple" | "list" | "List" => Ok(SourceType::FixedAggregate),
            _ => Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation: format!("{:?}", annotation.node),
            }),
        };
    }
    if let ExprKind::BinOp {
        left,
        op: nac3ast::Operator::BitOr,
        right,
    } = &annotation.node
    {
        let left = annotation_type(file_name, definition, left)?;
        let right = annotation_type(file_name, definition, right)?;
        return match (left, right) {
            (SourceType::Unit, value) | (value, SourceType::Unit) => {
                Ok(SourceType::Optional(Box::new(value)))
            }
            _ => Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation: format!("{:?}", annotation.node),
            }),
        };
    }
    let annotation =
        expression_path(annotation).unwrap_or_else(|| format!("{:?}", annotation.node));
    let leaf = annotation.rsplit('.').next().unwrap_or(&annotation);
    let source_type = match leaf {
        "None" | "Unit" => SourceType::Unit,
        "bool" | "Bool" => SourceType::Bool,
        "int" | "Int64" => SourceType::Int64,
        "float" | "Float64" => SourceType::Float64,
        "Duration" => SourceType::Duration,
        "str" | "String" => SourceType::String,
        "Morphism" => SourceType::Morphism,
        "MorphismDef" | "MorphismTemplate" => SourceType::MorphismTemplate,
        "AtomicMorphism" | "AtomicOp" | "TimedRegion" | "BlackBoxAtomicMorphism" => {
            SourceType::AtomicOp
        }
        "Board" => SourceType::Board,
        "Channel" => SourceType::Channel,
        "ExpParams" | "ScanBindings" => SourceType::ScanBindings,
        _ => {
            return Err(TypedCheckError::UnsupportedAnnotation {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                annotation,
            });
        }
    };
    Ok(source_type)
}

fn expression_path(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { id, .. } => Some(id.to_string()),
        ExprKind::Attribute { value, attr, .. } => {
            let mut path = expression_path(value)?;
            path.push('.');
            path.push_str(&attr.to_string());
            Some(path)
        }
        ExprKind::Constant {
            value: nac3ast::Constant::None,
            ..
        } => Some("None".to_owned()),
        _ => None,
    }
}
