//! Target-independent structured Control topology.

/// Opaque reference to source-origin data owned by the frontend.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct OriginId(u32);

impl OriginId {
    pub const fn new(index: u32) -> Self {
        Self(index)
    }
}

/// The diagnostic role played by a source origin.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OriginRole {
    Morphism,
    MorphismOperator,
    Return,
    Failure,
    SerialOperator,
}

/// One source contribution retained outside semantic Control structure.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OriginContribution {
    pub origin: OriginId,
    pub role: OriginRole,
}

/// The result exposed by a Control computation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ControlResult<V, T> {
    Unit,
    Value { reference: V, value_type: T },
}

/// The type of the result exposed by a Control computation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ControlResultType<T> {
    Unit,
    Value(T),
}

impl<V, T: Clone> ControlResult<V, T> {
    fn result_type(&self) -> ControlResultType<T> {
        match self {
            Self::Unit => ControlResultType::Unit,
            Self::Value { value_type, .. } => ControlResultType::Value(value_type.clone()),
        }
    }
}

/// Stable identifier for one builder-owned Control node.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct ControlNodeId(u32);

/// The Morphism operations required by Control normalization.
///
/// Morphism identity and Serial remain owned by the Morphism algebra. Control
/// calls this interface without depending on a concrete Morphism arena ID.
/// `serial` must return the Morphism algebra's canonical associative Serial
/// representation; Control deliberately does not inspect Morphism structure.
pub trait MorphismAlgebra<M> {
    type Error;

    fn is_identity(&self, morphism: &M) -> bool;

    fn serial(&mut self, morphisms: Vec<M>) -> Result<M, Self::Error>;
}

/// A Morphism and the source origins that must follow it if it is lifted.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MorphismTerm<M> {
    pub morphism: M,
    origins: Vec<OriginContribution>,
}

impl<M> MorphismTerm<M> {
    pub fn new(morphism: M, origin: OriginId) -> Self {
        Self {
            morphism,
            origins: vec![OriginContribution {
                origin,
                role: OriginRole::Morphism,
            }],
        }
    }

    /// Import all source contributions already collected by the Morphism
    /// layer, including operators inside a composite Morphism.
    pub fn from_origins(morphism: M, origins: Vec<OriginContribution>) -> Self {
        Self { morphism, origins }
    }
}

/// The two domains accepted by CatSeq's overloaded Serial operator.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SerialTerm<M> {
    Morphism(MorphismTerm<M>),
    Control(ControlNodeId),
}

/// One normalized Control node. Source origins are stored separately.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ControlNode<M, V, T> {
    Return(ControlResult<V, T>),
    Lift(M),
    Then(Vec<ControlNodeId>),
    Fail {
        message: String,
        result_type: ControlResultType<T>,
    },
}

struct BuilderNode<M, V, T> {
    node: ControlNode<M, V, T>,
    origins: Vec<OriginContribution>,
    then_origins: Vec<Vec<OriginContribution>>,
}

/// Canonical, target-independent Control topology.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ControlArena<M, V, T> {
    root: ControlNodeId,
    nodes: Vec<ControlNode<M, V, T>>,
}

impl<M, V, T> ControlArena<M, V, T> {
    pub const fn root(&self) -> ControlNodeId {
        self.root
    }

    pub fn nodes(&self) -> &[ControlNode<M, V, T>] {
        &self.nodes
    }

    pub fn node(&self, id: ControlNodeId) -> &ControlNode<M, V, T> {
        &self.nodes[id.0 as usize]
    }

    pub fn children(&self, id: ControlNodeId) -> &[ControlNodeId] {
        match self.node(id) {
            ControlNode::Then(children) => children,
            ControlNode::Return(_) | ControlNode::Lift(_) | ControlNode::Fail { .. } => &[],
        }
    }
}

/// Source-origin data aligned with, but excluded from, semantic Control IR.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OriginMap {
    nodes: Vec<NodeOrigins>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct NodeOrigins {
    node: Vec<OriginContribution>,
    then_boundaries: Vec<Vec<OriginContribution>>,
}

impl OriginMap {
    pub fn node(&self, id: ControlNodeId) -> &[OriginContribution] {
        &self.nodes[id.0 as usize].node
    }

    pub fn then_boundary(
        &self,
        then: ControlNodeId,
        boundary_index: usize,
    ) -> &[OriginContribution] {
        &self.nodes[then.0 as usize].then_boundaries[boundary_index]
    }
}

/// A normalized Control arena together with non-semantic diagnostic origins.
#[derive(Clone, Debug)]
pub struct NormalizedControl<M, V, T> {
    arena: ControlArena<M, V, T>,
    origins: OriginMap,
    summary: ControlSummary<T>,
}

impl<M, V, T> NormalizedControl<M, V, T> {
    pub const fn arena(&self) -> &ControlArena<M, V, T> {
        &self.arena
    }

    pub const fn origins(&self) -> &OriginMap {
        &self.origins
    }

    pub const fn summary(&self) -> &ControlSummary<T> {
        &self.summary
    }
}

impl<M: Clone, V: Clone, T: Clone> NormalizedControl<M, V, T> {
    /// Reapply canonical normalization. This is primarily the pass-level seam
    /// used to assert idempotence before later compiler stages consume Control.
    pub fn renormalize<A>(&self, algebra: &mut A) -> Result<Self, ControlBuildError<A::Error>>
    where
        A: MorphismAlgebra<M>,
    {
        let mut builder = ControlBuilder::new();
        let mut remapped = Vec::with_capacity(self.arena.nodes.len());
        for (index, node) in self.arena.nodes.iter().enumerate() {
            let node = match node {
                ControlNode::Return(result) => ControlNode::Return(result.clone()),
                ControlNode::Lift(morphism) => ControlNode::Lift(morphism.clone()),
                ControlNode::Then(children) => ControlNode::Then(
                    children
                        .iter()
                        .map(|child| remapped[child.0 as usize])
                        .collect(),
                ),
                ControlNode::Fail {
                    message,
                    result_type,
                } => ControlNode::Fail {
                    message: message.clone(),
                    result_type: result_type.clone(),
                },
            };
            let id = builder.push_raw(
                node,
                self.origins.nodes[index].node.clone(),
                self.origins.nodes[index].then_boundaries.clone(),
            );
            remapped.push(id);
        }
        builder.finish(remapped[self.arena.root.0 as usize], algebra)
    }
}

impl<M: PartialEq, V: PartialEq, T: PartialEq> PartialEq for NormalizedControl<M, V, T> {
    fn eq(&self, other: &Self) -> bool {
        self.arena == other.arena
    }
}

impl<M: Eq, V: Eq, T: Eq> Eq for NormalizedControl<M, V, T> {}

/// Target-independent facts derived from normalized Control topology.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ControlSummary<T> {
    pub result_type: ControlResultType<T>,
    pub has_normal_exit: bool,
    pub has_failure_exit: bool,
    pub morphism_island_count: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlDiagnosticCode {
    NoNormalContinuation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlDiagnosticSubject {
    ThenBoundary { left_child_index: usize },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ControlDiagnostic {
    pub code: ControlDiagnosticCode,
    pub subject: ControlDiagnosticSubject,
    pub primary_origin: OriginId,
    pub related_origins: Vec<OriginId>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ControlBuildError<E> {
    Morphism(E),
    Diagnostic(ControlDiagnostic),
}

/// Compiler-facing builder for structured Control topology.
pub struct ControlBuilder<M, V, T> {
    nodes: Vec<BuilderNode<M, V, T>>,
}

impl<M, V, T> Default for ControlBuilder<M, V, T> {
    fn default() -> Self {
        Self::new()
    }
}

impl<M, V, T> ControlBuilder<M, V, T> {
    pub const fn new() -> Self {
        Self { nodes: Vec::new() }
    }

    pub fn return_unit(&mut self, origin: OriginId) -> ControlNodeId {
        self.push_leaf(
            ControlNode::Return(ControlResult::Unit),
            OriginContribution {
                origin,
                role: OriginRole::Return,
            },
        )
    }

    pub fn return_value(&mut self, reference: V, value_type: T, origin: OriginId) -> ControlNodeId {
        self.push_leaf(
            ControlNode::Return(ControlResult::Value {
                reference,
                value_type,
            }),
            OriginContribution {
                origin,
                role: OriginRole::Return,
            },
        )
    }

    pub fn fail(
        &mut self,
        message: impl Into<String>,
        result_type: ControlResultType<T>,
        origin: OriginId,
    ) -> ControlNodeId {
        self.push_leaf(
            ControlNode::Fail {
                message: message.into(),
                result_type,
            },
            OriginContribution {
                origin,
                role: OriginRole::Failure,
            },
        )
    }

    /// Embed a Morphism in Control. This is a compiler-facing operation, not a
    /// source-language constructor.
    pub fn lift(&mut self, term: MorphismTerm<M>) -> ControlNodeId {
        self.push_lift(term)
    }

    /// Build an unnormalized variadic Control sequence.
    pub fn then(
        &mut self,
        children: &[ControlNodeId],
        boundary_origins: &[OriginId],
    ) -> ControlNodeId {
        self.push_then(children.to_vec(), boundary_origins.to_vec())
    }

    pub fn result_type(&self, id: ControlNodeId) -> ControlResultType<T>
    where
        T: Clone,
    {
        match &self.nodes[id.0 as usize].node {
            ControlNode::Return(result) => result.result_type(),
            ControlNode::Lift(_) => ControlResultType::Unit,
            ControlNode::Then(children) => children
                .last()
                .map_or(ControlResultType::Unit, |child| self.result_type(*child)),
            ControlNode::Fail { result_type, .. } => result_type.clone(),
        }
    }

    pub fn serial<A>(
        &mut self,
        algebra: &mut A,
        left: SerialTerm<M>,
        right: SerialTerm<M>,
        operator_origin: OriginId,
    ) -> Result<SerialTerm<M>, ControlBuildError<A::Error>>
    where
        A: MorphismAlgebra<M>,
    {
        match (left, right) {
            (SerialTerm::Morphism(left), SerialTerm::Morphism(right)) => {
                let morphism = algebra
                    .serial(vec![left.morphism, right.morphism])
                    .map_err(ControlBuildError::Morphism)?;
                let mut origins = left.origins;
                origins.push(OriginContribution {
                    origin: operator_origin,
                    role: OriginRole::SerialOperator,
                });
                origins.extend(right.origins);
                Ok(SerialTerm::Morphism(MorphismTerm { morphism, origins }))
            }
            (SerialTerm::Morphism(left), SerialTerm::Control(right)) => {
                let left = self.push_lift(left);
                Ok(SerialTerm::Control(
                    self.push_then(vec![left, right], vec![operator_origin]),
                ))
            }
            (SerialTerm::Control(left), SerialTerm::Morphism(right)) => {
                let right = self.push_lift(right);
                Ok(SerialTerm::Control(
                    self.push_then(vec![left, right], vec![operator_origin]),
                ))
            }
            (SerialTerm::Control(left), SerialTerm::Control(right)) => Ok(SerialTerm::Control(
                self.push_then(vec![left, right], vec![operator_origin]),
            )),
        }
    }

    /// Normalize the selected Control root into a fresh canonical arena.
    pub fn finish<A>(
        self,
        root: ControlNodeId,
        algebra: &mut A,
    ) -> Result<NormalizedControl<M, V, T>, ControlBuildError<A::Error>>
    where
        A: MorphismAlgebra<M>,
        M: Clone,
        V: Clone,
        T: Clone,
    {
        let normalized = self.normalize_node(root, algebra)?;
        let mut arena = ControlArena {
            root: ControlNodeId(0),
            nodes: Vec::new(),
        };
        let mut origins = OriginMap { nodes: Vec::new() };
        let root = emit_normalized(normalized, &mut arena, &mut origins);
        arena.root = root;
        let summary = summarize(&arena);
        Ok(NormalizedControl {
            arena,
            origins,
            summary,
        })
    }

    fn normalize_node<A>(
        &self,
        id: ControlNodeId,
        algebra: &mut A,
    ) -> Result<NormalizedExpr<M, V, T>, ControlBuildError<A::Error>>
    where
        A: MorphismAlgebra<M>,
        M: Clone,
        V: Clone,
        T: Clone,
    {
        let node = &self.nodes[id.0 as usize];
        let origins = node.origins.clone();
        match &node.node {
            ControlNode::Return(result) => Ok(NormalizedExpr {
                kind: NormalizedKind::Return(result.clone()),
                origins,
            }),
            ControlNode::Lift(morphism) => Ok(NormalizedExpr {
                kind: if algebra.is_identity(morphism) {
                    NormalizedKind::Return(ControlResult::Unit)
                } else {
                    NormalizedKind::Lift(morphism.clone())
                },
                origins,
            }),
            ControlNode::Then(children) => {
                let boundary_origins = &node.then_origins;
                let mut sequence = Vec::new();
                for (index, child) in children.iter().enumerate() {
                    let child = self.normalize_node(*child, algebra)?;
                    let before = index
                        .checked_sub(1)
                        .map_or_else(Vec::new, |boundary| boundary_origins[boundary].clone());
                    append_flattened(&mut sequence, child, before);
                }
                reject_missing_normal_continuation(&sequence)?;
                fuse_lift_runs(eliminate_returns(sequence), algebra)
            }
            ControlNode::Fail {
                message,
                result_type,
            } => Ok(NormalizedExpr {
                kind: NormalizedKind::Fail {
                    message: message.clone(),
                    result_type: result_type.clone(),
                },
                origins,
            }),
        }
    }

    fn push_leaf(
        &mut self,
        node: ControlNode<M, V, T>,
        origin: OriginContribution,
    ) -> ControlNodeId {
        self.push_raw(node, vec![origin], Vec::new())
    }

    fn push_lift(&mut self, term: MorphismTerm<M>) -> ControlNodeId {
        self.push_raw(ControlNode::Lift(term.morphism), term.origins, Vec::new())
    }

    fn push_then(
        &mut self,
        children: Vec<ControlNodeId>,
        boundary_origins: Vec<OriginId>,
    ) -> ControlNodeId {
        assert_eq!(children.len().saturating_sub(1), boundary_origins.len());
        let then_origins = boundary_origins
            .into_iter()
            .map(|origin| {
                vec![OriginContribution {
                    origin,
                    role: OriginRole::SerialOperator,
                }]
            })
            .collect();
        self.push_raw(ControlNode::Then(children), Vec::new(), then_origins)
    }

    fn push_raw(
        &mut self,
        node: ControlNode<M, V, T>,
        node_origins: Vec<OriginContribution>,
        then_origins: Vec<Vec<OriginContribution>>,
    ) -> ControlNodeId {
        let id = ControlNodeId(self.nodes.len() as u32);
        self.nodes.push(BuilderNode {
            node,
            origins: node_origins,
            then_origins,
        });
        id
    }
}

struct SequenceItem<M, V, T> {
    before: Vec<OriginContribution>,
    expression: NormalizedExpr<M, V, T>,
}

struct NormalizedExpr<M, V, T> {
    kind: NormalizedKind<M, V, T>,
    origins: Vec<OriginContribution>,
}

enum NormalizedKind<M, V, T> {
    Return(ControlResult<V, T>),
    Lift(M),
    Then {
        children: Vec<NormalizedExpr<M, V, T>>,
        boundaries: Vec<Vec<OriginContribution>>,
    },
    Fail {
        message: String,
        result_type: ControlResultType<T>,
    },
}

fn append_flattened<M, V, T>(
    sequence: &mut Vec<SequenceItem<M, V, T>>,
    expression: NormalizedExpr<M, V, T>,
    before: Vec<OriginContribution>,
) {
    let NormalizedExpr { kind, origins } = expression;
    match kind {
        NormalizedKind::Then {
            children,
            boundaries,
        } => {
            let mut boundaries = boundaries.into_iter();
            for (index, child) in children.into_iter().enumerate() {
                sequence.push(SequenceItem {
                    before: if index == 0 {
                        before.clone()
                    } else {
                        boundaries.next().expect("normalized Then boundary")
                    },
                    expression: child,
                });
            }
        }
        kind => sequence.push(SequenceItem {
            before,
            expression: NormalizedExpr { kind, origins },
        }),
    }
}

fn eliminate_returns<M, V, T>(sequence: Vec<SequenceItem<M, V, T>>) -> Vec<SequenceItem<M, V, T>> {
    let input_len = sequence.len();
    let mut kept: Vec<SequenceItem<M, V, T>> = Vec::with_capacity(input_len);
    let mut pending_origins = Vec::new();

    for (index, mut item) in sequence.into_iter().enumerate() {
        let is_non_final_return =
            index + 1 != input_len && matches!(&item.expression.kind, NormalizedKind::Return(_));
        if is_non_final_return {
            pending_origins.extend(item.before);
            pending_origins.extend(item.expression.origins);
            continue;
        }

        if kept.is_empty() {
            pending_origins.extend(item.before);
            pending_origins.append(&mut item.expression.origins);
            item.expression.origins = pending_origins;
            item.before = Vec::new();
        } else {
            pending_origins.extend(item.before);
            item.before = pending_origins;
        }
        pending_origins = Vec::new();
        kept.push(item);
    }

    let redundant_final_unit = kept.len() > 1
        && matches!(
            kept.last().map(|item| &item.expression.kind),
            Some(NormalizedKind::Return(ControlResult::Unit))
        );
    if redundant_final_unit {
        let unit = kept.pop().expect("redundant final Control unit");
        let previous = kept.last_mut().expect("Control before final unit");
        previous.expression.origins.extend(unit.before);
        previous.expression.origins.extend(unit.expression.origins);
    }

    kept
}

fn reject_missing_normal_continuation<M, V, T, E>(
    sequence: &[SequenceItem<M, V, T>],
) -> Result<(), ControlBuildError<E>> {
    for (left_child_index, pair) in sequence.windows(2).enumerate() {
        if has_normal_exit(&pair[0].expression) {
            continue;
        }

        let primary_origin = pair[1]
            .before
            .iter()
            .find(|origin| origin.role == OriginRole::SerialOperator)
            .expect("every Then relationship has a Serial operator origin")
            .origin;
        let related_origins = pair[0]
            .expression
            .origins
            .iter()
            .chain(&pair[1].expression.origins)
            .map(|origin| origin.origin)
            .collect();
        return Err(ControlBuildError::Diagnostic(ControlDiagnostic {
            code: ControlDiagnosticCode::NoNormalContinuation,
            subject: ControlDiagnosticSubject::ThenBoundary { left_child_index },
            primary_origin,
            related_origins,
        }));
    }
    Ok(())
}

fn has_normal_exit<M, V, T>(expression: &NormalizedExpr<M, V, T>) -> bool {
    match &expression.kind {
        NormalizedKind::Return(_) | NormalizedKind::Lift(_) => true,
        NormalizedKind::Then { children, .. } => has_normal_exit(
            children
                .last()
                .expect("canonical Then has at least two children"),
        ),
        NormalizedKind::Fail { .. } => false,
    }
}

fn fuse_lift_runs<M, V, T, A>(
    sequence: Vec<SequenceItem<M, V, T>>,
    algebra: &mut A,
) -> Result<NormalizedExpr<M, V, T>, ControlBuildError<A::Error>>
where
    A: MorphismAlgebra<M>,
{
    let mut fused = Vec::new();
    let mut items = sequence.into_iter().peekable();
    while let Some(item) = items.next() {
        if !matches!(item.expression.kind, NormalizedKind::Lift(_)) {
            fused.push(item);
            continue;
        }

        let before = item.before;
        let mut morphisms = Vec::new();
        let mut origins = item.expression.origins;
        let NormalizedKind::Lift(first) = item.expression.kind else {
            unreachable!();
        };
        morphisms.push(first);

        while matches!(
            items.peek(),
            Some(SequenceItem {
                expression: NormalizedExpr {
                    kind: NormalizedKind::Lift(_),
                    ..
                },
                ..
            })
        ) {
            let next = items.next().expect("peeked Lift");
            origins.extend(next.before);
            origins.extend(next.expression.origins);
            let NormalizedKind::Lift(morphism) = next.expression.kind else {
                unreachable!();
            };
            morphisms.push(morphism);
        }

        let morphism = if morphisms.len() == 1 {
            morphisms.pop().expect("one Morphism")
        } else {
            algebra
                .serial(morphisms)
                .map_err(ControlBuildError::Morphism)?
        };
        fused.push(SequenceItem {
            before,
            expression: NormalizedExpr {
                kind: NormalizedKind::Lift(morphism),
                origins,
            },
        });
    }

    Ok(reduce_sequence(fused))
}

fn reduce_sequence<M, V, T>(mut sequence: Vec<SequenceItem<M, V, T>>) -> NormalizedExpr<M, V, T> {
    match sequence.len() {
        0 => NormalizedExpr {
            kind: NormalizedKind::Return(ControlResult::Unit),
            origins: Vec::new(),
        },
        1 => sequence.pop().expect("one Control expression").expression,
        _ => {
            let mut children = Vec::with_capacity(sequence.len());
            let mut boundaries = Vec::with_capacity(sequence.len() - 1);
            for (index, item) in sequence.into_iter().enumerate() {
                if index != 0 {
                    boundaries.push(item.before);
                }
                children.push(item.expression);
            }
            NormalizedExpr {
                kind: NormalizedKind::Then {
                    children,
                    boundaries,
                },
                origins: Vec::new(),
            }
        }
    }
}

fn emit_normalized<M, V, T>(
    expression: NormalizedExpr<M, V, T>,
    arena: &mut ControlArena<M, V, T>,
    origin_map: &mut OriginMap,
) -> ControlNodeId {
    let NormalizedExpr { kind, origins } = expression;
    let (node, boundary_origins) = match kind {
        NormalizedKind::Return(result) => (ControlNode::Return(result), Vec::new()),
        NormalizedKind::Lift(morphism) => (ControlNode::Lift(morphism), Vec::new()),
        NormalizedKind::Then {
            children,
            boundaries,
        } => {
            let children = children
                .into_iter()
                .map(|child| emit_normalized(child, arena, origin_map))
                .collect();
            (ControlNode::Then(children), boundaries)
        }
        NormalizedKind::Fail {
            message,
            result_type,
        } => (
            ControlNode::Fail {
                message,
                result_type,
            },
            Vec::new(),
        ),
    };
    let id = ControlNodeId(arena.nodes.len() as u32);
    arena.nodes.push(node);
    origin_map.nodes.push(NodeOrigins {
        node: origins,
        then_boundaries: boundary_origins,
    });
    id
}

fn summarize<M, V, T: Clone>(arena: &ControlArena<M, V, T>) -> ControlSummary<T> {
    ControlSummary {
        result_type: canonical_result_type(arena, arena.root),
        has_normal_exit: canonical_has_normal_exit(arena, arena.root),
        has_failure_exit: arena
            .nodes
            .iter()
            .any(|node| matches!(node, ControlNode::Fail { .. })),
        morphism_island_count: arena
            .nodes
            .iter()
            .filter(|node| matches!(node, ControlNode::Lift(_)))
            .count(),
    }
}

fn canonical_result_type<M, V, T: Clone>(
    arena: &ControlArena<M, V, T>,
    id: ControlNodeId,
) -> ControlResultType<T> {
    match arena.node(id) {
        ControlNode::Return(result) => result.result_type(),
        ControlNode::Lift(_) => ControlResultType::Unit,
        ControlNode::Then(children) => canonical_result_type(
            arena,
            *children
                .last()
                .expect("canonical Then has at least two children"),
        ),
        ControlNode::Fail { result_type, .. } => result_type.clone(),
    }
}

fn canonical_has_normal_exit<M, V, T>(arena: &ControlArena<M, V, T>, id: ControlNodeId) -> bool {
    match arena.node(id) {
        ControlNode::Return(_) | ControlNode::Lift(_) => true,
        ControlNode::Then(children) => canonical_has_normal_exit(
            arena,
            *children
                .last()
                .expect("canonical Then has at least two children"),
        ),
        ControlNode::Fail { .. } => false,
    }
}
