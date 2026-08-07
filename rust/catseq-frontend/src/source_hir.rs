//! Definition-owned, flat Source HIR and its semantic side tables.

use std::collections::{HashMap, HashSet};

use nac3ast::{Boolop, Cmpop, Constant, Expr, ExprKind, Operator, Stmt, StmtKind};
use serde::{Deserialize, Serialize};

use crate::intrinsics;
use crate::native_records::{self, NativeRecordFieldType};
use crate::typed::resolution::resolve_call_path;
use crate::typed::{SourceType, TypeSignature};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceAnchor {
    module: String,
    line: usize,
    column: usize,
}

impl SourceAnchor {
    pub fn module(&self) -> &str {
        &self.module
    }

    pub const fn line(&self) -> usize {
        self.line
    }

    pub const fn column(&self) -> usize {
        self.column
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceHirKind {
    Name,
    Constant,
    Attribute,
    Subscript,
    Binary,
    Unary,
    Call,
    Dictionary,
    Aggregate,
    Compare,
    ConditionalExpression,
    Lambda,
    Comprehension,
    Assignment,
    Return,
    Expression,
    If,
    While,
    Loop,
    Other,
}

/// CatSeq operations whose identity must survive parsing for native lowering.
///
/// Morphism algebra is recorded separately from scalar arithmetic so both can
/// lower directly into native arenas without retaining Python AST.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum MorphismComposition {
    AutoSerial,
    StrictSerial,
    Parallel,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SourceLiteral {
    None,
    Bool(bool),
    Int(String),
    FloatBits(u64),
    String(String),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ValueOperation {
    Add,
    Subtract,
    Multiply,
    Divide,
    FloorDivide,
    Modulo,
    Power,
    LeftShift,
    Negate,
    Positive,
    LogicalNot,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ComparisonOperation {
    Equal,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Is,
    IsNot,
    In,
    NotIn,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum BooleanOperation {
    And,
    Or,
}

impl BooleanOperation {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::And => "and",
            Self::Or => "or",
        }
    }
}

impl ComparisonOperation {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Equal => "equal",
            Self::NotEqual => "not_equal",
            Self::Less => "less",
            Self::LessEqual => "less_equal",
            Self::Greater => "greater",
            Self::GreaterEqual => "greater_equal",
            Self::Is => "is",
            Self::IsNot => "is_not",
            Self::In => "in",
            Self::NotIn => "not_in",
        }
    }
}

impl ValueOperation {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Add => "add",
            Self::Subtract => "subtract",
            Self::Multiply => "multiply",
            Self::Divide => "divide",
            Self::FloorDivide => "floor_divide",
            Self::Modulo => "modulo",
            Self::Power => "power",
            Self::LeftShift => "left_shift",
            Self::Negate => "negate",
            Self::Positive => "positive",
            Self::LogicalNot => "logical_not",
        }
    }
}

impl MorphismComposition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AutoSerial => "auto_serial",
            Self::StrictSerial => "strict_serial",
            Self::Parallel => "parallel",
        }
    }
}

impl SourceHirKind {
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Name => "name",
            Self::Constant => "constant",
            Self::Attribute => "attribute",
            Self::Subscript => "subscript",
            Self::Binary => "binary",
            Self::Unary => "unary",
            Self::Call => "call",
            Self::Dictionary => "dictionary",
            Self::Aggregate => "aggregate",
            Self::Compare => "compare",
            Self::ConditionalExpression => "conditional_expression",
            Self::Lambda => "lambda",
            Self::Comprehension => "comprehension",
            Self::Assignment => "assignment",
            Self::Return => "return",
            Self::Expression => "expression",
            Self::If => "if",
            Self::While => "while",
            Self::Loop => "loop",
            Self::Other => "other",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceHirNode {
    kind: SourceHirKind,
    symbol: Option<String>,
    morphism_composition: Option<MorphismComposition>,
    literal: Option<SourceLiteral>,
    value_operation: Option<ValueOperation>,
    #[serde(default)]
    boolean_operation: Option<BooleanOperation>,
    #[serde(default)]
    comparison_operations: Vec<ComparisonOperation>,
    #[serde(default)]
    lambda_parameter_names: Vec<String>,
    #[serde(default)]
    comprehension_element_count: u32,
    #[serde(default)]
    comprehension_filter_counts: Vec<u32>,
    #[serde(default)]
    call_positional_count: u32,
    #[serde(default)]
    call_keyword_names: Vec<String>,
    #[serde(default)]
    control_body_count: u32,
    #[serde(default)]
    control_else_count: u32,
    edge_start: u32,
    edge_count: u32,
    anchor: SourceAnchor,
}

impl SourceHirNode {
    pub fn kind(&self) -> &SourceHirKind {
        &self.kind
    }

    pub fn symbol(&self) -> Option<&str> {
        self.symbol.as_deref()
    }

    pub const fn morphism_composition(&self) -> Option<MorphismComposition> {
        self.morphism_composition
    }

    pub const fn literal(&self) -> Option<&SourceLiteral> {
        self.literal.as_ref()
    }

    pub const fn value_operation(&self) -> Option<ValueOperation> {
        self.value_operation
    }

    pub const fn boolean_operation(&self) -> Option<BooleanOperation> {
        self.boolean_operation
    }

    pub fn comparison_operations(&self) -> &[ComparisonOperation] {
        &self.comparison_operations
    }

    pub fn lambda_parameter_names(&self) -> &[String] {
        &self.lambda_parameter_names
    }

    pub const fn comprehension_element_count(&self) -> u32 {
        self.comprehension_element_count
    }

    pub fn comprehension_filter_counts(&self) -> &[u32] {
        &self.comprehension_filter_counts
    }

    pub const fn call_positional_count(&self) -> u32 {
        self.call_positional_count
    }

    pub fn call_keyword_names(&self) -> &[String] {
        &self.call_keyword_names
    }

    /// Number of statement children in the primary body of an `if`, `while`,
    /// or `for` node.  Expression children (the condition, target, and
    /// iterable) precede the statement children in the edge slice.
    pub const fn control_body_count(&self) -> u32 {
        self.control_body_count
    }

    /// Number of statement children in the `else` body of a control-flow node.
    pub const fn control_else_count(&self) -> u32 {
        self.control_else_count
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ResolvedCallTarget {
    definition: String,
    instance_identity: Option<String>,
}

impl ResolvedCallTarget {
    pub fn definition(&self) -> &str {
        &self.definition
    }

    pub fn instance_identity(&self) -> Option<&str> {
        self.instance_identity.as_deref()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SemanticFact {
    source_type: Option<SourceType>,
    availability: ValueAvailability,
    roles: Vec<DependencyRole>,
    resolved_node: Option<u32>,
    resolved_definition: Option<String>,
    resolved_definitions: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    resolved_call_targets: Vec<ResolvedCallTarget>,
    #[serde(default)]
    module_binding_shadowed: bool,
    phase_frame: Option<String>,
    compile_value: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    comprehension_static_values: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    compile_aggregate_element_types: Vec<SourceType>,
}

impl SemanticFact {
    pub fn source_type(&self) -> Option<&SourceType> {
        self.source_type.as_ref()
    }

    pub const fn availability(&self) -> ValueAvailability {
        self.availability
    }

    pub fn roles(&self) -> &[DependencyRole] {
        &self.roles
    }

    pub const fn resolved_node(&self) -> Option<u32> {
        self.resolved_node
    }

    pub fn resolved_definition(&self) -> Option<&str> {
        self.resolved_definition.as_deref()
    }

    pub fn resolved_definitions(&self) -> &[String] {
        &self.resolved_definitions
    }

    pub fn resolved_call_targets(&self) -> &[ResolvedCallTarget] {
        &self.resolved_call_targets
    }

    pub fn phase_frame(&self) -> Option<&str> {
        self.phase_frame.as_deref()
    }

    pub fn compile_value(&self) -> Option<&str> {
        self.compile_value.as_deref()
    }

    pub fn comprehension_static_values(&self) -> Option<&[String]> {
        self.comprehension_static_values.as_deref()
    }

    pub fn compile_aggregate_element_types(&self) -> &[SourceType] {
        &self.compile_aggregate_element_types
    }

    pub(crate) const fn module_binding_shadowed(&self) -> bool {
        self.module_binding_shadowed
    }
}

#[derive(Clone)]
struct LocalBinding {
    source_type: Option<SourceType>,
    value_node: u32,
    availability: ValueAvailability,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypedSourceHir {
    definition: String,
    nodes: Vec<SourceHirNode>,
    edges: Vec<u32>,
    roots: Vec<u32>,
    facts: Vec<SemanticFact>,
}

impl TypedSourceHir {
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

    pub(crate) fn resolve_compile_attributes(
        &mut self,
        attributes: &HashMap<String, (SourceType, String, Vec<SourceType>)>,
    ) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if fact.module_binding_shadowed {
                continue;
            }
            let Some(symbol) = node.symbol.as_deref() else {
                continue;
            };
            let Some((source_type, value, aggregate_element_types)) = attributes.get(symbol) else {
                continue;
            };
            fact.source_type = Some(source_type.clone());
            fact.compile_value = Some(value.clone());
            fact.compile_aggregate_element_types = aggregate_element_types.clone();
        }
    }

    pub(crate) fn resolve_global_symbols(
        &mut self,
        symbols: &HashMap<String, (SourceType, String)>,
    ) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if !matches!(node.kind, SourceHirKind::Name | SourceHirKind::Attribute)
                || fact.module_binding_shadowed
            {
                continue;
            }
            let Some(symbol) = node.symbol.as_deref() else {
                continue;
            };
            let Some((source_type, definition)) = symbols.get(symbol) else {
                continue;
            };
            fact.source_type = Some(source_type.clone());
            record_resolution(fact, definition);
        }
    }

    pub(crate) fn referenced_attributes<'a>(
        &'a self,
        property_names: &'a HashSet<String>,
    ) -> Vec<String> {
        let mut attributes = Vec::new();
        for node in &self.nodes {
            let Some(path) = node
                .symbol
                .as_deref()
                .filter(|_| node.kind == SourceHirKind::Attribute)
            else {
                continue;
            };
            let Some(property) = path.strip_prefix("self.") else {
                continue;
            };
            if property_names.contains(property)
                && !attributes.iter().any(|existing| existing == path)
            {
                attributes.push(path.to_owned());
            }
        }
        attributes
    }

    pub(crate) fn first_link_structural_use(&self) -> Option<&SourceAnchor> {
        self.nodes
            .iter()
            .zip(&self.facts)
            .find(|(_, fact)| {
                fact.availability == ValueAvailability::Link
                    && fact.roles.contains(&DependencyRole::Structural)
            })
            .map(|(node, _)| &node.anchor)
    }

    pub(crate) fn resolve_call(
        &mut self,
        source_path: &str,
        line: usize,
        column: usize,
        resolved: &str,
        instance_identity: Option<&str>,
    ) {
        for node_id in 0..self.nodes.len() {
            let node = &self.nodes[node_id];
            if !call_matches(node, source_path, line, column) {
                continue;
            }
            let first_argument_type = node_edges(node, &self.edges)
                .get(1)
                .and_then(|child| self.facts.get(*child as usize))
                .and_then(SemanticFact::source_type)
                .cloned();
            let fact = &mut self.facts[node_id];
            record_call_resolution(fact, resolved, instance_identity);
            if let Some(source_type) =
                intrinsics::return_type(resolved, first_argument_type.as_ref())
            {
                fact.source_type = Some(source_type);
            }
        }
    }

    pub(crate) fn resolve_attribute(&mut self, source_path: &str, resolved: &str) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if node.kind == SourceHirKind::Attribute && node.symbol.as_deref() == Some(source_path)
            {
                record_resolution(fact, resolved);
            }
        }
    }

    pub(crate) fn resolve_definition_reference(
        &mut self,
        source_path: &str,
        line: usize,
        column: usize,
        resolved: &str,
    ) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if matches!(node.kind, SourceHirKind::Name | SourceHirKind::Attribute)
                && node.symbol.as_deref() == Some(source_path)
                && node.anchor.line == line
                && node.anchor.column == column
            {
                record_resolution(fact, resolved);
            }
        }
    }

    pub(crate) fn definition_reference_resolves_to_lambda(
        &self,
        source_path: &str,
        line: usize,
        column: usize,
    ) -> bool {
        let Some(mut current) = self.nodes.iter().position(|node| {
            matches!(node.kind, SourceHirKind::Name | SourceHirKind::Attribute)
                && node.symbol.as_deref() == Some(source_path)
                && node.anchor.line == line
                && node.anchor.column == column
        }) else {
            return false;
        };
        let mut visited = HashSet::new();
        while visited.insert(current) {
            if self.nodes[current].kind == SourceHirKind::Lambda {
                return true;
            }
            let Some(resolved) = self.facts[current].resolved_node else {
                return false;
            };
            current = resolved as usize;
        }
        false
    }

    pub(crate) fn mark_opaque_atomic_call(
        &mut self,
        source_path: &str,
        line: usize,
        column: usize,
    ) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if call_matches(node, source_path, line, column) {
                fact.source_type = Some(SourceType::Morphism);
                fact.availability = ValueAvailability::Compile;
            }
        }
    }

    pub(crate) fn call_anchor(
        &self,
        source_path: &str,
        line: usize,
        column: usize,
    ) -> Option<&SourceAnchor> {
        self.nodes
            .iter()
            .find(|node| call_matches(node, source_path, line, column))
            .map(|node| &node.anchor)
    }

    pub(crate) fn call_callee_shadows_module_binding(
        &self,
        source_path: &str,
        line: usize,
        column: usize,
    ) -> bool {
        self.nodes
            .iter()
            .find(|node| call_matches(node, source_path, line, column))
            .and_then(|node| node_edges(node, &self.edges).first())
            .and_then(|callee| self.facts.get(*callee as usize))
            .is_some_and(|fact| fact.module_binding_shadowed)
    }

    pub(crate) fn apply_definition_signatures(
        &mut self,
        return_types: &HashMap<String, SourceType>,
    ) {
        for fact in &mut self.facts {
            let mut resolved_types = fact
                .resolved_definitions
                .iter()
                .filter_map(|definition| return_types.get(definition));
            let Some(return_type) = resolved_types.next() else {
                continue;
            };
            if resolved_types.all(|candidate| candidate == return_type) {
                fact.source_type = Some(return_type.clone());
                if matches!(
                    return_type,
                    SourceType::Morphism | SourceType::MorphismTemplate
                ) {
                    fact.availability = ValueAvailability::Compile;
                }
            }
        }
        self.refresh_derived_facts();
    }

    fn refresh_derived_facts(&mut self) {
        for node_id in 0..self.nodes.len() {
            if let Some(resolved_node) = self.facts[node_id].resolved_node {
                let resolved = self.facts[resolved_node as usize].clone();
                self.facts[node_id].source_type = resolved.source_type;
                self.facts[node_id].availability = resolved.availability;
            }

            let children = node_edges(&self.nodes[node_id], &self.edges);
            let child_facts: Vec<_> = children
                .iter()
                .map(|child| self.facts[*child as usize].clone())
                .collect();
            let child_type = |index: usize| {
                child_facts
                    .get(index)
                    .and_then(|fact| fact.source_type.clone())
            };
            let derived_type = match self.nodes[node_id].kind {
                SourceHirKind::Return => Some(child_type(0)),
                SourceHirKind::Assignment | SourceHirKind::Expression => {
                    Some(child_facts.last().and_then(|fact| fact.source_type.clone()))
                }
                SourceHirKind::ConditionalExpression => Some(child_type(1)),
                SourceHirKind::Unary => Some(child_type(0)),
                SourceHirKind::Call
                    if self.facts[node_id]
                        .resolved_definition()
                        .is_some_and(intrinsics::is_native_record_replace) =>
                {
                    let resolved = self.facts[node_id]
                        .resolved_definition()
                        .expect("guarded replace call has a resolved definition");
                    Some(intrinsics::return_type(resolved, child_type(1).as_ref()))
                }
                SourceHirKind::Call if child_type(0) == Some(SourceType::MorphismTemplate) => {
                    Some(Some(SourceType::Morphism))
                }
                SourceHirKind::Binary => Some(
                    if child_facts
                        .iter()
                        .any(|fact| fact.source_type == Some(SourceType::Morphism))
                    {
                        Some(SourceType::Morphism)
                    } else if !child_facts.is_empty()
                        && child_facts
                            .iter()
                            .all(|fact| fact.source_type == Some(SourceType::MorphismTemplate))
                    {
                        Some(SourceType::MorphismTemplate)
                    } else {
                        self.nodes[node_id].value_operation.and_then(|operation| {
                            scalar_binary_type(
                                operation,
                                child_type(0).as_ref(),
                                child_type(1).as_ref(),
                            )
                        })
                    },
                ),
                _ => None,
            };
            if let Some(derived_type) = derived_type {
                self.facts[node_id].source_type = derived_type;
            }
            if self.nodes[node_id].kind == SourceHirKind::Call
                && child_type(0) == Some(SourceType::MorphismTemplate)
                && self.facts[node_id].resolved_definition.is_none()
            {
                record_resolution(&mut self.facts[node_id], "catseq.instantiate");
            }
            if matches!(
                self.nodes[node_id].kind,
                SourceHirKind::Return
                    | SourceHirKind::Assignment
                    | SourceHirKind::Expression
                    | SourceHirKind::ConditionalExpression
                    | SourceHirKind::Unary
                    | SourceHirKind::Binary
            ) {
                self.facts[node_id].availability = child_facts
                    .iter()
                    .map(|fact| fact.availability)
                    .max()
                    .unwrap_or(ValueAvailability::Compile);
            }
        }
    }

    pub(crate) fn inferred_return_type(&self) -> Option<SourceType> {
        self.nodes
            .iter()
            .zip(&self.facts)
            .filter(|(node, _)| node.kind == SourceHirKind::Return)
            .find_map(|(_, fact)| fact.source_type.clone())
    }

    pub(crate) fn first_return_type_mismatch(
        &self,
        expected: &SourceType,
    ) -> Option<(&SourceAnchor, &SourceType)> {
        self.nodes
            .iter()
            .zip(&self.facts)
            .filter(|(node, _)| node.kind == SourceHirKind::Return)
            .filter_map(|(node, fact)| Some((&node.anchor, fact.source_type.as_ref()?)))
            .find(|(_, found)| !return_types_compatible(expected, found))
    }

    pub(crate) fn first_call_argument_type_mismatch(
        &self,
        signatures: &HashMap<String, TypeSignature>,
    ) -> Option<(&SourceAnchor, SourceType, SourceType)> {
        for (node_id, node) in self.nodes.iter().enumerate() {
            if node.kind != SourceHirKind::Call {
                continue;
            }
            let children = node_edges(node, &self.edges);
            for resolved in &self.facts[node_id].resolved_definitions {
                let parameters = signatures.get(resolved).map_or_else(
                    || intrinsics::parameter_types(resolved),
                    |signature| {
                        signature
                            .parameters()
                            .iter()
                            .filter(|parameter| {
                                !matches!(parameter.source_type(), SourceType::Instance(_))
                            })
                            .enumerate()
                            .map(|(index, parameter)| {
                                (index, parameter.name(), parameter.source_type().clone())
                            })
                            .collect()
                    },
                );
                for (position, name, expected) in parameters {
                    let actual = if position < node.call_positional_count as usize {
                        children.get(position + 1)
                    } else {
                        node.call_keyword_names
                            .iter()
                            .position(|keyword| keyword == name)
                            .and_then(|keyword| {
                                children.get(1 + node.call_positional_count as usize + keyword)
                            })
                    };
                    let found = actual
                        .and_then(|actual| self.facts.get(*actual as usize))
                        .and_then(|fact| fact.source_type.as_ref());
                    if let Some(found) = found
                        && !argument_types_compatible(&expected, found)
                    {
                        return Some((&node.anchor, expected, found.clone()));
                    }
                }
            }
        }
        None
    }

    pub(crate) fn first_native_record_replace_error(&self) -> Option<(&SourceAnchor, String)> {
        for (node_id, node) in self.nodes.iter().enumerate() {
            if node.kind != SourceHirKind::Call
                || !self.facts[node_id]
                    .resolved_definition()
                    .is_some_and(intrinsics::is_native_record_replace)
            {
                continue;
            }
            if node.call_positional_count == 0 {
                return Some((
                    &node.anchor,
                    "catseq.replace first argument must be positional".to_owned(),
                ));
            }
            let children = node_edges(node, &self.edges);
            let base_type = children
                .get(1)
                .and_then(|base| self.facts.get(*base as usize))
                .and_then(SemanticFact::source_type);
            let Some(SourceType::NativeRecord(schema_name)) = base_type else {
                return Some((
                    &node.anchor,
                    "catseq.replace requires a Native Record as its first argument".to_owned(),
                ));
            };
            let Some(schema) = native_records::schema(schema_name) else {
                return Some((
                    &node.anchor,
                    format!(
                        "catseq.replace requires a registered Native Record, found `{schema_name}`"
                    ),
                ));
            };
            for argument_index in 1..children.len().saturating_sub(1) {
                let Some(name) = argument_index
                    .checked_sub(node.call_positional_count as usize)
                    .and_then(|keyword| node.call_keyword_names.get(keyword))
                else {
                    return Some((
                        &node.anchor,
                        "catseq.replace fields must be named".to_owned(),
                    ));
                };
                let Some(field) = schema.field(name) else {
                    return Some((
                        &node.anchor,
                        format!(
                            "unknown Native Record field `{name}` for `{}`",
                            schema.name()
                        ),
                    ));
                };
                let field_type = children
                    .get(argument_index + 1)
                    .and_then(|argument| self.facts.get(*argument as usize))
                    .and_then(SemanticFact::source_type);
                if let Some(field_type) = field_type
                    && !field.field_type().accepts(field_type)
                {
                    return Some((
                        &node.anchor,
                        format!(
                            "catseq.replace field `{name}` for `{}` expects {}, found {field_type}",
                            schema.name(),
                            field.field_type()
                        ),
                    ));
                }
                if let Some(element_type) = field.field_type().aggregate_element_type()
                    && let Some(argument) = children.get(argument_index + 1)
                    && let Some(found) =
                        self.first_aggregate_element_type_mismatch(*argument, element_type)
                {
                    return Some((
                        &node.anchor,
                        format!(
                            "catseq.replace field `{name}` for `{}` expects {}, found Aggregate<{found}>",
                            schema.name(),
                            field.field_type()
                        ),
                    ));
                }
            }
        }
        None
    }

    fn first_aggregate_element_type_mismatch(
        &self,
        mut node_id: u32,
        expected: NativeRecordFieldType,
    ) -> Option<SourceType> {
        for _ in 0..self.nodes.len() {
            let fact = self.facts.get(node_id as usize)?;
            let Some(resolved) = fact.resolved_node() else {
                break;
            };
            node_id = resolved;
        }
        let node = self.nodes.get(node_id as usize)?;
        if node.kind == SourceHirKind::Aggregate {
            return node_edges(node, &self.edges)
                .iter()
                .filter_map(|element| self.facts.get(*element as usize))
                .filter_map(SemanticFact::source_type)
                .find(|source_type| !expected.accepts(source_type))
                .cloned();
        }
        self.facts
            .get(node_id as usize)?
            .compile_aggregate_element_types()
            .iter()
            .find(|source_type| !expected.accepts(source_type))
            .cloned()
    }
}

fn call_matches(node: &SourceHirNode, source_path: &str, line: usize, column: usize) -> bool {
    node.kind == SourceHirKind::Call
        && node.symbol.as_deref() == Some(source_path)
        && node.anchor.line == line
        && node.anchor.column == column
}

fn record_resolution(fact: &mut SemanticFact, resolved: &str) {
    if fact.resolved_definition.is_none() {
        fact.resolved_definition = Some(resolved.to_owned());
    }
    if !fact
        .resolved_definitions
        .iter()
        .any(|definition| definition == resolved)
    {
        fact.resolved_definitions.push(resolved.to_owned());
    }
}

fn record_call_resolution(
    fact: &mut SemanticFact,
    resolved: &str,
    instance_identity: Option<&str>,
) {
    record_resolution(fact, resolved);
    let target = ResolvedCallTarget {
        definition: resolved.to_owned(),
        instance_identity: instance_identity.map(str::to_owned),
    };
    fact.resolved_call_targets.push(target);
}

fn return_types_compatible(expected: &SourceType, found: &SourceType) -> bool {
    expected == found
        || matches!(
            (expected, found),
            (SourceType::Float64, SourceType::Int64)
                | (SourceType::Morphism, SourceType::MorphismTemplate)
        )
}

fn argument_types_compatible(expected: &SourceType, found: &SourceType) -> bool {
    expected == found
        || matches!((expected, found), (SourceType::Float64, SourceType::Int64))
        || matches!(
            expected,
            SourceType::Optional(inner) if argument_types_compatible(inner, found)
        )
}

#[derive(Clone, Copy)]
enum AstNode<'a> {
    Expression(&'a Expr),
    Statement(&'a Stmt),
}

#[derive(Clone, Copy)]
enum Task<'a> {
    Enter(AstNode<'a>),
    Exit(AstNode<'a>),
}

pub(crate) struct DefinitionHirContext<'a> {
    module: &'a str,
    fields: &'a HashMap<String, SourceType>,
    field_values: &'a HashMap<String, String>,
    field_aggregate_element_types: &'a HashMap<String, Vec<SourceType>>,
    property_compile_values: &'a HashMap<String, Vec<String>>,
    erased_state_names: &'a HashSet<String>,
    imports: &'a HashMap<String, String>,
}

impl<'a> DefinitionHirContext<'a> {
    pub(crate) fn new(
        module: &'a str,
        fields: &'a HashMap<String, SourceType>,
        field_values: &'a HashMap<String, String>,
        field_aggregate_element_types: &'a HashMap<String, Vec<SourceType>>,
        property_compile_values: &'a HashMap<String, Vec<String>>,
        erased_state_names: &'a HashSet<String>,
        imports: &'a HashMap<String, String>,
    ) -> Self {
        Self {
            module,
            fields,
            field_values,
            field_aggregate_element_types,
            property_compile_values,
            erased_state_names,
            imports,
        }
    }
}

pub(crate) fn lower_definition_hir(
    definition: &str,
    body: &[Stmt],
    signature: &TypeSignature,
    context: &DefinitionHirContext<'_>,
) -> TypedSourceHir {
    let parameters: HashMap<_, _> = signature
        .parameters()
        .iter()
        .map(|parameter| (parameter.name().to_owned(), parameter.source_type().clone()))
        .collect();
    let mut locals = HashMap::<String, LocalBinding>::new();
    let local_names = function_local_names(body, context.erased_state_names);
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let mut facts = Vec::new();
    let mut expression_ids = HashMap::<usize, u32>::new();
    let mut statement_ids = HashMap::<usize, u32>::new();
    let mut roots = Vec::new();
    let root_statements: HashSet<_> = body.iter().map(statement_key).collect();
    let mut tasks = Vec::new();
    for statement in body
        .iter()
        .filter(|statement| !is_erased_state_assignment(statement, context.erased_state_names))
        .rev()
    {
        tasks.push(Task::Enter(AstNode::Statement(statement)));
    }

    while let Some(task) = tasks.pop() {
        match task {
            Task::Enter(ast_node) => {
                tasks.push(Task::Exit(ast_node));
                let children = ast_children(ast_node, context.erased_state_names);
                for child in children.into_iter().rev() {
                    tasks.push(Task::Enter(child));
                }
            }
            Task::Exit(AstNode::Expression(expression)) => {
                let child_ids =
                    ast_children(AstNode::Expression(expression), context.erased_state_names)
                        .into_iter()
                        .filter_map(|child| ast_id(child, &expression_ids, &statement_ids))
                        .collect::<Vec<_>>();
                let edge_start = edges.len() as u32;
                edges.extend_from_slice(&child_ids);
                let fact = expression_fact(
                    expression,
                    &child_ids,
                    &facts,
                    &parameters,
                    &locals,
                    &local_names,
                    context,
                );
                let id = nodes.len() as u32;
                let (comprehension_element_count, comprehension_filter_counts) =
                    expression_comprehension_shape(expression);
                nodes.push(SourceHirNode {
                    kind: expression_kind(expression),
                    symbol: expression_symbol(expression),
                    morphism_composition: expression_morphism_composition(expression),
                    literal: expression_literal(expression),
                    value_operation: expression_value_operation(expression),
                    boolean_operation: expression_boolean_operation(expression),
                    comparison_operations: expression_comparison_operations(expression),
                    lambda_parameter_names: expression_lambda_parameter_names(expression),
                    comprehension_element_count,
                    comprehension_filter_counts,
                    call_positional_count: call_shape(expression, context.erased_state_names).0,
                    call_keyword_names: call_shape(expression, context.erased_state_names).1,
                    control_body_count: 0,
                    control_else_count: 0,
                    edge_start,
                    edge_count: child_ids.len() as u32,
                    anchor: anchor(
                        context.module,
                        expression.location.row,
                        expression.location.column,
                    ),
                });
                facts.push(fact);
                expression_ids.insert(expression_key(expression), id);
            }
            Task::Exit(AstNode::Statement(statement)) => {
                let child_ids =
                    ast_children(AstNode::Statement(statement), context.erased_state_names)
                        .into_iter()
                        .filter_map(|child| ast_id(child, &expression_ids, &statement_ids))
                        .collect::<Vec<_>>();
                let edge_start = edges.len() as u32;
                edges.extend_from_slice(&child_ids);
                let fact = statement_fact(statement, &child_ids, &facts, &mut locals);
                let id = nodes.len() as u32;
                let (control_body_count, control_else_count) =
                    control_shape(statement, context.erased_state_names);
                nodes.push(SourceHirNode {
                    kind: statement_kind(statement),
                    symbol: None,
                    morphism_composition: None,
                    literal: None,
                    value_operation: None,
                    boolean_operation: None,
                    comparison_operations: Vec::new(),
                    lambda_parameter_names: Vec::new(),
                    comprehension_element_count: 0,
                    comprehension_filter_counts: Vec::new(),
                    call_positional_count: 0,
                    call_keyword_names: Vec::new(),
                    control_body_count,
                    control_else_count,
                    edge_start,
                    edge_count: child_ids.len() as u32,
                    anchor: anchor(
                        context.module,
                        statement.location.row,
                        statement.location.column,
                    ),
                });
                facts.push(fact);
                statement_ids.insert(statement_key(statement), id);
                if root_statements.contains(&statement_key(statement)) {
                    roots.push(id);
                }
            }
        }
    }

    propagate_dependency_roles(&nodes, &edges, &mut facts);
    TypedSourceHir {
        definition: definition.to_owned(),
        nodes,
        edges,
        roots,
        facts,
    }
}

fn function_local_names(body: &[Stmt], erased_state_names: &HashSet<String>) -> HashSet<String> {
    let mut names = HashSet::new();
    let mut pending = body.iter().map(AstNode::Statement).collect::<Vec<_>>();
    while let Some(node) = pending.pop() {
        match node {
            AstNode::Statement(statement) => match &statement.node {
                StmtKind::Assign { targets, .. } => {
                    for target in targets {
                        collect_target_names(target, &mut names);
                    }
                }
                StmtKind::AnnAssign { target, .. }
                | StmtKind::AugAssign { target, .. }
                | StmtKind::For { target, .. } => collect_target_names(target, &mut names),
                StmtKind::FunctionDef { name, .. } | StmtKind::ClassDef { name, .. } => {
                    names.insert(name.to_string());
                }
                _ => {}
            },
            AstNode::Expression(expression) => match &expression.node {
                ExprKind::NamedExpr { target, .. } => collect_target_names(target, &mut names),
                ExprKind::ListComp { generators, .. }
                | ExprKind::SetComp { generators, .. }
                | ExprKind::GeneratorExp { generators, .. }
                | ExprKind::DictComp { generators, .. } => {
                    for generator in generators {
                        collect_target_names(&generator.target, &mut names);
                    }
                }
                _ => {}
            },
        }
        pending.extend(ast_children(node, erased_state_names));
    }
    names
}

fn collect_target_names(target: &Expr, names: &mut HashSet<String>) {
    match &target.node {
        ExprKind::Name { id, .. } => {
            names.insert(id.to_string());
        }
        ExprKind::Tuple { elts, .. } | ExprKind::List { elts, .. } => {
            for element in elts {
                collect_target_names(element, names);
            }
        }
        ExprKind::Starred { value, .. } => collect_target_names(value, names),
        _ => {}
    }
}

fn control_shape(statement: &Stmt, erased_state_names: &HashSet<String>) -> (u32, u32) {
    let counts = |body: &[Stmt], orelse: &[Stmt]| {
        let retained = |statements: &[Stmt]| {
            statements
                .iter()
                .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
                .count() as u32
        };
        (retained(body), retained(orelse))
    };
    match &statement.node {
        StmtKind::If { body, orelse, .. }
        | StmtKind::While { body, orelse, .. }
        | StmtKind::For { body, orelse, .. } => counts(body, orelse),
        _ => (0, 0),
    }
}

fn call_shape(expression: &Expr, erased_state_names: &HashSet<String>) -> (u32, Vec<String>) {
    let ExprKind::Call { args, keywords, .. } = &expression.node else {
        return (0, Vec::new());
    };
    let positional_count = args
        .iter()
        .filter(|argument| !is_erased_state_expression(argument, erased_state_names))
        .count() as u32;
    let keyword_names = keywords
        .iter()
        .filter(|keyword| !is_erased_state_expression(&keyword.node.value, erased_state_names))
        .map(|keyword| {
            keyword
                .node
                .arg
                .map_or_else(|| "**".to_owned(), |name| name.to_string())
        })
        .collect();
    (positional_count, keyword_names)
}

fn anchor(module: &str, line: usize, column: usize) -> SourceAnchor {
    SourceAnchor {
        module: module.to_owned(),
        line,
        column,
    }
}

fn expression_key(expression: &Expr) -> usize {
    std::ptr::from_ref(expression).addr()
}

fn statement_key(statement: &Stmt) -> usize {
    std::ptr::from_ref(statement).addr()
}

fn ast_id(
    node: AstNode<'_>,
    expressions: &HashMap<usize, u32>,
    statements: &HashMap<usize, u32>,
) -> Option<u32> {
    match node {
        AstNode::Expression(expression) => expressions.get(&expression_key(expression)).copied(),
        AstNode::Statement(statement) => statements.get(&statement_key(statement)).copied(),
    }
}

fn ast_children<'a>(node: AstNode<'a>, erased_state_names: &HashSet<String>) -> Vec<AstNode<'a>> {
    match node {
        AstNode::Expression(expression) => expression_children(expression, erased_state_names),
        AstNode::Statement(statement) => statement_children(statement, erased_state_names),
    }
}

fn expression_children<'a>(
    expression: &'a Expr,
    erased_state_names: &HashSet<String>,
) -> Vec<AstNode<'a>> {
    let mut children = Vec::new();
    match &expression.node {
        ExprKind::BoolOp { values, .. }
        | ExprKind::List { elts: values, .. }
        | ExprKind::Tuple { elts: values, .. }
        | ExprKind::Set { elts: values } => {
            children.extend(values.iter().map(AstNode::Expression));
        }
        ExprKind::NamedExpr { target, value }
        | ExprKind::BinOp {
            left: target,
            right: value,
            ..
        } => {
            children.push(AstNode::Expression(target));
            children.push(AstNode::Expression(value));
        }
        ExprKind::UnaryOp { operand, .. } | ExprKind::Attribute { value: operand, .. } => {
            children.push(AstNode::Expression(operand));
        }
        ExprKind::Lambda { body, .. } => children.push(AstNode::Expression(body)),
        ExprKind::IfExp { test, body, orelse } => {
            children.push(AstNode::Expression(test));
            children.push(AstNode::Expression(body));
            children.push(AstNode::Expression(orelse));
        }
        ExprKind::Dict { keys, values } => {
            children.extend(
                keys.iter()
                    .flatten()
                    .map(|value| AstNode::Expression(value)),
            );
            children.extend(values.iter().map(AstNode::Expression));
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            children.push(AstNode::Expression(left));
            children.extend(comparators.iter().map(AstNode::Expression));
        }
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            children.push(AstNode::Expression(func));
            let compile_environment_load =
                expression_path(func).is_some_and(|path| path == "np.load" || path == "numpy.load");
            if !compile_environment_load {
                children.extend(
                    args.iter()
                        .filter(|argument| {
                            !is_erased_state_expression(argument, erased_state_names)
                        })
                        .map(AstNode::Expression),
                );
                children.extend(
                    keywords
                        .iter()
                        .map(|keyword| keyword.node.value.as_ref())
                        .filter(|argument| {
                            !is_erased_state_expression(argument, erased_state_names)
                        })
                        .map(AstNode::Expression),
                );
            }
        }
        ExprKind::Subscript { value, slice, .. } => {
            children.push(AstNode::Expression(value));
            children.push(AstNode::Expression(slice));
        }
        ExprKind::ListComp { elt, generators }
        | ExprKind::SetComp { elt, generators }
        | ExprKind::GeneratorExp { elt, generators } => {
            children.push(AstNode::Expression(elt));
            for generator in generators {
                children.push(AstNode::Expression(&generator.target));
                children.push(AstNode::Expression(&generator.iter));
                children.extend(generator.ifs.iter().map(AstNode::Expression));
            }
        }
        ExprKind::DictComp {
            key,
            value,
            generators,
        } => {
            children.push(AstNode::Expression(key));
            children.push(AstNode::Expression(value));
            for generator in generators {
                children.push(AstNode::Expression(&generator.target));
                children.push(AstNode::Expression(&generator.iter));
                children.extend(generator.ifs.iter().map(AstNode::Expression));
            }
        }
        _ => {}
    }
    children
}

fn statement_children<'a>(
    statement: &'a Stmt,
    erased_state_names: &HashSet<String>,
) -> Vec<AstNode<'a>> {
    let mut children = Vec::new();
    match &statement.node {
        StmtKind::Return { value, .. } => {
            children.extend(value.iter().map(|value| AstNode::Expression(value)));
        }
        StmtKind::Assign { targets, value, .. } => {
            children.extend(targets.iter().map(AstNode::Expression));
            children.push(AstNode::Expression(value));
        }
        StmtKind::AnnAssign { target, value, .. } => {
            children.push(AstNode::Expression(target));
            children.extend(value.iter().map(|value| AstNode::Expression(value)));
        }
        StmtKind::AugAssign { target, value, .. } => {
            children.push(AstNode::Expression(target));
            children.push(AstNode::Expression(value));
        }
        StmtKind::Expr { value, .. } => children.push(AstNode::Expression(value)),
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            children.push(AstNode::Expression(test));
            children.extend(
                body.iter()
                    .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
                    .map(AstNode::Statement),
            );
            children.extend(
                orelse
                    .iter()
                    .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
                    .map(AstNode::Statement),
            );
        }
        StmtKind::For {
            target,
            iter,
            body,
            orelse,
            ..
        } => {
            children.push(AstNode::Expression(target));
            children.push(AstNode::Expression(iter));
            children.extend(
                body.iter()
                    .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
                    .map(AstNode::Statement),
            );
            children.extend(
                orelse
                    .iter()
                    .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
                    .map(AstNode::Statement),
            );
        }
        _ => {}
    }
    children
}

fn expression_kind(expression: &Expr) -> SourceHirKind {
    match expression.node {
        ExprKind::Name { .. } => SourceHirKind::Name,
        ExprKind::Constant { .. } => SourceHirKind::Constant,
        ExprKind::Attribute { .. } => SourceHirKind::Attribute,
        ExprKind::Subscript { .. } => SourceHirKind::Subscript,
        ExprKind::BinOp { .. } | ExprKind::BoolOp { .. } => SourceHirKind::Binary,
        ExprKind::UnaryOp { .. } => SourceHirKind::Unary,
        ExprKind::Call { .. } => SourceHirKind::Call,
        ExprKind::Dict { .. } => SourceHirKind::Dictionary,
        ExprKind::List { .. } | ExprKind::Tuple { .. } | ExprKind::Set { .. } => {
            SourceHirKind::Aggregate
        }
        ExprKind::Compare { .. } => SourceHirKind::Compare,
        ExprKind::IfExp { .. } => SourceHirKind::ConditionalExpression,
        ExprKind::Lambda { .. } => SourceHirKind::Lambda,
        ExprKind::ListComp { .. }
        | ExprKind::SetComp { .. }
        | ExprKind::DictComp { .. }
        | ExprKind::GeneratorExp { .. } => SourceHirKind::Comprehension,
        _ => SourceHirKind::Other,
    }
}

fn statement_kind(statement: &Stmt) -> SourceHirKind {
    match statement.node {
        StmtKind::Assign { .. } | StmtKind::AnnAssign { .. } | StmtKind::AugAssign { .. } => {
            SourceHirKind::Assignment
        }
        StmtKind::Return { .. } => SourceHirKind::Return,
        StmtKind::Expr { .. } => SourceHirKind::Expression,
        StmtKind::If { .. } => SourceHirKind::If,
        StmtKind::While { .. } => SourceHirKind::While,
        StmtKind::For { .. } => SourceHirKind::Loop,
        _ => SourceHirKind::Other,
    }
}

fn expression_fact(
    expression: &Expr,
    children: &[u32],
    facts: &[SemanticFact],
    parameters: &HashMap<String, SourceType>,
    locals: &HashMap<String, LocalBinding>,
    local_names: &HashSet<String>,
    context: &DefinitionHirContext<'_>,
) -> SemanticFact {
    let child_fact = |index: usize| children.get(index).and_then(|id| facts.get(*id as usize));
    let joined_availability = || {
        children
            .iter()
            .filter_map(|id| facts.get(*id as usize))
            .map(|fact| fact.availability)
            .max()
            .unwrap_or(ValueAvailability::Compile)
    };
    let mut resolved_node = None;
    let mut resolved_definition = None;
    let mut module_binding_shadowed = false;
    let phase_frame = expression_path(expression).and_then(|path| {
        path.strip_suffix(".phase")
            .filter(|frame| frame.ends_with("_tracker"))
            .map(str::to_owned)
    });
    let compile_value = expression_path(expression).and_then(|path| {
        path.strip_prefix("self.")
            .and_then(|field| context.field_values.get(field).cloned())
    });
    let compile_aggregate_element_types = expression_path(expression)
        .and_then(|path| {
            path.strip_prefix("self.")
                .and_then(|field| context.field_aggregate_element_types.get(field))
                .cloned()
        })
        .unwrap_or_default();
    let (source_type, availability) = match &expression.node {
        ExprKind::Name { id, .. } => {
            let name = id.to_string();
            module_binding_shadowed = local_names.contains(&name) || parameters.contains_key(&name);
            let imported = (!module_binding_shadowed)
                .then(|| resolve_call_path(context.module, context.imports, &name))
                .filter(|resolved| intrinsics::is_duration_unit(resolved));
            resolved_definition.clone_from(&imported);
            resolved_node = locals.get(&name).map(|binding| binding.value_node);
            let availability = locals
                .get(&name)
                .map_or(ValueAvailability::Compile, |binding| binding.availability);
            let source_type = locals
                .get(&name)
                .and_then(|binding| binding.source_type.clone())
                .or_else(|| parameters.get(&name).cloned())
                .or_else(|| imported.map(|_| SourceType::Duration));
            (source_type, availability)
        }
        ExprKind::Constant { value, .. } => (
            match value {
                Constant::None => Some(SourceType::Unit),
                Constant::Bool(_) => Some(SourceType::Bool),
                Constant::Int(_) => Some(SourceType::Int64),
                Constant::Float(_) => Some(SourceType::Float64),
                Constant::Str(_) => Some(SourceType::String),
                Constant::Tuple(_) => Some(SourceType::FixedAggregate),
                _ => None,
            },
            ValueAvailability::Compile,
        ),
        ExprKind::Attribute { .. } => {
            let path = expression_path(expression);
            let root_is_shadowed = path
                .as_deref()
                .and_then(|path| path.split('.').next())
                .is_some_and(|root| local_names.contains(root) || parameters.contains_key(root));
            module_binding_shadowed = root_is_shadowed;
            let imported = (!root_is_shadowed)
                .then(|| {
                    path.as_deref()
                        .map(|path| resolve_call_path(context.module, context.imports, path))
                        .filter(|resolved| intrinsics::is_duration_unit(resolved))
                })
                .flatten();
            resolved_definition.clone_from(&imported);
            let source_type = if imported.is_some() {
                Some(SourceType::Duration)
            } else {
                path.as_deref().and_then(|path| {
                    if path == "np.pi" {
                        return Some(SourceType::Float64);
                    }
                    if path.ends_with("._tracker.phase") {
                        return Some(SourceType::Float64);
                    }
                    path.strip_prefix("self.")
                        .and_then(|field| context.fields.get(field).cloned())
                })
            };
            let availability = path
                .as_deref()
                .and_then(|path| path.strip_prefix("self."))
                .filter(|field| {
                    context.fields.contains_key(*field)
                        && !context.field_values.contains_key(*field)
                })
                .map_or(ValueAvailability::Compile, |_| ValueAvailability::Link);
            (source_type, availability)
        }
        ExprKind::Subscript { .. } => {
            let base_type = child_fact(0).and_then(SemanticFact::source_type);
            if base_type == Some(&SourceType::ScanBindings) {
                let source_type = child_fact(1)
                    .and_then(SemanticFact::source_type)
                    .and_then(|source_type| match source_type {
                        SourceType::ScanParam(inner) => Some(inner.as_ref().clone()),
                        _ => None,
                    })
                    .unwrap_or(SourceType::Float64);
                (Some(source_type), ValueAvailability::Link)
            } else {
                (None, joined_availability())
            }
        }
        ExprKind::BinOp { op, .. } => {
            let left = child_fact(0).and_then(SemanticFact::source_type);
            let right = child_fact(1).and_then(SemanticFact::source_type);
            let source_type = binary_type(*op, left, right);
            (source_type, joined_availability())
        }
        ExprKind::UnaryOp { .. } => (
            child_fact(0).and_then(SemanticFact::source_type).cloned(),
            joined_availability(),
        ),
        ExprKind::Compare { .. } | ExprKind::BoolOp { .. } => {
            (Some(SourceType::Bool), joined_availability())
        }
        ExprKind::IfExp { .. } => (
            child_fact(1).and_then(SemanticFact::source_type).cloned(),
            joined_availability(),
        ),
        ExprKind::Dict { .. } => (Some(SourceType::ChannelBindings), joined_availability()),
        ExprKind::List { .. } | ExprKind::Tuple { .. } | ExprKind::Set { .. } => {
            (Some(SourceType::FixedAggregate), joined_availability())
        }
        ExprKind::ListComp { .. }
        | ExprKind::SetComp { .. }
        | ExprKind::DictComp { .. }
        | ExprKind::GeneratorExp { .. } => {
            (Some(SourceType::FixedAggregate), joined_availability())
        }
        ExprKind::Lambda { .. } => (
            Some(SourceType::NativeRecord("Lambda".to_owned())),
            ValueAvailability::Compile,
        ),
        ExprKind::Call { func, .. } => {
            let source_type = callable_path(func).and_then(|path| {
                intrinsics::return_type(&path, child_fact(1).and_then(SemanticFact::source_type))
            });
            let availability = if matches!(
                source_type,
                Some(SourceType::Morphism | SourceType::MorphismTemplate)
            ) {
                ValueAvailability::Compile
            } else {
                joined_availability()
            };
            (source_type, availability)
        }
        _ => (None, joined_availability()),
    };
    SemanticFact {
        source_type,
        availability,
        roles: Vec::new(),
        resolved_node,
        resolved_definition,
        resolved_definitions: Vec::new(),
        resolved_call_targets: Vec::new(),
        module_binding_shadowed,
        phase_frame,
        compile_value,
        comprehension_static_values: expression_comprehension_static_values(expression, context),
        compile_aggregate_element_types,
    }
}

fn binary_type(
    operator: Operator,
    left: Option<&SourceType>,
    right: Option<&SourceType>,
) -> Option<SourceType> {
    match operator {
        Operator::RShift | Operator::BitOr => {
            if left == Some(&SourceType::MorphismTemplate)
                && right == Some(&SourceType::MorphismTemplate)
            {
                Some(SourceType::MorphismTemplate)
            } else {
                Some(SourceType::Morphism)
            }
        }
        Operator::Add => scalar_binary_type(ValueOperation::Add, left, right),
        Operator::Sub => scalar_binary_type(ValueOperation::Subtract, left, right),
        Operator::Mult => scalar_binary_type(ValueOperation::Multiply, left, right),
        Operator::Div => scalar_binary_type(ValueOperation::Divide, left, right),
        Operator::FloorDiv => scalar_binary_type(ValueOperation::FloorDivide, left, right),
        Operator::Mod => scalar_binary_type(ValueOperation::Modulo, left, right),
        Operator::Pow => scalar_binary_type(ValueOperation::Power, left, right),
        Operator::LShift => scalar_binary_type(ValueOperation::LeftShift, left, right),
        _ => None,
    }
}

fn scalar_binary_type(
    operation: ValueOperation,
    left: Option<&SourceType>,
    right: Option<&SourceType>,
) -> Option<SourceType> {
    match operation {
        ValueOperation::Add | ValueOperation::Subtract
            if left == Some(&SourceType::Duration) && right == Some(&SourceType::Duration) =>
        {
            Some(SourceType::Duration)
        }
        ValueOperation::Multiply
            if (left == Some(&SourceType::Duration) && right.is_some_and(is_numeric_scalar))
                || (right == Some(&SourceType::Duration)
                    && left.is_some_and(is_numeric_scalar)) =>
        {
            Some(SourceType::Duration)
        }
        ValueOperation::Divide
            if left == Some(&SourceType::Duration) && right.is_some_and(is_numeric_scalar) =>
        {
            Some(SourceType::Duration)
        }
        ValueOperation::Divide
            if left == Some(&SourceType::Duration) && right == Some(&SourceType::Duration) =>
        {
            Some(SourceType::Float64)
        }
        _ if left == Some(&SourceType::Duration) || right == Some(&SourceType::Duration) => None,
        _ if left == Some(&SourceType::Float64) || right == Some(&SourceType::Float64) => {
            Some(SourceType::Float64)
        }
        _ if left == Some(&SourceType::Int64) && right == Some(&SourceType::Int64) => {
            Some(SourceType::Int64)
        }
        _ => None,
    }
}

fn is_numeric_scalar(source_type: &SourceType) -> bool {
    matches!(source_type, SourceType::Int64 | SourceType::Float64)
}

fn statement_fact(
    statement: &Stmt,
    children: &[u32],
    facts: &[SemanticFact],
    locals: &mut HashMap<String, LocalBinding>,
) -> SemanticFact {
    let child_facts: Vec<_> = children
        .iter()
        .filter_map(|id| facts.get(*id as usize))
        .collect();
    if matches!(
        &statement.node,
        StmtKind::Assign { .. } | StmtKind::AnnAssign { .. }
    ) {
        let target: Option<&Expr> = match &statement.node {
            StmtKind::Assign { targets, .. } => targets.first(),
            StmtKind::AnnAssign { target, .. } => Some(target),
            _ => None,
        };
        let value = children.last().copied().map(|value_node| LocalBinding {
            source_type: facts[value_node as usize].source_type.clone(),
            value_node,
            availability: facts[value_node as usize].availability,
        });
        if let (Some(target), Some(value)) = (target, value) {
            if let ExprKind::Name { id, .. } = &target.node {
                locals.insert(id.to_string(), value);
            }
        }
    }
    let source_type = match statement.node {
        StmtKind::Return { .. } => child_facts
            .first()
            .and_then(|fact| fact.source_type.clone()),
        _ => Some(SourceType::Unit),
    };
    let availability = child_facts
        .iter()
        .map(|fact| fact.availability)
        .max()
        .unwrap_or(ValueAvailability::Compile);
    SemanticFact {
        source_type,
        availability,
        roles: Vec::new(),
        resolved_node: None,
        resolved_definition: None,
        resolved_definitions: Vec::new(),
        resolved_call_targets: Vec::new(),
        module_binding_shadowed: false,
        phase_frame: None,
        compile_value: None,
        comprehension_static_values: None,
        compile_aggregate_element_types: Vec::new(),
    }
}

fn propagate_dependency_roles(nodes: &[SourceHirNode], edges: &[u32], facts: &mut [SemanticFact]) {
    let mut pending = Vec::<(u32, DependencyRole)>::new();
    for (node_id, node) in nodes.iter().enumerate() {
        let children = node_edges(node, edges);
        match node.kind {
            SourceHirKind::Call => {
                if let Some(function) = children.first() {
                    pending.push((*function, DependencyRole::Structural));
                }
                pending.extend(
                    children
                        .iter()
                        .skip(1)
                        .map(|child| (*child, DependencyRole::Relocatable)),
                );
            }
            SourceHirKind::Dictionary => {
                let half = children.len() / 2;
                pending.extend(
                    children
                        .iter()
                        .take(half)
                        .map(|child| (*child, DependencyRole::Structural)),
                );
                pending.extend(
                    children
                        .iter()
                        .skip(half)
                        .map(|child| (*child, DependencyRole::Relocatable)),
                );
            }
            SourceHirKind::If | SourceHirKind::While | SourceHirKind::Loop => {
                if let Some(control) = children.first() {
                    pending.push((*control, DependencyRole::Structural));
                }
            }
            _ => {
                let _ = node_id;
            }
        }
    }
    while let Some((node_id, role)) = pending.pop() {
        let Some(fact) = facts.get_mut(node_id as usize) else {
            continue;
        };
        if fact.roles.contains(&role) {
            continue;
        }
        fact.roles.push(role);
        fact.roles.sort();
        if let Some(node) = nodes.get(node_id as usize) {
            pending.extend(node_edges(node, edges).iter().map(|child| (*child, role)));
        }
        if let Some(resolved_node) = fact.resolved_node {
            pending.push((resolved_node, role));
        }
    }
}

fn node_edges<'a>(node: &SourceHirNode, edges: &'a [u32]) -> &'a [u32] {
    let start = node.edge_start as usize;
    &edges[start..start + node.edge_count as usize]
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
        _ => None,
    }
}

fn callable_path(expression: &Expr) -> Option<String> {
    expression_path(expression).or_else(|| match &expression.node {
        ExprKind::Attribute { attr, .. } => Some(attr.to_string()),
        _ => None,
    })
}

fn is_erased_state_assignment(statement: &Stmt, erased_state_names: &HashSet<String>) -> bool {
    let StmtKind::Assign { targets, value, .. } = &statement.node else {
        return false;
    };
    targets.iter().any(|target| {
        matches!(&target.node, ExprKind::Name { id, .. } if erased_state_names.contains(&id.to_string()))
    }) && is_legacy_state_initializer(value)
}

fn is_erased_state_expression(expression: &Expr, erased_state_names: &HashSet<String>) -> bool {
    is_legacy_state_initializer(expression)
        || matches!(&expression.node, ExprKind::Name { id, .. } if erased_state_names.contains(&id.to_string()))
}

fn is_legacy_state_initializer(expression: &Expr) -> bool {
    let ExprKind::Call {
        func,
        args,
        keywords,
    } = &expression.node
    else {
        return false;
    };
    let Some(path) = expression_path(func) else {
        return false;
    };
    path.rsplit('.').next() == Some("get_end_state")
        || (args.is_empty()
            && keywords.is_empty()
            && (path.ends_with(".default_states.copy") || path.ends_with(".default_state.copy")))
}

fn expression_symbol(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { .. } | ExprKind::Attribute { .. } => expression_path(expression),
        ExprKind::Call { func, .. } => callable_path(func),
        _ => None,
    }
}

fn expression_morphism_composition(expression: &Expr) -> Option<MorphismComposition> {
    let ExprKind::BinOp { op, .. } = expression.node else {
        return None;
    };
    match op {
        Operator::RShift => Some(MorphismComposition::AutoSerial),
        Operator::MatMult => Some(MorphismComposition::StrictSerial),
        Operator::BitOr => Some(MorphismComposition::Parallel),
        _ => None,
    }
}

fn expression_literal(expression: &Expr) -> Option<SourceLiteral> {
    let ExprKind::Constant { value, .. } = &expression.node else {
        return None;
    };
    match value {
        Constant::None => Some(SourceLiteral::None),
        Constant::Bool(value) => Some(SourceLiteral::Bool(*value)),
        Constant::Int(value) => Some(SourceLiteral::Int(value.to_string())),
        Constant::Float(value) => Some(SourceLiteral::FloatBits(value.to_bits())),
        Constant::Str(value) => Some(SourceLiteral::String(value.to_string())),
        _ => None,
    }
}

fn expression_value_operation(expression: &Expr) -> Option<ValueOperation> {
    match expression.node {
        ExprKind::BinOp { op, .. } => match op {
            Operator::Add => Some(ValueOperation::Add),
            Operator::Sub => Some(ValueOperation::Subtract),
            Operator::Mult => Some(ValueOperation::Multiply),
            Operator::Div => Some(ValueOperation::Divide),
            Operator::FloorDiv => Some(ValueOperation::FloorDivide),
            Operator::Mod => Some(ValueOperation::Modulo),
            Operator::Pow => Some(ValueOperation::Power),
            Operator::LShift => Some(ValueOperation::LeftShift),
            _ => None,
        },
        ExprKind::UnaryOp { op, .. } => match op {
            nac3ast::Unaryop::USub => Some(ValueOperation::Negate),
            nac3ast::Unaryop::UAdd => Some(ValueOperation::Positive),
            nac3ast::Unaryop::Not => Some(ValueOperation::LogicalNot),
            _ => None,
        },
        _ => None,
    }
}

fn expression_boolean_operation(expression: &Expr) -> Option<BooleanOperation> {
    let ExprKind::BoolOp { op, .. } = expression.node else {
        return None;
    };
    Some(match op {
        Boolop::And => BooleanOperation::And,
        Boolop::Or => BooleanOperation::Or,
    })
}

fn expression_comparison_operations(expression: &Expr) -> Vec<ComparisonOperation> {
    let ExprKind::Compare { ops, .. } = &expression.node else {
        return Vec::new();
    };
    ops.iter()
        .map(|operation| match operation {
            Cmpop::Eq => ComparisonOperation::Equal,
            Cmpop::NotEq => ComparisonOperation::NotEqual,
            Cmpop::Lt => ComparisonOperation::Less,
            Cmpop::LtE => ComparisonOperation::LessEqual,
            Cmpop::Gt => ComparisonOperation::Greater,
            Cmpop::GtE => ComparisonOperation::GreaterEqual,
            Cmpop::Is => ComparisonOperation::Is,
            Cmpop::IsNot => ComparisonOperation::IsNot,
            Cmpop::In => ComparisonOperation::In,
            Cmpop::NotIn => ComparisonOperation::NotIn,
        })
        .collect()
}

fn expression_comprehension_static_values(
    expression: &Expr,
    context: &DefinitionHirContext<'_>,
) -> Option<Vec<String>> {
    let generators = match &expression.node {
        ExprKind::ListComp { generators, .. }
        | ExprKind::SetComp { generators, .. }
        | ExprKind::DictComp { generators, .. }
        | ExprKind::GeneratorExp { generators, .. } => generators,
        _ => return None,
    };
    let [generator] = generators.as_slice() else {
        return None;
    };
    let property = expression_path(&generator.iter)
        .and_then(|path| path.strip_prefix("self.").map(str::to_owned))?;
    context.property_compile_values.get(&property).cloned()
}

fn expression_comprehension_shape(expression: &Expr) -> (u32, Vec<u32>) {
    let (element_count, generators) = match &expression.node {
        ExprKind::ListComp { generators, .. }
        | ExprKind::SetComp { generators, .. }
        | ExprKind::GeneratorExp { generators, .. } => (1, generators.as_slice()),
        ExprKind::DictComp { generators, .. } => (2, generators.as_slice()),
        _ => return (0, Vec::new()),
    };
    (
        element_count,
        generators
            .iter()
            .map(|generator| generator.ifs.len() as u32)
            .collect(),
    )
}

fn expression_lambda_parameter_names(expression: &Expr) -> Vec<String> {
    let ExprKind::Lambda { args, .. } = &expression.node else {
        return Vec::new();
    };
    args.posonlyargs
        .iter()
        .chain(&args.args)
        .map(|argument| argument.node.arg.to_string())
        .collect()
}
