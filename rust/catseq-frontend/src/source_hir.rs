//! Definition-owned, flat Source HIR and its semantic side tables.

use std::collections::{HashMap, HashSet};

use nac3ast::{Constant, Expr, ExprKind, Operator, Stmt, StmtKind};
use serde::{Deserialize, Serialize};

use crate::intrinsics;
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
    Assignment,
    Return,
    Expression,
    If,
    While,
    Loop,
    Other,
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
pub struct SemanticFact {
    source_type: Option<SourceType>,
    availability: ValueAvailability,
    roles: Vec<DependencyRole>,
    resolved_node: Option<u32>,
    resolved_definition: Option<String>,
    phase_frame: Option<String>,
    compile_value: Option<String>,
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

    pub fn phase_frame(&self) -> Option<&str> {
        self.phase_frame.as_deref()
    }

    pub fn compile_value(&self) -> Option<&str> {
        self.compile_value.as_deref()
    }
}

#[derive(Clone)]
struct LocalBinding {
    source_type: SourceType,
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

    pub(crate) fn resolve_call(&mut self, source_path: &str, resolved: &str) {
        for (node, fact) in self.nodes.iter().zip(&mut self.facts) {
            if node.kind == SourceHirKind::Call && node.symbol.as_deref() == Some(source_path) {
                fact.resolved_definition = Some(resolved.to_owned());
                if let Some(source_type) =
                    intrinsics::return_type(resolved, fact.source_type.as_ref())
                {
                    fact.source_type = Some(source_type);
                }
            }
        }
    }

    pub(crate) fn call_anchor(&self, source_path: &str) -> Option<&SourceAnchor> {
        self.nodes
            .iter()
            .find(|node| {
                node.kind == SourceHirKind::Call && node.symbol.as_deref() == Some(source_path)
            })
            .map(|node| &node.anchor)
    }

    pub(crate) fn apply_definition_signatures(
        &mut self,
        return_types: &HashMap<String, SourceType>,
    ) {
        for fact in &mut self.facts {
            let Some(definition) = fact.resolved_definition.as_deref() else {
                continue;
            };
            if let Some(return_type) = return_types.get(definition) {
                fact.source_type = Some(return_type.clone());
                if matches!(
                    return_type,
                    SourceType::Morphism | SourceType::MorphismTemplate
                ) {
                    fact.availability = ValueAvailability::Compile;
                }
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
}

fn return_types_compatible(expected: &SourceType, found: &SourceType) -> bool {
    expected == found
        || matches!(
            (expected, found),
            (SourceType::Float64, SourceType::Int64)
                | (SourceType::Morphism, SourceType::MorphismTemplate)
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

pub(crate) fn lower_definition_hir(
    module: &str,
    definition: &str,
    body: &[Stmt],
    signature: &TypeSignature,
    fields: &HashMap<String, SourceType>,
    field_values: &HashMap<String, String>,
    erased_state_names: &HashSet<String>,
) -> TypedSourceHir {
    let parameters: HashMap<_, _> = signature
        .parameters()
        .iter()
        .map(|parameter| (parameter.name().to_owned(), parameter.source_type().clone()))
        .collect();
    let mut locals = HashMap::<String, LocalBinding>::new();
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
        .filter(|statement| !is_erased_state_assignment(statement, erased_state_names))
        .rev()
    {
        tasks.push(Task::Enter(AstNode::Statement(statement)));
    }

    while let Some(task) = tasks.pop() {
        match task {
            Task::Enter(ast_node) => {
                tasks.push(Task::Exit(ast_node));
                let children = ast_children(ast_node, erased_state_names);
                for child in children.into_iter().rev() {
                    tasks.push(Task::Enter(child));
                }
            }
            Task::Exit(AstNode::Expression(expression)) => {
                let child_ids = ast_children(AstNode::Expression(expression), erased_state_names)
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
                    fields,
                    field_values,
                );
                let id = nodes.len() as u32;
                nodes.push(SourceHirNode {
                    kind: expression_kind(expression),
                    symbol: expression_symbol(expression),
                    edge_start,
                    edge_count: child_ids.len() as u32,
                    anchor: anchor(module, expression.location.row, expression.location.column),
                });
                facts.push(fact);
                expression_ids.insert(expression_key(expression), id);
            }
            Task::Exit(AstNode::Statement(statement)) => {
                let child_ids = ast_children(AstNode::Statement(statement), erased_state_names)
                    .into_iter()
                    .filter_map(|child| ast_id(child, &expression_ids, &statement_ids))
                    .collect::<Vec<_>>();
                let edge_start = edges.len() as u32;
                edges.extend_from_slice(&child_ids);
                let fact = statement_fact(statement, &child_ids, &facts, &mut locals);
                let id = nodes.len() as u32;
                nodes.push(SourceHirNode {
                    kind: statement_kind(statement),
                    symbol: None,
                    edge_start,
                    edge_count: child_ids.len() as u32,
                    anchor: anchor(module, statement.location.row, statement.location.column),
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
            children.extend(
                args.iter()
                    .filter(|argument| !is_erased_state_expression(argument, erased_state_names))
                    .map(AstNode::Expression),
            );
            children.extend(
                keywords
                    .iter()
                    .map(|keyword| keyword.node.value.as_ref())
                    .filter(|argument| !is_erased_state_expression(argument, erased_state_names))
                    .map(AstNode::Expression),
            );
        }
        ExprKind::Subscript { value, slice, .. } => {
            children.push(AstNode::Expression(value));
            children.push(AstNode::Expression(slice));
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
    fields: &HashMap<String, SourceType>,
    field_values: &HashMap<String, String>,
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
    let phase_frame = expression_path(expression).and_then(|path| {
        path.strip_suffix(".phase")
            .filter(|frame| frame.ends_with("_tracker"))
            .map(str::to_owned)
    });
    let compile_value = expression_path(expression).and_then(|path| {
        path.strip_prefix("self.")
            .and_then(|field| field_values.get(field).cloned())
    });
    let (source_type, availability) = match &expression.node {
        ExprKind::Name { id, .. } => {
            let name = id.to_string();
            resolved_node = locals.get(&name).map(|binding| binding.value_node);
            let availability = locals
                .get(&name)
                .map_or(ValueAvailability::Compile, |binding| binding.availability);
            let source_type = locals
                .get(&name)
                .map(|binding| binding.source_type.clone())
                .or_else(|| parameters.get(&name).cloned())
                .or(match name.as_str() {
                    "us" | "ms" | "s" | "ns" => Some(SourceType::Duration),
                    _ => None,
                });
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
            let source_type = expression_path(expression).and_then(|path| {
                if path == "np.pi" {
                    return Some(SourceType::Float64);
                }
                if path.ends_with("._tracker.phase") {
                    return Some(SourceType::Float64);
                }
                path.strip_prefix("self.")
                    .and_then(|field| fields.get(field).cloned())
            });
            (source_type, ValueAvailability::Compile)
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
        ExprKind::Call { func, .. } => {
            let source_type = expression_path(func).and_then(|path| {
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
        resolved_definition: None,
        phase_frame,
        compile_value,
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
        Operator::Mult | Operator::Div
            if left == Some(&SourceType::Duration) || right == Some(&SourceType::Duration) =>
        {
            Some(SourceType::Duration)
        }
        _ if left == Some(&SourceType::Float64) || right == Some(&SourceType::Float64) => {
            Some(SourceType::Float64)
        }
        _ if left == Some(&SourceType::Int64) && right == Some(&SourceType::Int64) => {
            Some(SourceType::Int64)
        }
        _ => None,
    }
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
        let value = children.last().copied().and_then(|value_node| {
            facts
                .get(value_node as usize)
                .and_then(|fact| fact.source_type.clone())
                .map(|source_type| LocalBinding {
                    source_type,
                    value_node,
                    availability: facts[value_node as usize].availability,
                })
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
        phase_frame: None,
        compile_value: None,
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
        ExprKind::Call { func, .. } => expression_path(func),
        _ => None,
    }
}
