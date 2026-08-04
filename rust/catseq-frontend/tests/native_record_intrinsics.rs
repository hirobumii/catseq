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
