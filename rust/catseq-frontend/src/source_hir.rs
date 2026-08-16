//! Python-free typed source facts produced from exact registered definitions.

use serde::{Deserialize, Serialize};
use std::fmt::{Display, Formatter};

use crate::compute_validation::ComputeType;
use crate::registered_modules::RegisteredDefinitionRole;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceAnchor {
    module: String,
    file_name: String,
    line: usize,
    column: usize,
}

impl SourceAnchor {
    pub(crate) fn new(
        module: impl Into<String>,
        file_name: impl Into<String>,
        line: usize,
        column: usize,
    ) -> Self {
        Self {
            module: module.into(),
            file_name: file_name.into(),
            line,
            column,
        }
    }

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

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum ValueType {
    Unit,
    None,
    Bool,
    Int32,
    Float64,
    String,
    Duration,
    Morphism,
    Optional(Box<ValueType>),
    List(Box<ValueType>),
    Sequence(Box<ValueType>),
    Named(String),
}

impl ValueType {
    pub fn as_str(&self) -> String {
        match self {
            Self::Unit => "unit".to_owned(),
            Self::None => "none".to_owned(),
            Self::Bool => "bool".to_owned(),
            Self::Int32 => "i32".to_owned(),
            Self::Float64 => "f64".to_owned(),
            Self::String => "str".to_owned(),
            Self::Duration => "duration".to_owned(),
            Self::Morphism => "morphism".to_owned(),
            Self::Optional(value) => format!("optional[{value}]"),
            Self::List(value) => format!("list[{value}]"),
            Self::Sequence(value) => format!("sequence[{value}]"),
            Self::Named(name) => name.clone(),
        }
    }
}

impl Display for ValueType {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.as_str())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ValueTypeConstructor {
    List,
    Sequence,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceBinding {
    ValueType(ValueType),
    TypeConstructor(ValueTypeConstructor),
    EntryOwner,
    ExpParams,
    ExpParam {
        id: u32,
        name: String,
        value_type: ValueType,
    },
    Definition {
        definition_id: usize,
        role: RegisteredDefinitionRole,
    },
    Intrinsic(SourceIntrinsic),
    HostRpc {
        display_name: String,
    },
    Unsupported {
        display_name: String,
    },
}

impl SourceBinding {
    pub const fn value_type(&self) -> Option<&ValueType> {
        match self {
            Self::ValueType(value_type) => Some(value_type),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceLiteral {
    None,
    Bool(bool),
    Int32(i32),
    Float64(u64),
    String(String),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
pub enum ValueAvailability {
    Compile,
    Link,
    Device,
}

impl ValueAvailability {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Compile => "compile",
            Self::Link => "link",
            Self::Device => "device",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
pub enum DependencyRole {
    Structural,
    Relocatable,
}

impl DependencyRole {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Structural => "structural",
            Self::Relocatable => "relocatable",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum TopologyEffect {
    #[default]
    Empty,
    Morphism,
}

impl TopologyEffect {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Empty => "empty",
            Self::Morphism => "morphism",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceIntrinsic {
    Cycles,
    Identity,
}

impl SourceIntrinsic {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Cycles => "cycles",
            Self::Identity => "identity",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum MorphismComposition {
    AutoSerial,
}

impl MorphismComposition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AutoSerial => "auto_serial",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceHirKind {
    Name,
    Constant,
    Attribute,
    Subscript,
    Call,
    Binary,
    Assignment,
    Return,
}

impl SourceHirKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Name => "name",
            Self::Constant => "constant",
            Self::Attribute => "attribute",
            Self::Subscript => "subscript",
            Self::Call => "call",
            Self::Binary => "binary",
            Self::Assignment => "assignment",
            Self::Return => "return",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ComputeCallReference {
    work_id: u32,
    definition_id: usize,
    parameters: Vec<ComputeType>,
    result: ComputeType,
    abi_signature: String,
    abi_hash: String,
    availability: ValueAvailability,
    topology_effect: TopologyEffect,
    interface_provenance: SourceAnchor,
    call_anchor: SourceAnchor,
}

impl ComputeCallReference {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        work_id: u32,
        definition_id: usize,
        parameters: Vec<ComputeType>,
        result: ComputeType,
        abi_signature: String,
        abi_hash: String,
        availability: ValueAvailability,
        interface_provenance: SourceAnchor,
        call_anchor: SourceAnchor,
    ) -> Self {
        Self {
            work_id,
            definition_id,
            parameters,
            result,
            abi_signature,
            abi_hash,
            availability,
            topology_effect: TopologyEffect::Empty,
            interface_provenance,
            call_anchor,
        }
    }

    pub const fn work_id(&self) -> u32 {
        self.work_id
    }

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

    pub const fn availability(&self) -> ValueAvailability {
        self.availability
    }

    pub const fn topology_effect(&self) -> TopologyEffect {
        self.topology_effect
    }

    pub const fn interface_provenance(&self) -> &SourceAnchor {
        &self.interface_provenance
    }

    pub const fn call_anchor(&self) -> &SourceAnchor {
        &self.call_anchor
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub enum ResolvedCallTarget {
    Definition {
        definition_id: usize,
        role: RegisteredDefinitionRole,
    },
    Intrinsic(SourceIntrinsic),
    Compute(Box<ComputeCallReference>),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CallArgumentOrigin {
    Positional,
    Keyword,
    Default,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CallArgumentBinding {
    parameter: String,
    value_node: u32,
    origin: CallArgumentOrigin,
}

impl CallArgumentBinding {
    pub(crate) fn new(parameter: String, value_node: u32, origin: CallArgumentOrigin) -> Self {
        Self {
            parameter,
            value_node,
            origin,
        }
    }

    pub fn parameter(&self) -> &str {
        &self.parameter
    }

    pub const fn value_node(&self) -> u32 {
        self.value_node
    }

    pub const fn origin(&self) -> CallArgumentOrigin {
        self.origin
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SourceHirNode {
    kind: SourceHirKind,
    symbol: Option<String>,
    literal: Option<SourceLiteral>,
    morphism_composition: Option<MorphismComposition>,
    edge_start: u32,
    edge_count: u32,
    anchor: SourceAnchor,
}

impl SourceHirNode {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        kind: SourceHirKind,
        symbol: Option<String>,
        literal: Option<SourceLiteral>,
        morphism_composition: Option<MorphismComposition>,
        edge_start: u32,
        edge_count: u32,
        anchor: SourceAnchor,
    ) -> Self {
        Self {
            kind,
            symbol,
            literal,
            morphism_composition,
            edge_start,
            edge_count,
            anchor,
        }
    }

    pub const fn kind(&self) -> SourceHirKind {
        self.kind
    }

    pub fn symbol(&self) -> Option<&str> {
        self.symbol.as_deref()
    }

    pub const fn literal(&self) -> Option<&SourceLiteral> {
        self.literal.as_ref()
    }

    pub const fn morphism_composition(&self) -> Option<MorphismComposition> {
        self.morphism_composition
    }

    pub const fn edge_start(&self) -> u32 {
        self.edge_start
    }

    pub const fn edge_count(&self) -> u32 {
        self.edge_count
    }

    pub const fn anchor(&self) -> &SourceAnchor {
        &self.anchor
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SemanticMeaning {
    Value(ValueType),
    SourceBinding(SourceBinding),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SemanticFact {
    meaning: SemanticMeaning,
    availability: ValueAvailability,
    roles: Vec<DependencyRole>,
    topology_effect: TopologyEffect,
    resolved_node: Option<u32>,
    resolved_call: Option<ResolvedCallTarget>,
    call_arguments: Vec<CallArgumentBinding>,
    external_read_id: Option<u32>,
}

impl SemanticFact {
    pub(crate) fn value(
        value_type: ValueType,
        availability: ValueAvailability,
        topology_effect: TopologyEffect,
    ) -> Self {
        Self {
            meaning: SemanticMeaning::Value(value_type),
            availability,
            roles: Vec::new(),
            topology_effect,
            resolved_node: None,
            resolved_call: None,
            call_arguments: Vec::new(),
            external_read_id: None,
        }
    }

    pub(crate) fn binding(binding: SourceBinding) -> Self {
        Self {
            meaning: SemanticMeaning::SourceBinding(binding),
            availability: ValueAvailability::Compile,
            roles: Vec::new(),
            topology_effect: TopologyEffect::Empty,
            resolved_node: None,
            resolved_call: None,
            call_arguments: Vec::new(),
            external_read_id: None,
        }
    }

    pub const fn value_type(&self) -> Option<&ValueType> {
        match &self.meaning {
            SemanticMeaning::Value(value_type) => Some(value_type),
            SemanticMeaning::SourceBinding(_) => None,
        }
    }

    pub const fn source_binding(&self) -> Option<&SourceBinding> {
        match &self.meaning {
            SemanticMeaning::Value(_) => None,
            SemanticMeaning::SourceBinding(binding) => Some(binding),
        }
    }

    pub const fn meaning(&self) -> &SemanticMeaning {
        &self.meaning
    }

    pub const fn availability(&self) -> ValueAvailability {
        self.availability
    }

    pub fn roles(&self) -> &[DependencyRole] {
        &self.roles
    }

    pub const fn topology_effect(&self) -> TopologyEffect {
        self.topology_effect
    }

    pub const fn resolved_node(&self) -> Option<u32> {
        self.resolved_node
    }

    pub const fn resolved_call(&self) -> Option<&ResolvedCallTarget> {
        self.resolved_call.as_ref()
    }

    pub fn call_arguments(&self) -> &[CallArgumentBinding] {
        &self.call_arguments
    }

    pub const fn external_read_id(&self) -> Option<u32> {
        self.external_read_id
    }

    pub(crate) fn set_resolved_node(&mut self, node_id: u32) {
        self.resolved_node = Some(node_id);
    }

    pub(crate) fn set_resolved_call(&mut self, target: ResolvedCallTarget) {
        self.resolved_call = Some(target);
    }

    pub(crate) fn set_call_arguments(&mut self, arguments: Vec<CallArgumentBinding>) {
        self.call_arguments = arguments;
    }

    pub(crate) fn set_external_read_id(&mut self, read_id: u32) {
        self.external_read_id = Some(read_id);
    }

    pub(crate) fn add_role(&mut self, role: DependencyRole) {
        if !self.roles.contains(&role) {
            self.roles.push(role);
            self.roles.sort_unstable();
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TypedSourceHir {
    definition_id: usize,
    definition: String,
    nodes: Vec<SourceHirNode>,
    edges: Vec<u32>,
    roots: Vec<u32>,
    facts: Vec<SemanticFact>,
}

impl TypedSourceHir {
    pub(crate) fn new(
        definition_id: usize,
        definition: String,
        nodes: Vec<SourceHirNode>,
        edges: Vec<u32>,
        roots: Vec<u32>,
        facts: Vec<SemanticFact>,
    ) -> Self {
        assert_eq!(nodes.len(), facts.len());
        Self {
            definition_id,
            definition,
            nodes,
            edges,
            roots,
            facts,
        }
    }

    pub const fn definition_id(&self) -> usize {
        self.definition_id
    }

    pub fn definition(&self) -> &str {
        &self.definition
    }

    pub fn nodes(&self) -> &[SourceHirNode] {
        &self.nodes
    }

    pub fn edges(&self) -> &[u32] {
        &self.edges
    }

    pub fn roots(&self) -> &[u32] {
        &self.roots
    }

    pub fn facts(&self) -> &[SemanticFact] {
        &self.facts
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ExternalRead {
    id: u32,
    name: String,
    value_type: ValueType,
    availability: ValueAvailability,
    value: SourceLiteral,
    anchor: SourceAnchor,
}

impl ExternalRead {
    pub(crate) fn new(
        id: u32,
        name: String,
        value_type: ValueType,
        availability: ValueAvailability,
        value: SourceLiteral,
        anchor: SourceAnchor,
    ) -> Self {
        Self {
            id,
            name,
            value_type,
            availability,
            value,
            anchor,
        }
    }

    pub const fn id(&self) -> u32 {
        self.id
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub const fn value_type(&self) -> &ValueType {
        &self.value_type
    }

    pub const fn availability(&self) -> ValueAvailability {
        self.availability
    }

    pub const fn value(&self) -> &SourceLiteral {
        &self.value
    }

    pub const fn anchor(&self) -> &SourceAnchor {
        &self.anchor
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct DefinitionCallEdge {
    caller_definition_id: usize,
    callee_definition_id: usize,
    callee: String,
    callee_role: RegisteredDefinitionRole,
    anchor: SourceAnchor,
}

impl DefinitionCallEdge {
    pub(crate) fn new(
        caller_definition_id: usize,
        callee_definition_id: usize,
        callee: String,
        callee_role: RegisteredDefinitionRole,
        anchor: SourceAnchor,
    ) -> Self {
        Self {
            caller_definition_id,
            callee_definition_id,
            callee,
            callee_role,
            anchor,
        }
    }

    pub const fn caller_definition_id(&self) -> usize {
        self.caller_definition_id
    }

    pub const fn callee_definition_id(&self) -> usize {
        self.callee_definition_id
    }

    pub fn callee(&self) -> &str {
        &self.callee
    }

    pub const fn callee_role(&self) -> RegisteredDefinitionRole {
        self.callee_role
    }

    pub const fn anchor(&self) -> &SourceAnchor {
        &self.anchor
    }
}
