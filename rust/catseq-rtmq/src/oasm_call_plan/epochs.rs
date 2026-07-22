//! Structural global-sync epoch analysis.

use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload};
use catseq_core::native_arenas::NativeArenas;

use super::arena_util::children_by_node;
use super::model::{AtomicLowering, OasmCompileError, TargetProfile};

pub(super) struct EpochAnalysis {
    pub(super) sync_counts: Vec<u32>,
}

pub(super) fn analyze_epochs(
    program: &NativeArenas,
    target: &TargetProfile,
) -> Result<EpochAnalysis, OasmCompileError> {
    let arena = program.morphisms();
    // Epochs are a structural property of the Morphism DAG. Keep them
    // separate from absolute timestamps so zero-duration operations following
    // a sync cannot be reordered to the pre-sync side of the seam.
    let mut sync_counts = vec![0_u32; arena.nodes().len()];
    for (index, node) in arena.nodes().iter().enumerate() {
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        sync_counts[index] = match node.kind() {
            MorphismNodeKind::Atomic => match payload {
                Some(MorphismPayload::Atomic { operation, .. })
                    if target
                        .operations
                        .get(&arena.operations()[operation.index()])
                        .is_some_and(|schema| schema.lowering == AtomicLowering::GlobalSync) =>
                {
                    1
                }
                _ => 0,
            },
            MorphismNodeKind::Instantiate => match payload {
                Some(MorphismPayload::Instantiate { template, .. }) => {
                    sync_counts[arena.templates()[template.index()].root().index()]
                }
                _ => 0,
            },
            MorphismNodeKind::Serial => {
                children_by_node(arena, node)
                    .iter()
                    .try_fold(0_u32, |count, child| {
                        count
                            .checked_add(sync_counts[child.index()])
                            .ok_or_else(|| OasmCompileError::new("global sync count overflows u32"))
                    })?
            }
            MorphismNodeKind::Parallel => {
                let mut child_counts = children_by_node(arena, node)
                    .iter()
                    .map(|child| sync_counts[child.index()]);
                let first = child_counts.next().unwrap_or(0);
                if child_counts.any(|count| count != first) {
                    return Err(OasmCompileError::new(
                        "parallel branches cross different global sync epochs",
                    ));
                }
                first
            }
            MorphismNodeKind::Loop => {
                let body = children_by_node(arena, node)[0];
                if sync_counts[body.index()] != 0 {
                    return Err(OasmCompileError::new(
                        "hardware loops cannot contain a global sync boundary",
                    ));
                }
                0
            }
            MorphismNodeKind::Wait
            | MorphismNodeKind::DefinitionRef
            | MorphismNodeKind::SyncPhi => 0,
        };
    }
    Ok(EpochAnalysis { sync_counts })
}
