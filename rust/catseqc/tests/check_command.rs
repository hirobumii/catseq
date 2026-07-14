use std::fs;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn source_file() -> std::path::PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("catseqc-source-{nonce}.py"));
    fs::write(
        &path,
        "class Experiment:\n    @arena_build\n    def sequence(self, params: ExpParams):\n        return identity(params[self.delay])\n",
    )
    .unwrap();
    path
}

#[test]
fn binary_discovers_requested_sequence_entry_from_source() {
    let path = source_file();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("Experiment.sequence"));
    assert!(stdout.contains("1 definitions"), "{stdout}");
    assert!(stdout.contains("typed HIR nodes"), "{stdout}");
}

#[test]
fn binary_rejects_an_unknown_sequence_entry() {
    let path = source_file();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.missing",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("not found"));
}

#[test]
fn binary_rejects_python_outside_the_restricted_sequence_language() {
    let path = source_file();
    fs::write(
        &path,
        "@arena_build\ndef sequence(flag: bool):\n    while flag:\n        side_effect()\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("while"), "{stderr}");
}

#[test]
fn binary_rejects_scan_values_that_change_channel_topology() {
    let path = source_file();
    fs::write(
        &path,
        "@arena_build\ndef sequence(params: ExpParams):\n    return {params[channel]: identity(1)}\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Link value"), "{stderr}");
    assert!(stderr.contains("Structural"), "{stderr}");
}

#[test]
fn binary_reports_the_entry_type_signature_as_structured_check_output() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, arena_build, identity\n\n@arena_build\ndef sequence(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema_version"], 1);
    assert_eq!(report["entry"], "sequence");
    assert_eq!(report["definitions"][0]["qualified_name"], "sequence");
    assert_eq!(
        report["definitions"][0]["parameters"][0]["name"],
        "duration"
    );
    assert_eq!(report["definitions"][0]["parameters"][0]["type"], "Float64");
    assert_eq!(report["definitions"][0]["return_type"], "Morphism");
    assert_eq!(report["diagnostics"], serde_json::json!([]));
    assert!(report["incremental"]["executed"].as_u64().is_some());
    assert!(report["incremental"]["green"].as_u64().is_some());
}

#[test]
fn explicit_check_entry_does_not_require_an_arena_build_decorator() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\nclass RydbergTransferExp:\n    def build_sequence(self, params: ExpParams) -> Morphism:\n        return identity(params[self.pulse_time])\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "RydbergTransferExp.build_sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let definition = &report["definitions"][0];
    assert_eq!(
        definition["qualified_name"],
        "RydbergTransferExp.build_sequence"
    );
    assert_eq!(definition["parameters"][0]["name"], "self");
    assert_eq!(
        definition["parameters"][0]["type"],
        "Instance<RydbergTransferExp>"
    );
    assert_eq!(definition["parameters"][1]["name"], "params");
    assert_eq!(definition["parameters"][1]["type"], "ScanBindings");
    assert_eq!(definition["return_type"], "Morphism");
}

#[test]
fn unchanged_check_reuses_queries_from_the_previous_process() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef sequence(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();
    let cache_dir = path.with_extension("incremental");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                path.to_str().unwrap(),
                "--entry",
                "sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let first_output = run();
    assert!(
        first_output.status.success(),
        "{}",
        String::from_utf8_lossy(&first_output.stderr)
    );
    let first: serde_json::Value = serde_json::from_slice(&first_output.stdout).unwrap();
    let second_output = run();
    assert!(
        second_output.status.success(),
        "{}",
        String::from_utf8_lossy(&second_output.stderr)
    );
    let second: serde_json::Value = serde_json::from_slice(&second_output.stdout).unwrap();

    fs::remove_file(path).unwrap();
    fs::remove_dir_all(cache_dir).unwrap();

    assert!(first["incremental"]["executed"].as_u64().unwrap() >= 2);
    assert_eq!(first["incremental"]["green"], 0);
    assert_eq!(second["incremental"]["executed"], 0);
    assert!(second["incremental"]["green"].as_u64().unwrap() >= 2);
    assert_eq!(second["incremental"]["red"], 0);
    assert!(
        second["incremental"]["result_cache_loads"]
            .as_u64()
            .unwrap()
            >= 1
    );
    assert!(second["incremental"]["bytes_read"].as_u64().unwrap() > 0);
    assert_eq!(second["incremental"]["bytes_written"], 0);
    assert!(
        second["incremental"]["fingerprint_nanos"]
            .as_u64()
            .is_some()
    );
    assert!(second["incremental"]["executed_by_kind"].is_object());
    assert_eq!(second["definitions"], first["definitions"]);
}

#[test]
fn comment_only_change_stops_after_the_parser_semantic_fingerprint() {
    let path = source_file();
    let source = "from catseq.morphism import Morphism, identity\n\ndef sequence(duration: float) -> Morphism:\n    return identity(duration)\n";
    fs::write(&path, source).unwrap();
    let cache_dir = path.with_extension("incremental");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                path.to_str().unwrap(),
                "--entry",
                "sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let first_output = run();
    assert!(first_output.status.success());
    let first: serde_json::Value = serde_json::from_slice(&first_output.stdout).unwrap();
    fs::write(&path, format!("# host-only comment\n{source}")).unwrap();
    let second_output = run();
    assert!(
        second_output.status.success(),
        "{}",
        String::from_utf8_lossy(&second_output.stderr)
    );
    let second: serde_json::Value = serde_json::from_slice(&second_output.stdout).unwrap();

    fs::remove_file(path).unwrap();
    fs::remove_dir_all(cache_dir).unwrap();

    assert_eq!(second["incremental"]["executed"], 1);
    assert!(second["incremental"]["green"].as_u64().unwrap() >= 2);
    assert_eq!(second["definitions"], first["definitions"]);
}

#[test]
fn check_follows_reachable_definitions_across_the_source_bundle() {
    let entry_path = source_file();
    let source_root = entry_path.with_extension("bundle");
    fs::create_dir(&source_root).unwrap();
    let entry_path = source_root.join("experiment.py");
    let service_path = source_root.join("services.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom services import pulse\n\ndef sequence(duration: float) -> Morphism:\n    return pulse(duration)\n",
    )
    .unwrap();
    fs::write(
        &service_path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            entry_path.to_str().unwrap(),
            "--source-root",
            source_root.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_dir_all(source_root).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let names: Vec<_> = report["definitions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|definition| definition["qualified_name"].as_str().unwrap())
        .collect();
    assert_eq!(names, ["sequence", "services.pulse"]);
    assert_eq!(report["definitions"][1]["parameters"][0]["type"], "Float64");
    assert_eq!(report["definitions"][1]["return_type"], "Morphism");
    let entry_hir = &report["definitions"][0]["hir"];
    let call = entry_hir["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|node| node["kind"] == "call" && node["symbol"] == "pulse")
        .unwrap();
    let fact = &entry_hir["facts"][call["id"].as_u64().unwrap() as usize];
    assert_eq!(fact["resolved_definition"], "services.pulse");
    assert_eq!(fact["type"], "Morphism");
}

#[test]
fn reachable_service_singleton_resolves_to_its_compile_class_method() {
    let root = source_file().with_extension("bundle");
    fs::create_dir(&root).unwrap();
    let entry_path = root.join("experiment.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom services import service\n\ndef sequence(duration: float) -> Morphism:\n    return service.pulse(duration)\n",
    )
    .unwrap();
    fs::write(
        root.join("services.py"),
        "from catseq.morphism import Morphism, identity\n\nclass Service:\n    def pulse(self, duration: float) -> Morphism:\n        return identity(duration)\n\nservice = Service()\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            entry_path.to_str().unwrap(),
            "--source-root",
            root.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_dir_all(root).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        report["definitions"][1]["qualified_name"],
        "services.Service.pulse"
    );
    assert_eq!(
        report["definitions"][1]["parameters"][0]["type"],
        "Instance<Service>"
    );
}

#[test]
fn compile_discriminated_optional_annotation_has_a_native_source_type() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(frequency: float | None) -> Morphism:\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "pulse",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        report["definitions"][0]["parameters"][0]["type"],
        "Optional<Float64>"
    );
}

#[test]
fn unannotated_numeric_parameter_is_inferred_from_restricted_arithmetic() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(phi, duration: float) -> Morphism:\n    shifted = phi + duration\n    return identity(shifted)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "pulse",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["definitions"][0]["parameters"][0]["type"], "Float64");
}

#[test]
fn unannotated_return_type_is_inferred_from_flat_hir() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import identity\n\ndef pulse(duration: float):\n    morphism = identity(duration)\n    return morphism\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "pulse",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["definitions"][0]["return_type"], "Morphism");
}

#[test]
fn legacy_repeat_sequence_handle_is_erased_and_self_calls_remain_reachable() {
    let root = source_file().with_extension("bundle");
    fs::create_dir(&root).unwrap();
    let entry_path = root.join("experiment.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom services import service\n\nclass Experiment:\n    def sequence(self, count: int) -> Morphism:\n        return service.prepare(self.seq, count)\n",
    )
    .unwrap();
    fs::write(
        root.join("services.py"),
        "from catseq import repeat_morphism\nfrom catseq.morphism import Morphism, identity\n\nclass Service:\n    def prepare(self, seq, count: int) -> Morphism:\n        return self._repeat(seq, count)\n\n    def _repeat(self, seq, count: int) -> Morphism:\n        return repeat_morphism(identity(1), count, seq)\n\nservice = Service()\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            entry_path.to_str().unwrap(),
            "--source-root",
            root.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_dir_all(root).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let definitions = report["definitions"].as_array().unwrap();
    let names: Vec<_> = definitions
        .iter()
        .map(|definition| definition["qualified_name"].as_str().unwrap())
        .collect();
    assert_eq!(
        names,
        [
            "Experiment.sequence",
            "services.Service.prepare",
            "services.Service._repeat"
        ]
    );
    for definition in definitions {
        assert!(
            definition["parameters"]
                .as_array()
                .unwrap()
                .iter()
                .all(|parameter| parameter["name"] != "seq")
        );
    }
}

#[test]
fn legacy_end_state_access_reports_the_required_implicit_state_migration() {
    let root = source_file().with_extension("bundle");
    let system = root.join("rb1system");
    fs::create_dir_all(&system).unwrap();
    fs::write(root.join("__init__.py"), "").unwrap();
    fs::write(system.join("__init__.py"), "").unwrap();
    let entry_path = root.join("experiment.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom rb1system.utils import get_end_state\n\ndef sequence(body: Morphism) -> Morphism:\n    state = get_end_state(body)\n    return body\n",
    )
    .unwrap();
    fs::write(
        system.join("utils.py"),
        "from typing import Mapping\nfrom catseq.morphism import Morphism\n\ndef get_end_state(body: Morphism) -> Mapping[str, object]:\n    return {}\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            entry_path.to_str().unwrap(),
            "--source-root",
            root.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_dir_all(root).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("get_end_state"), "{stderr}");
    assert!(stderr.contains("implicit Morphism state flow"), "{stderr}");
}

#[test]
fn forwarded_legacy_state_edge_is_erased_from_reachable_signatures() {
    let root = source_file().with_extension("bundle");
    let system = root.join("rb1system");
    fs::create_dir_all(&system).unwrap();
    fs::write(system.join("__init__.py"), "").unwrap();
    let entry_path = root.join("experiment.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom rb1system.utils import get_end_state\nfrom service import continue_from\n\ndef sequence(body: Morphism) -> Morphism:\n    state = get_end_state(body)\n    return continue_from(state)\n",
    )
    .unwrap();
    fs::write(
        root.join("service.py"),
        "from catseq.morphism import Morphism, identity\nfrom catseq.types.common import State\n\ndef continue_from(start_state: State) -> Morphism:\n    return identity(1)\n",
    )
    .unwrap();
    fs::write(
        system.join("utils.py"),
        "def get_end_state(body):\n    return object()\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            entry_path.to_str().unwrap(),
            "--source-root",
            root.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_dir_all(root).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["definitions"].as_array().unwrap().len(), 2);
    assert!(
        report["definitions"][1]["parameters"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(
        report["definitions"][0]["hir"]["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .all(|node| node["symbol"] != "get_end_state" && node["symbol"] != "state")
    );
}

#[test]
fn source_bundle_cache_tracks_only_compile_reachable_modules() {
    let root = source_file().with_extension("bundle");
    fs::create_dir(&root).unwrap();
    let entry_path = root.join("experiment.py");
    let service_path = root.join("services.py");
    let host_path = root.join("host.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom services import pulse\n\ndef sequence(duration: float) -> Morphism:\n    return pulse(duration)\n",
    )
    .unwrap();
    fs::write(
        &service_path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();
    fs::write(&host_path, "def prepare():\n    return 1\n").unwrap();
    let cache_dir = root.join("incremental");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                entry_path.to_str().unwrap(),
                "--source-root",
                root.to_str().unwrap(),
                "--entry",
                "sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let first_output = run();
    assert!(
        first_output.status.success(),
        "{}",
        String::from_utf8_lossy(&first_output.stderr)
    );
    let first: serde_json::Value = serde_json::from_slice(&first_output.stdout).unwrap();
    let second_output = run();
    assert!(second_output.status.success());
    let second: serde_json::Value = serde_json::from_slice(&second_output.stdout).unwrap();

    fs::write(&host_path, "def prepare():\n    return 2\n").unwrap();
    let host_change_output = run();
    assert!(host_change_output.status.success());
    let host_change: serde_json::Value =
        serde_json::from_slice(&host_change_output.stdout).unwrap();

    fs::write(
        &service_path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(duration: float) -> Morphism:\n    return identity(duration + 1.0)\n",
    )
    .unwrap();
    let reachable_change_output = run();
    assert!(reachable_change_output.status.success());
    let reachable_change: serde_json::Value =
        serde_json::from_slice(&reachable_change_output.stdout).unwrap();

    fs::remove_dir_all(root).unwrap();

    assert!(first["incremental"]["executed"].as_u64().unwrap() >= 3);
    assert_eq!(second["incremental"]["executed"], 0);
    assert_eq!(host_change["incremental"]["executed"], 0);
    assert!(
        reachable_change["incremental"]["executed"]
            .as_u64()
            .unwrap()
            >= 2
    );
    assert_eq!(
        reachable_change["incremental"]["executed_by_kind"]["LowerSourceHir"],
        1
    );
    assert_eq!(
        reachable_change["incremental"]["executed_by_kind"]["DefinitionHeader"],
        serde_json::Value::Null
    );
    assert_eq!(
        reachable_change["definitions"][1]["return_type"],
        first["definitions"][1]["return_type"]
    );
}

#[test]
fn compile_visible_field_change_invalidates_only_its_definition_revision() {
    let root = source_file().with_extension("bundle");
    fs::create_dir(&root).unwrap();
    let entry_path = root.join("experiment.py");
    let source = |amplitude: f64| {
        format!(
            "from catseq.morphism import Morphism, identity\n\nclass Experiment:\n    amplitude: float = {amplitude}\n\n    def sequence(self) -> Morphism:\n        return identity(self.amplitude)\n"
        )
    };
    fs::write(&entry_path, source(0.1)).unwrap();
    let cache_dir = root.join("incremental");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                entry_path.to_str().unwrap(),
                "--source-root",
                root.to_str().unwrap(),
                "--entry",
                "Experiment.sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let first_output = run();
    assert!(first_output.status.success());
    let first: serde_json::Value = serde_json::from_slice(&first_output.stdout).unwrap();
    fs::write(&entry_path, source(0.2)).unwrap();
    let changed_output = run();
    assert!(
        changed_output.status.success(),
        "{}",
        String::from_utf8_lossy(&changed_output.stderr)
    );
    let changed: serde_json::Value = serde_json::from_slice(&changed_output.stdout).unwrap();
    fs::remove_dir_all(root).unwrap();

    assert_eq!(
        changed["incremental"]["executed_by_kind"]["LowerSourceHir"],
        1
    );
    assert_eq!(
        changed["incremental"]["executed_by_kind"]["DefinitionHeader"],
        serde_json::Value::Null
    );
    let compile_values = |report: &serde_json::Value| {
        report["definitions"][0]["hir"]["facts"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|fact| fact["compile_value"].as_str())
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };
    assert_ne!(compile_values(&first), compile_values(&changed));
}

#[test]
fn typed_check_returns_flat_definition_hir_with_scan_semantic_facts() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\nclass Experiment:\n    def sequence(self, params: ExpParams) -> Morphism:\n        pulse_time = params[self.pulse_time] * us\n        return identity(pulse_time)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let hir = &report["definitions"][0]["hir"];
    let nodes = hir["nodes"].as_array().unwrap();
    let facts = hir["facts"].as_array().unwrap();
    assert!(!nodes.is_empty());
    assert_eq!(nodes.len(), facts.len());
    assert!(!hir["roots"].as_array().unwrap().is_empty());

    let subscript = nodes
        .iter()
        .find(|node| node["kind"] == "subscript")
        .unwrap();
    let fact = &facts[subscript["id"].as_u64().unwrap() as usize];
    assert_eq!(fact["type"], "Float64");
    assert_eq!(fact["availability"], "link");
    assert!(
        fact["roles"]
            .as_array()
            .unwrap()
            .contains(&serde_json::json!("relocatable"))
    );

    for node in nodes {
        let edge_start = node["edge_start"].as_u64().unwrap() as usize;
        let edge_count = node["edge_count"].as_u64().unwrap() as usize;
        assert!(edge_start + edge_count <= hir["edges"].as_array().unwrap().len());
    }
}

#[test]
fn registered_phase_tracker_attribute_has_a_phase_frame_fact() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\nclass Module:\n    def pulse(self) -> Morphism:\n        current_phase = self._tracker.phase\n        self._tracker.phase = 0.0\n        return identity(current_phase)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "Module.pulse",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let hir = &report["definitions"][0]["hir"];
    let (node, fact) = hir["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .zip(hir["facts"].as_array().unwrap())
        .find(|(node, _)| node["symbol"] == "self._tracker.phase")
        .unwrap();
    assert_eq!(node["kind"], "attribute");
    assert_eq!(fact["type"], "Float64");
    assert_eq!(fact["phase_frame"], "self._tracker");
}

#[test]
fn typed_check_rejects_link_values_used_as_structural_channel_keys() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef sequence(params: ExpParams) -> Morphism:\n    return {params[channel_param]: identity(1)}\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Link value"), "{stderr}");
    assert!(stderr.contains("Structural"), "{stderr}");
    assert!(stderr.contains(":4:"), "{stderr}");
}

#[test]
fn reachable_host_call_reports_a_source_anchored_diagnostic() {
    let path = source_file();
    fs::write(
        &path,
        "import time\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    time.sleep(1.0)\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("reachable Host call"), "{stderr}");
    assert!(stderr.contains("time.sleep"), "{stderr}");
    assert!(stderr.contains(":5:"), "{stderr}");
}

#[test]
fn incompatible_return_type_reports_a_source_anchored_diagnostic() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism\n\ndef sequence() -> Morphism:\n    return 1\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "check",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("type mismatch"), "{stderr}");
    assert!(stderr.contains("expected Morphism"), "{stderr}");
    assert!(stderr.contains("found Int64"), "{stderr}");
    assert!(stderr.contains(":4:"), "{stderr}");
}

#[test]
fn failed_check_preserves_the_last_successful_incremental_session() {
    let path = source_file();
    let valid_source = "from catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(1)\n";
    fs::write(&path, valid_source).unwrap();
    let cache_dir = path.with_extension("incremental");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                path.to_str().unwrap(),
                "--entry",
                "sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let first_output = run();
    assert!(first_output.status.success());
    let first: serde_json::Value = serde_json::from_slice(&first_output.stdout).unwrap();

    fs::write(
        &path,
        "import time\nfrom catseq.morphism import Morphism\n\ndef sequence() -> Morphism:\n    time.sleep(1.0)\n",
    )
    .unwrap();
    let failed_output = run();
    assert!(!failed_output.status.success());
    assert!(String::from_utf8_lossy(&failed_output.stderr).contains("reachable Host call"));

    fs::write(&path, valid_source).unwrap();
    let restored_output = run();
    assert!(
        restored_output.status.success(),
        "{}",
        String::from_utf8_lossy(&restored_output.stderr)
    );
    let restored: serde_json::Value = serde_json::from_slice(&restored_output.stdout).unwrap();

    fs::remove_file(path).unwrap();
    fs::remove_dir_all(cache_dir).unwrap();

    assert_eq!(restored["incremental"]["executed"], 0);
    assert_eq!(restored["definitions"], first["definitions"]);
}

#[test]
fn real_rydberg_transfer_reuses_the_definition_segmented_hir() {
    let source_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../rb1-next")
        .canonicalize();
    let Ok(source_root) = source_root else {
        // The sibling application is present in the development workspace but
        // is not required when the CatSeq repository is tested in isolation.
        return;
    };
    let entry_path = source_root.join("experiments/computing/rydberg_transfer.py");
    if !entry_path.exists() {
        return;
    }
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let cache_dir = std::env::temp_dir().join(format!("catseqc-rydberg-{nonce}"));
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "check",
                entry_path.to_str().unwrap(),
                "--source-root",
                source_root.to_str().unwrap(),
                "--entry",
                "RydbergTransferExp.build_sequence",
                "--format",
                "json",
                "--cache-dir",
                cache_dir.to_str().unwrap(),
            ])
            .output()
            .unwrap()
    };

    let cold_output = run();
    assert!(
        cold_output.status.success(),
        "{}",
        String::from_utf8_lossy(&cold_output.stderr)
    );
    let cold: serde_json::Value = serde_json::from_slice(&cold_output.stdout).unwrap();
    let warm_output = run();
    assert!(
        warm_output.status.success(),
        "{}",
        String::from_utf8_lossy(&warm_output.stderr)
    );
    let warm: serde_json::Value = serde_json::from_slice(&warm_output.stdout).unwrap();
    fs::remove_dir_all(cache_dir).unwrap();

    assert_eq!(cold["entry"], "RydbergTransferExp.build_sequence");
    assert_eq!(cold["definitions"].as_array().unwrap().len(), 29);
    assert_eq!(warm["incremental"]["executed"], 0);
    assert!(warm["incremental"]["green"].as_u64().unwrap() > 100);
    assert_eq!(warm["definitions"], cold["definitions"]);

    for definition in cold["definitions"].as_array().unwrap() {
        let nodes = definition["hir"]["nodes"].as_array().unwrap();
        let facts = definition["hir"]["facts"].as_array().unwrap();
        assert_eq!(nodes.len(), facts.len());
        for (node, fact) in nodes.iter().zip(facts) {
            let symbol = node["symbol"].as_str().unwrap_or_default();
            assert_ne!(symbol, "get_end_state");
            assert_ne!(symbol, "default_state");
            if node["kind"] == "call" {
                assert!(
                    fact["resolved_definition"].is_string(),
                    "unresolved call {symbol} in {}",
                    definition["qualified_name"]
                );
                assert!(
                    fact["type"].is_string(),
                    "untyped call {symbol} in {}",
                    definition["qualified_name"]
                );
            }
        }
    }
}
