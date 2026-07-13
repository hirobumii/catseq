use catseq_core::arena::{ArenaStore, NodeKind, SegmentKind};

#[test]
fn composition_appends_to_one_shared_store() {
    let store = ArenaStore::new();
    let program = store.create_segment(SegmentKind::Program);
    let left = store.atomic(program, 10, 0b01, 0).unwrap();
    let right = store.atomic(program, 11, 0b10, 0).unwrap();

    let root = store
        .compose(program, NodeKind::AutoSerial, left, right, 7)
        .unwrap();

    assert_eq!(store.segment_node_count(program).unwrap(), 3);
    assert_eq!(
        store.node(root).unwrap().children(),
        (Some(left), Some(right))
    );
    assert_eq!(store.node(root).unwrap().channel_mask(), 0b11);
}

#[test]
fn template_instantiation_adds_one_node_without_copying_template() {
    let store = ArenaStore::new();
    let template_segment = store.create_segment(SegmentKind::Template);
    let first = store.atomic(template_segment, 20, 0b01, 0).unwrap();
    let second = store.wait(template_segment, 21, 0).unwrap();
    let template_root = store
        .compose(template_segment, NodeKind::AutoSerial, first, second, 0)
        .unwrap();
    let template = store.publish_template(template_root, 3).unwrap();
    let template_nodes = store.segment_node_count(template_segment).unwrap();

    let program = store.create_segment(SegmentKind::Program);
    let instance = store.instantiate(program, template, 5, 0b100, 9).unwrap();
    let frozen = store.freeze(instance).unwrap();

    assert_eq!(template_nodes, 3);
    assert_eq!(store.segment_node_count(template_segment).unwrap(), 3);
    assert_eq!(store.segment_node_count(program).unwrap(), 1);
    assert_eq!(frozen.reachable_storage_node_count().unwrap(), 4);
    assert_eq!(frozen.template_instance_count().unwrap(), 1);
}

#[test]
fn frozen_root_is_stable_while_the_program_keeps_growing() {
    let store = ArenaStore::new();
    let program = store.create_segment(SegmentKind::Program);
    let root = store.atomic(program, 30, 0b1, 0).unwrap();
    let frozen = store.freeze(root).unwrap();

    let later = store.atomic(program, 31, 0b10, 0).unwrap();
    store
        .compose(program, NodeKind::Parallel, root, later, 0)
        .unwrap();

    assert_eq!(frozen.root(), root);
    assert_eq!(frozen.reachable_storage_node_count().unwrap(), 1);
    assert_eq!(store.segment_node_count(program).unwrap(), 3);
}

#[test]
fn legacy_columns_are_exported_from_native_storage_in_node_order() {
    let store = ArenaStore::new();
    let program = store.create_segment(SegmentKind::Program);
    let left = store.atomic(program, 0, 0b01, 4).unwrap();
    let right = store.wait(program, 1, 5).unwrap();
    store
        .append_raw(
            program,
            NodeKind::DeferredApply,
            Some(left),
            None,
            2,
            0b01,
            6,
        )
        .unwrap();
    store
        .compose(program, NodeKind::AutoSerial, left, right, 7)
        .unwrap();

    let columns = store.export_segment(program).unwrap();

    assert_eq!(
        columns.kinds,
        vec![
            NodeKind::Atomic,
            NodeKind::Wait,
            NodeKind::DeferredApply,
            NodeKind::AutoSerial,
        ]
    );
    assert_eq!(columns.left, vec![None, None, Some(left), Some(left)]);
    assert_eq!(columns.right, vec![None, None, None, Some(right)]);
    assert_eq!(columns.payload_ids, vec![0, 1, 2, 0]);
    assert_eq!(columns.channel_masks, vec![0b01, 0, 0b01, 0b01]);
    assert_eq!(columns.provenance_ids, vec![4, 5, 6, 7]);
}
