use std::sync::Arc;

use catseq_core::arena::{ArenaStore, NodeKind, SegmentKind};
use catseq_frontend::{SourceModule, lower_sequence_hir};

fn lower(source: &str) -> (ArenaStore, catseq_frontend::SourceArenaProgram) {
    let module = SourceModule::parse("sequence.py", source).unwrap();
    let hir = Arc::new(module.lower_sequence("sequence").unwrap());
    let store = ArenaStore::new();
    let segment = store.create_segment(SegmentKind::Program);
    let program = lower_sequence_hir(hir, &store, segment).unwrap();
    (store, program)
}

#[test]
fn source_hir_compositions_lower_into_one_shared_rust_arena() {
    let (store, program) =
        lower("@arena_build\ndef sequence():\n    return first() >> (second() | third())\n");

    assert_eq!(store.segment_node_count(program.segment()).unwrap(), 5);
    let root = store.node(program.root()).unwrap();
    assert_eq!(root.kind(), NodeKind::AutoSerial);
    let (Some(left), Some(right)) = root.children() else {
        panic!("serial root should have two children")
    };
    assert_eq!(store.node(left).unwrap().kind(), NodeKind::SourceCall);
    assert_eq!(store.node(right).unwrap().kind(), NodeKind::Parallel);
    assert_eq!(program.frozen().reachable_storage_node_count().unwrap(), 5);
}

#[test]
fn local_hir_sharing_does_not_copy_arena_prefixes() {
    let (store, program) = lower(
        "@arena_build\ndef sequence():\n    prefix = first() >> second()\n    return prefix >> third()\n",
    );

    assert_eq!(store.segment_node_count(program.segment()).unwrap(), 5);
    assert_eq!(program.frozen().reachable_storage_node_count().unwrap(), 5);
}

#[test]
fn channel_dictionary_is_retained_as_a_deferred_hir_payload() {
    let (store, program) =
        lower("@arena_build\ndef sequence():\n    return first() >> {channel: transition()}\n");

    assert_eq!(store.segment_node_count(program.segment()).unwrap(), 2);
    let root = store.node(program.root()).unwrap();
    assert_eq!(root.kind(), NodeKind::DeferredApply);
    assert!(root.children().0.is_some());
    assert!(root.children().1.is_none());
    assert!(matches!(
        program
            .hir()
            .expression(catseq_frontend::ExpressionId::from_index(root.payload_id()))
            .kind(),
        catseq_frontend::HirKind::Dictionary(_)
    ));
}

#[test]
fn scalar_hir_root_is_rejected_as_a_non_morphism() {
    let module = SourceModule::parse(
        "invalid.py",
        "@arena_build\ndef sequence():\n    return 42\n",
    )
    .unwrap();
    let hir = Arc::new(module.lower_sequence("sequence").unwrap());
    let store = ArenaStore::new();
    let segment = store.create_segment(SegmentKind::Program);

    let error = lower_sequence_hir(hir, &store, segment).unwrap_err();

    assert!(error.to_string().contains("literal"));
    assert!(error.to_string().contains("Morphism"));
}
