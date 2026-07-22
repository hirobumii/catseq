//! Shared access to validated Morphism child ranges.

use catseq_core::morphism_arena::{MorphismArena, MorphismNode, MorphismNodeId};

pub(super) fn children_by_node<'a>(
    arena: &'a MorphismArena,
    node: &MorphismNode,
) -> &'a [MorphismNodeId] {
    let start = node.edge_start() as usize;
    &arena.edges()[start..start + node.edge_count() as usize]
}
