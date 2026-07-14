//! Public typed-frontend model, reports, statistics, and diagnostics.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};

use crate::source_hir::TypedSourceHir;

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
    pub(super) name: String,
    pub(super) source_type: SourceType,
    #[serde(default)]
    pub(super) default_value: Option<String>,
}

impl TypedParameter {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn source_type(&self) -> &SourceType {
        &self.source_type
    }

    pub fn default_value(&self) -> Option<&str> {
        self.default_value.as_deref()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypeSignature {
    pub(super) parameters: Vec<TypedParameter>,
    pub(super) return_type: SourceType,
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
    pub(super) module: String,
    pub(super) qualified_name: String,
    pub(super) signature: TypeSignature,
    pub(super) return_type_is_explicit: bool,
    pub(super) hir: TypedSourceHir,
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

    pub fn fingerprint_seconds(&self) -> f64 {
        self.fingerprint_nanos as f64 / 1_000_000_000.0
    }

    pub fn executed_by_kind(&self) -> &BTreeMap<String, u64> {
        &self.executed_by_kind
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedCheckReport {
    pub(super) entry: String,
    pub(super) definitions: Vec<TypedDefinition>,
    pub(super) diagnostics: Vec<String>,
    pub(super) queried_modules: Vec<String>,
    pub(super) incremental: IncrementalStats,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedCheckSummary {
    pub(super) entry: String,
    pub(super) entry_signature: TypeSignature,
    pub(super) definition_count: usize,
    pub(super) hir_node_count: usize,
    pub(super) diagnostics: Vec<String>,
    pub(super) queried_modules: Vec<String>,
    pub(super) incremental: IncrementalStats,
}

impl TypedCheckSummary {
    pub const fn schema_version(&self) -> u32 {
        2
    }

    pub fn entry(&self) -> &str {
        &self.entry
    }

    pub const fn entry_signature(&self) -> &TypeSignature {
        &self.entry_signature
    }

    pub const fn definition_count(&self) -> usize {
        self.definition_count
    }

    pub const fn hir_node_count(&self) -> usize {
        self.hir_node_count
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
        entry_signature: TypeSignature,
        definition_count: usize,
        hir_node_count: usize,
        diagnostics: Vec<String>,
        queried_modules: Vec<String>,
        incremental: IncrementalStats,
    ) -> Self {
        Self {
            entry,
            entry_signature,
            definition_count,
            hir_node_count,
            diagnostics,
            queried_modules,
            incremental,
        }
    }
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

    pub fn summary(&self) -> TypedCheckSummary {
        let entry_signature = self
            .definitions
            .first()
            .expect("a successful typed check has an entry definition")
            .signature
            .clone();
        TypedCheckSummary {
            entry: self.entry.clone(),
            entry_signature,
            definition_count: self.definitions.len(),
            hir_node_count: self
                .definitions
                .iter()
                .map(|definition| definition.hir.nodes().len())
                .sum(),
            diagnostics: self.diagnostics.clone(),
            queried_modules: self.queried_modules.clone(),
            incremental: self.incremental.clone(),
        }
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
    UnsupportedExpression {
        file_name: String,
        definition: String,
        expression: String,
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
            Self::UnsupportedExpression {
                file_name,
                definition,
                expression,
                line,
                column,
            } => write!(
                formatter,
                "unsupported reachable {expression} expression in {definition} at {file_name}:{line}:{column}"
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
