use catseq_frontend::{SourceType, check_typed_entry};

#[test]
fn imported_catseq_replace_preserves_the_native_record_type() {
    let report = check_typed_entry(
        "experiment",
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(target, freq=2.0)\n",
        "sequence",
    )
    .unwrap();
    let hir = report.definitions()[0].hir();
    let replace_type = hir
        .facts()
        .iter()
        .find(|fact| fact.resolved_definition() == Some("catseq.replace"))
        .and_then(|fact| fact.source_type());

    assert_eq!(
        replace_type,
        Some(&SourceType::NativeRecord("StaticWaveform".to_owned()))
    );
}

#[test]
fn a_source_function_named_replace_is_not_the_catseq_special_form() {
    let report = check_typed_entry(
        "experiment",
        "def replace(value: float) -> float:\n    return value + 1.0\n\ndef sequence() -> float:\n    return replace(1.0)\n",
        "sequence",
    )
    .unwrap();
    let sequence = report
        .definitions()
        .iter()
        .find(|definition| definition.qualified_name() == "sequence")
        .unwrap();
    let replace_call = sequence
        .hir()
        .facts()
        .iter()
        .find(|fact| fact.resolved_definition() == Some("experiment.replace"))
        .unwrap();

    assert_eq!(replace_call.source_type(), Some(&SourceType::Float64));
    assert!(
        report
            .definitions()
            .iter()
            .any(|definition| definition.qualified_name() == "experiment.replace")
    );
}
