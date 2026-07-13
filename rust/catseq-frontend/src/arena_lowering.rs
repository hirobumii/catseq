//! Lower source-level Morphism structure into the shared Rust arena.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use catseq_core::arena::{ArenaError, ArenaStore, FrozenProgram, NodeKind, NodeRef, SegmentId};

use crate::{CompositionKind, ExpressionId, HirKind, SequenceHir, SourceSpan};

/// A frozen arena root that pins the source HIR referenced by its payload IDs.
#[derive(Clone, Debug)]
pub struct SourceArenaProgram {
    hir: Arc<SequenceHir>,
    store: ArenaStore,
    frozen: FrozenProgram,
    segment: SegmentId,
}

impl SourceArenaProgram {
    pub fn hir(&self) -> &SequenceHir {
        &self.hir
    }

    pub fn hir_arc(&self) -> &Arc<SequenceHir> {
        &self.hir
    }

    pub fn frozen(&self) -> &FrozenProgram {
        &self.frozen
    }

    pub fn root(&self) -> NodeRef {
        self.frozen.root()
    }

    pub const fn segment(&self) -> SegmentId {
        self.segment
    }

    pub(crate) fn rebind_hir(&self, hir: Arc<SequenceHir>) -> Self {
        debug_assert!(self.hir.structurally_eq_ignoring_spans(&hir));
        let frozen = self
            .store
            .freeze_with_owner(self.root(), Arc::clone(&hir))
            .expect("an append-only arena cannot invalidate a frozen root");
        Self {
            hir,
            store: self.store.clone(),
            frozen,
            segment: self.segment,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArenaLoweringError {
    NonMorphism {
        kind: &'static str,
        span: SourceSpan,
    },
    Arena(ArenaError),
}

impl Display for ArenaLoweringError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NonMorphism { kind, span } => write!(
                formatter,
                "source {kind} at {}:{} does not produce a Morphism",
                span.start_line, span.start_column
            ),
            Self::Arena(error) => Display::fmt(error, formatter),
        }
    }
}

impl Error for ArenaLoweringError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::NonMorphism { .. } => None,
            Self::Arena(error) => Some(error),
        }
    }
}

impl From<ArenaError> for ArenaLoweringError {
    fn from(error: ArenaError) -> Self {
        Self::Arena(error)
    }
}

/// Lower only Morphism structure into an existing arena segment.
///
/// Calls become unresolved `SourceCall` leaves. Their arguments, scan
/// expressions, and other scalar computations stay in `SequenceHir`; arena
/// payload IDs point back into that pinned HIR. Traversal is iterative and
/// memoized, so source DAG sharing is preserved without recursive Rust calls.
pub fn lower_sequence_hir(
    hir: Arc<SequenceHir>,
    store: &ArenaStore,
    segment: SegmentId,
) -> Result<SourceArenaProgram, ArenaLoweringError> {
    validate_morphism_graph(&hir)?;

    let mut lowered = HashMap::<ExpressionId, NodeRef>::new();
    let mut work = vec![Work::Enter(hir.root())];
    while let Some(item) = work.pop() {
        match item {
            Work::Enter(expression) => {
                if lowered.contains_key(&expression) {
                    continue;
                }
                match hir.expression(expression).kind() {
                    HirKind::Call { .. } => {
                        let node = store.source_call(segment, expression.index())?;
                        lowered.insert(expression, node);
                    }
                    HirKind::Compose { kind, left, right } => {
                        let dictionary = match hir.expression(*right).kind() {
                            HirKind::Dictionary(entries)
                                if *kind == CompositionKind::AutoSerial =>
                            {
                                Some(entries)
                            }
                            _ => None,
                        };
                        if let Some(entries) = dictionary {
                            let deferred = if entries.is_empty() {
                                Work::Alias {
                                    expression,
                                    target: *left,
                                }
                            } else {
                                Work::DeferredApply {
                                    expression,
                                    left: *left,
                                    dictionary: *right,
                                }
                            };
                            work.push(deferred);
                            work.push(Work::Enter(*left));
                        } else {
                            work.push(Work::Compose {
                                expression,
                                kind: *kind,
                                left: *left,
                                right: *right,
                            });
                            work.push(Work::Enter(*right));
                            work.push(Work::Enter(*left));
                        }
                    }
                    _ => unreachable!("validated Morphism graph contains a scalar node"),
                }
            }
            Work::Alias { expression, target } => {
                lowered.insert(expression, lowered[&target]);
            }
            Work::Compose {
                expression,
                kind,
                left,
                right,
            } => {
                let node = store.compose(
                    segment,
                    arena_composition_kind(kind),
                    lowered[&left],
                    lowered[&right],
                    expression.index(),
                )?;
                lowered.insert(expression, node);
            }
            Work::DeferredApply {
                expression,
                left,
                dictionary,
            } => {
                let left = lowered[&left];
                let node = store.append_raw(
                    segment,
                    NodeKind::DeferredApply,
                    Some(left),
                    None,
                    dictionary.index(),
                    store.node_channel_mask(left)?,
                    expression.index(),
                )?;
                lowered.insert(expression, node);
            }
        }
    }

    let root = lowered[&hir.root()];
    let frozen = store.freeze_with_owner(root, Arc::clone(&hir))?;
    Ok(SourceArenaProgram {
        hir,
        store: store.clone(),
        frozen,
        segment,
    })
}

#[derive(Clone, Copy, Debug)]
enum Work {
    Enter(ExpressionId),
    Alias {
        expression: ExpressionId,
        target: ExpressionId,
    },
    Compose {
        expression: ExpressionId,
        kind: CompositionKind,
        left: ExpressionId,
        right: ExpressionId,
    },
    DeferredApply {
        expression: ExpressionId,
        left: ExpressionId,
        dictionary: ExpressionId,
    },
}

fn validate_morphism_graph(hir: &SequenceHir) -> Result<(), ArenaLoweringError> {
    let mut seen = vec![false; hir.expressions().len()];
    let mut stack = vec![hir.root()];
    while let Some(expression) = stack.pop() {
        let index = expression.index() as usize;
        if seen[index] {
            continue;
        }
        seen[index] = true;
        match hir.expression(expression).kind() {
            HirKind::Call { .. } => {}
            HirKind::Compose { kind, left, right } => {
                stack.push(*left);
                if !(*kind == CompositionKind::AutoSerial
                    && matches!(hir.expression(*right).kind(), HirKind::Dictionary(_)))
                {
                    stack.push(*right);
                }
            }
            kind => {
                return Err(ArenaLoweringError::NonMorphism {
                    kind: hir_kind_name(kind),
                    span: hir.expression(expression).span(),
                });
            }
        }
    }
    Ok(())
}

const fn arena_composition_kind(kind: CompositionKind) -> NodeKind {
    match kind {
        CompositionKind::AutoSerial => NodeKind::AutoSerial,
        CompositionKind::StrictSerial => NodeKind::StrictSerial,
        CompositionKind::Parallel => NodeKind::Parallel,
    }
}

const fn hir_kind_name(kind: &HirKind) -> &'static str {
    match kind {
        HirKind::Symbol(_) => "symbol",
        HirKind::Literal(_) => "literal",
        HirKind::Attribute { .. } => "attribute",
        HirKind::Subscript { .. } => "subscript",
        HirKind::Call { .. } => "call",
        HirKind::Compose { .. } => "composition",
        HirKind::Binary { .. } => "binary expression",
        HirKind::Unary { .. } => "unary expression",
        HirKind::Dictionary(_) => "dictionary",
        HirKind::List(_) => "list",
        HirKind::Tuple(_) => "tuple",
    }
}
