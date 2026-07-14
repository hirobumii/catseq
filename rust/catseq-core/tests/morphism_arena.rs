use catseq_core::morphism_arena::{
    BoundaryPolicy, MorphismArenaBuilder, MorphismNodeKind, NativeProvenance,
};

#[test]
fn canonical_arena_flattens_composition_and_discards_builder_intermediates() {
    let mut builder = MorphismArenaBuilder::new();
    let provenance = builder.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
    let a = builder.definition_ref("service.a", &[], provenance);
    let b = builder.definition_ref("service.b", &[], provenance);
    let c = builder.definition_ref("service.c", &[], provenance);
    let ab = builder.serial(&[a, b], &[BoundaryPolicy::Auto], provenance);
    let root = builder.serial(&[ab, c], &[BoundaryPolicy::Strict], provenance);

    let arena = builder.finish(root).unwrap();
    let root = arena.root();
    let node = arena.node(root).unwrap();

    assert_eq!(node.kind(), MorphismNodeKind::Serial);
    assert_eq!(arena.children(root).unwrap().len(), 3);
    assert_eq!(
        arena.boundaries(root).unwrap(),
        [BoundaryPolicy::Auto, BoundaryPolicy::Strict]
    );
    assert_eq!(
        arena.nodes().len(),
        4,
        "three leaves plus one variadic Serial"
    );
    arena.validate().unwrap();
}

#[test]
fn canonical_arena_represents_parallel_as_one_variadic_node() {
    let mut builder = MorphismArenaBuilder::new();
    let provenance = builder.intern_provenance(NativeProvenance::new("test.sequence", 2, 3));
    let pulse_body = builder.atomic("catseq.hardware.ttl.pulse", &[], provenance);
    let pulse_template = builder.publish_template(pulse_body);
    let hold_body = builder.atomic("catseq.hardware.common.hold", &[], provenance);
    let hold_template = builder.publish_template(hold_body);
    let pulse = builder.instantiate(pulse_template, "ttl0", provenance);
    let hold = builder.instantiate(hold_template, "ttl1", provenance);
    let sync = builder.parallel(&[pulse, hold], provenance);

    let arena = builder.finish(sync).unwrap();
    assert_eq!(
        arena.node(arena.root()).unwrap().kind(),
        MorphismNodeKind::Parallel
    );
    assert_eq!(arena.children(arena.root()).unwrap().len(), 2);
    assert_eq!(arena.operations().len(), 2);
    assert_eq!(arena.channels().len(), 2);
    arena.validate().unwrap();
}

#[test]
fn a_composite_template_body_is_shared_across_instantiations() {
    let mut builder = MorphismArenaBuilder::new();
    let provenance = builder.intern_provenance(NativeProvenance::new("test.sequence", 4, 5));
    let pulse = builder.atomic("catseq.hardware.ttl.pulse", &[], provenance);
    let hold = builder.atomic("catseq.hardware.common.hold", &[], provenance);
    let body = builder.serial(&[pulse, hold], &[BoundaryPolicy::Auto], provenance);
    let template = builder.publish_template(body);
    let ttl0 = builder.instantiate(template, "ttl0", provenance);
    let ttl1 = builder.instantiate(template, "ttl1", provenance);
    let root = builder.parallel(&[ttl0, ttl1], provenance);

    let arena = builder.finish(root).unwrap();
    assert_eq!(arena.templates().len(), 1);
    let template_root = arena.templates()[0].root();
    assert_eq!(
        arena.node(template_root).unwrap().kind(),
        MorphismNodeKind::Serial
    );
    assert_eq!(arena.children(template_root).unwrap().len(), 2);
    assert_eq!(arena.children(arena.root()).unwrap().len(), 2);
    assert!(
        arena
            .children(arena.root())
            .unwrap()
            .iter()
            .all(|child| arena.node(*child).unwrap().kind() == MorphismNodeKind::Instantiate)
    );
    arena.validate().unwrap();
}
