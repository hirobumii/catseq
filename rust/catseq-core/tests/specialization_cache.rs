use std::cell::Cell;

use catseq_core::arena::{ArenaStore, SegmentKind};
use catseq_core::definitions::{
    DefinitionRegistry, SpecializationCache, SpecializationKey, TemplateSignature,
};

#[test]
fn definition_ids_are_stable_indices() {
    let store = ArenaStore::new();
    let arena = store.create_segment(SegmentKind::Template);
    let first_root = store.wait(arena, 1, 0).unwrap();
    let first_template = store.publish_template(first_root, 10).unwrap();

    let second_arena = store.create_segment(SegmentKind::Template);
    let second_root = store.wait(second_arena, 2, 0).unwrap();
    let second_template = store.publish_template(second_root, 20).unwrap();

    let mut definitions = DefinitionRegistry::new();
    let first = definitions.register_template(first_template, TemplateSignature::new(1, 2));
    let second = definitions.register_template(second_template, TemplateSignature::new(3, 4));

    assert_eq!(first.index(), 0);
    assert_eq!(second.index(), 1);
    assert_eq!(
        definitions.template(first).unwrap().template(),
        first_template
    );
    assert_eq!(
        definitions
            .template(second)
            .unwrap()
            .signature()
            .scan_slots(),
        3
    );
}

#[test]
fn identical_specialization_is_compiled_once_on_demand() {
    let mut cache = SpecializationCache::new();
    let definition = catseq_core::definitions::DefinitionId::from_index(7);
    let key = SpecializationKey::new(definition, 11, 12, 13);
    let compile_count = Cell::new(0);

    let first = cache.get_or_try_compile(key, || {
        compile_count.set(compile_count.get() + 1);
        Ok::<_, ()>(String::from("rtmq-relative-fragment"))
    });
    let second = cache.get_or_try_compile(key, || {
        compile_count.set(compile_count.get() + 1);
        Ok::<_, ()>(String::from("should-not-run"))
    });

    assert_eq!(first.unwrap().as_str(), "rtmq-relative-fragment");
    assert_eq!(second.unwrap().as_str(), "rtmq-relative-fragment");
    assert_eq!(compile_count.get(), 1);
    assert_eq!(cache.len(), 1);
}

#[test]
fn scan_values_do_not_participate_in_template_specialization() {
    let definition = catseq_core::definitions::DefinitionId::from_index(3);
    let before_scan_update = SpecializationKey::new(definition, 21, 22, 23);
    let after_scan_update = SpecializationKey::new(definition, 21, 22, 23);
    let changed_calibration = SpecializationKey::new(definition, 21, 22, 24);

    assert_eq!(before_scan_update, after_scan_update);
    assert_ne!(before_scan_update, changed_calibration);
}
