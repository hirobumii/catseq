use std::collections::{BTreeMap, BTreeSet};

use catseq_frontend::{
    check_typed_bundle_entry_with_loader,
    check_typed_bundle_entry_with_loader_and_opaque_definitions,
};

fn modules() -> BTreeMap<String, String> {
    BTreeMap::from([
        (
            "experiment".to_owned(),
            "from calibration import amp_calib\n\ndef sequence():\n    return amp_calib()\n"
                .to_owned(),
        ),
        (
            "calibration".to_owned(),
            "def amp_calib():\n    raise RuntimeError('host encoder only')\n".to_owned(),
        ),
    ])
}

#[test]
fn compile_environment_opaque_definition_stops_source_reachability() {
    let modules = modules();
    let mut loader = |module: &str| Ok(modules.get(module).cloned());
    let opaque_definitions = BTreeSet::from(["calibration.amp_calib".to_owned()]);

    let report = check_typed_bundle_entry_with_loader_and_opaque_definitions(
        "experiment",
        "sequence",
        &opaque_definitions,
        &mut loader,
    )
    .unwrap();

    assert_eq!(report.definitions().len(), 1);
    assert_eq!(report.definitions()[0].qualified_name(), "sequence");
}

#[test]
fn an_unregistered_host_definition_remains_reachable() {
    let modules = modules();
    let mut loader = |module: &str| Ok(modules.get(module).cloned());

    let error =
        check_typed_bundle_entry_with_loader("experiment", "sequence", &mut loader).unwrap_err();

    assert!(error.to_string().contains("raise statement"), "{error}");
}
