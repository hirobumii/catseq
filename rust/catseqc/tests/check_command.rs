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

fn ttl_target_profile(source_path: &std::path::Path) -> std::path::PathBuf {
    let path = source_path.with_extension("target.json");
    fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": 250_000_000_u64,
            "boards": {
                "main": {"kind": "main", "ttl_width": 32},
                "rwg0": {"kind": "rwg", "ttl_width": 32}
            },
            "operations": {
                "catseq.hardware.ttl.set_high": {
                    "lowering": "ttl_set_high",
                    "instruction_cost_cycles": 0
                },
                "catseq.hardware.ttl.set_low": {
                    "lowering": "ttl_set_low",
                    "instruction_cost_cycles": 0
                }
            }
        }))
        .unwrap(),
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
    fs::remove_file(&path).unwrap();

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
fn unsupported_expression_is_not_silently_dropped_from_hir() {
    let path = source_file();
    fs::write(&path, "def sequence() -> str:\n    return f'value={1}'\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("formatted string"), "{stderr}");
    assert!(stderr.contains(":2:"), "{stderr}");
}

#[test]
fn oasm_black_box_definition_is_an_opaque_atomic_boundary() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism\n\ndef sequence() -> Morphism:\n    return legacy_atomic()\n\ndef legacy_atomic() -> Morphism:\n    while True:\n        break\n    return oasm_black_box({})\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
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
    assert_eq!(report["definitions"].as_array().unwrap().len(), 1);
    let definition = &report["definitions"][0];
    let nodes = definition["hir"]["nodes"].as_array().unwrap();
    let facts = definition["hir"]["facts"].as_array().unwrap();
    let call = nodes
        .iter()
        .zip(facts)
        .find(|(node, _)| node["kind"] == "call" && node["symbol"] == "legacy_atomic")
        .unwrap();
    assert_eq!(call.1["type"], "Morphism");
    assert!(
        call.1["resolved_definition"]
            .as_str()
            .unwrap()
            .ends_with(".legacy_atomic")
    );
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
    fs::remove_file(&path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema_version"], 2);
    assert_eq!(report["entry"], "sequence");
    assert_eq!(report["definition_count"], 1);
    assert!(report["hir_node_count"].as_u64().unwrap() > 0);
    assert!(report.get("definitions").is_none());
    assert_eq!(
        report["entry_signature"]["parameters"][0]["name"],
        "duration"
    );
    assert_eq!(
        report["entry_signature"]["parameters"][0]["type"],
        "Float64"
    );
    assert_eq!(report["entry_signature"]["return_type"], "Morphism");
    assert_eq!(report["diagnostics"], serde_json::json!([]));
    assert!(report["incremental"]["executed"].as_u64().is_some());
    assert!(report["incremental"]["green"].as_u64().is_some());
}

#[test]
fn emit_hir_json_explicitly_outputs_the_definition_graph() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef sequence(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(&path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema_version"], 1);
    assert_eq!(report["entry"], "sequence");
    assert_eq!(report["definitions"][0]["qualified_name"], "sequence");
    assert!(
        !report["definitions"][0]["hir"]["nodes"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn invalid_emit_hir_format_is_rejected_before_compilation() {
    let path = source_file();
    let cache_dir = path.with_extension("incremental");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--format",
            "text",
            "--cache-dir",
            cache_dir.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("emit-hir requires --format json"));
    assert!(!cache_dir.exists());
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
    let signature = &report["entry_signature"];
    assert_eq!(report["entry"], "RydbergTransferExp.build_sequence");
    assert_eq!(signature["parameters"][0]["name"], "self");
    assert_eq!(
        signature["parameters"][0]["type"],
        "Instance<RydbergTransferExp>"
    );
    assert_eq!(signature["parameters"][1]["name"], "params");
    assert_eq!(signature["parameters"][1]["type"], "ScanBindings");
    assert_eq!(signature["return_type"], "Morphism");
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
        second["incremental"]["fingerprint_seconds"]
            .as_f64()
            .is_some()
    );
    assert!(second["incremental"]["executed_by_kind"].is_object());
    assert_eq!(second["entry_signature"], first["entry_signature"]);
}

#[test]
fn compact_check_does_not_load_the_full_hir_cache() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef sequence(duration: float) -> Morphism:\n    return identity(duration)\n",
    )
    .unwrap();
    let cache_dir = path.with_extension("incremental");
    let run = |command: &str| {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                command,
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

    assert!(run("check").status.success());
    let check_output = run("check");
    assert!(check_output.status.success());
    let check: serde_json::Value = serde_json::from_slice(&check_output.stdout).unwrap();
    let hir_output = run("emit-hir");
    assert!(hir_output.status.success());
    let hir: serde_json::Value = serde_json::from_slice(&hir_output.stdout).unwrap();

    fs::remove_file(path).unwrap();
    fs::remove_dir_all(cache_dir).unwrap();

    assert!(check.get("definitions").is_none());
    assert!(hir["definitions"].is_array());
    assert_eq!(check["incremental"]["executed"], 0);
    assert_eq!(hir["incremental"]["executed"], 0);
    assert!(
        check["incremental"]["bytes_read"].as_u64().unwrap()
            < hir["incremental"]["bytes_read"].as_u64().unwrap()
    );
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
    assert_eq!(second["entry_signature"], first["entry_signature"]);
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
            "emit-hir",
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
            "emit-hir",
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
fn static_property_comprehension_expands_compile_instance_calls() {
    let path = source_file();
    fs::write(
        &path,
        "from functools import reduce\nfrom catseq.morphism import Morphism, identity\n\nclass ModuleA:\n    def init(self) -> Morphism:\n        return identity(1)\n\nclass ModuleB:\n    def init(self) -> Morphism:\n        return identity(2)\n\nmodule_a = ModuleA()\nmodule_b = ModuleB()\n\nclass Service:\n    @property\n    def module_list(self) -> list[ModuleA | ModuleB]:\n        return [module_a, module_b]\n\n    def init(self) -> Morphism:\n        values = [module.init() for module in self.module_list]\n        return reduce(lambda left, right: left | right, values)\n\nservice = Service()\n\ndef sequence() -> Morphism:\n    return service.init()\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(&path).unwrap();

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
        .map(|definition| definition["qualified_name"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(
        names,
        vec![
            "sequence".to_owned(),
            format!("{}.Service.init", path.display()),
            format!("{}.Service.module_list", path.display()),
            format!("{}.ModuleA.init", path.display()),
            format!("{}.ModuleB.init", path.display()),
        ]
    );
    let service = &report["definitions"][1];
    let (call, fact) = service["hir"]["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .zip(service["hir"]["facts"].as_array().unwrap())
        .find(|(node, _)| node["kind"] == "call" && node["symbol"] == "module.init")
        .unwrap();
    assert_eq!(call["kind"], "call");
    assert_eq!(fact["resolved_definitions"].as_array().unwrap().len(), 2);
    assert_eq!(fact["type"], "Morphism");
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
            "emit-hir",
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
            "emit-hir",
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
            "emit-hir",
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
fn unannotated_return_type_flows_across_a_resolved_definition_call() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import identity\n\ndef sequence():\n    return helper()\n\ndef helper():\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
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
    assert_eq!(report["definitions"][0]["return_type"], "Morphism");
    assert_eq!(report["definitions"][1]["return_type"], "Morphism");
    let entry_hir = &report["definitions"][0]["hir"];
    let return_node = entry_hir["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|node| node["kind"] == "return")
        .unwrap();
    assert_eq!(
        entry_hir["facts"][return_node["id"].as_u64().unwrap() as usize]["type"],
        "Morphism"
    );
}

#[test]
fn unresolved_call_assignment_keeps_a_local_resolution_edge() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import identity\n\ndef sequence():\n    value = helper()\n    return value\n\ndef helper():\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
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
    assert_eq!(report["definitions"][0]["return_type"], "Morphism");
    let entry_hir = &report["definitions"][0]["hir"];
    let value_name = entry_hir["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .zip(entry_hir["facts"].as_array().unwrap())
        .find(|(node, fact)| {
            node["kind"] == "name" && node["symbol"] == "value" && fact["resolved_node"].is_u64()
        })
        .unwrap();
    assert!(value_name.1["resolved_node"].is_u64());
    assert_eq!(value_name.1["type"], "Morphism");
}

#[test]
fn declarative_repeat_self_calls_remain_reachable_without_host_handles() {
    let root = source_file().with_extension("bundle");
    fs::create_dir(&root).unwrap();
    let entry_path = root.join("experiment.py");
    fs::write(
        &entry_path,
        "from catseq.morphism import Morphism\nfrom services import service\n\nclass Experiment:\n    def sequence(self, count: int) -> Morphism:\n        return service.prepare(count)\n",
    )
    .unwrap();
    fs::write(
        root.join("services.py"),
        "from catseq.morphism import Morphism, identity, repeat_morphism\n\nclass Service:\n    def prepare(self, count: int) -> Morphism:\n        return self._repeat(count)\n\n    def _repeat(self, count: int) -> Morphism:\n        return repeat_morphism(identity(1), count)\n\nservice = Service()\n",
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-hir",
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
    assert!(definitions.iter().all(|definition| {
        definition["parameters"]
            .as_array()
            .unwrap()
            .iter()
            .all(|parameter| parameter["name"] != "seq")
    }));
}

#[test]
fn declarative_repeat_morphism_lowers_to_a_native_loop_node() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity, repeat_morphism\n\ndef sequence() -> Morphism:\n    return repeat_morphism(identity(1), 3)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
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
    assert!(
        report["morphism_arena"]["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .any(|node| node["kind"] == "loop"),
        "{report:#}"
    );
}

#[test]
fn declarative_repeat_morphism_rejects_a_non_positive_count() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity, repeat_morphism\n\ndef sequence() -> Morphism:\n    return repeat_morphism(identity(1), 0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
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
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("positive integer"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
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
            "emit-hir",
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
                "emit-hir",
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
                "emit-hir",
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
            "emit-hir",
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
            "emit-hir",
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
fn incompatible_resolved_call_return_reports_a_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef sequence() -> int:\n    return helper()\n\ndef helper() -> Morphism:\n    return identity(1)\n",
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
    assert!(stderr.contains("expected Int64"), "{stderr}");
    assert!(stderr.contains("found Morphism"), "{stderr}");
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
                "emit-hir",
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
fn emit_arena_returns_a_python_free_variadic_morphism_dag() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\nclass Experiment:\n    def sequence(self) -> Morphism:\n        return identity(1) >> identity(2) >> identity(3)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
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
    let artifact: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(artifact["entry"], "Experiment.sequence");
    assert_eq!(artifact["stage"], "morphism_arena");
    let arena = &artifact["morphism_arena"];
    let root = arena["root"].as_u64().unwrap() as usize;
    assert_eq!(arena["nodes"][root]["kind"], "serial");
    assert_eq!(arena["nodes"][root]["edge_count"], 3);
    let forbidden = [
        "source_call",
        "deferred_apply",
        "dictionary",
        "aggregate",
        "python_object",
    ];
    for node in arena["nodes"].as_array().unwrap() {
        assert!(!forbidden.contains(&node["kind"].as_str().unwrap()));
    }
}

#[test]
fn compile_emits_a_linked_oasm_call_plan_for_a_ttl_pulse() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(40 * ns)}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::ttl0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {
                    "board": "rwg0",
                    "local_id": 0,
                    "kind": "ttl"
                }
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["stage"], "oasm_call_plan");
    assert_eq!(response["entry"], "sequence");
    assert_eq!(response["logical_duration_cycles"], 10);
    assert_eq!(response["clock_hz"], 250_000_000_u64);
    let plan = &response["oasm_call_plan"];
    assert_eq!(plan["epochs"].as_array().unwrap().len(), 1);
    let board = &plan["epochs"][0]["boards"][0];
    assert_eq!(board["address"], "rwg0");
    assert_eq!(
        board["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 1, "function": "wait", "args": [9]},
            {"offset_cycles": 10, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
}

#[test]
fn compile_specializes_reachable_morphism_definitions_before_oasm_lowering() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef service(duration: float) -> Morphism:\n    return identity(0) >> {ttl0: pulse(duration)}\n\ndef sequence() -> Morphism:\n    return service(40 * ns)\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::ttl0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {"board": "rwg0", "local_id": 0, "kind": "ttl"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["logical_duration_cycles"], 10);
    assert_eq!(response["clock_hz"], 250_000_000_u64);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 1, "function": "wait", "args": [9]},
            {"offset_cycles": 10, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
}

#[test]
fn user_can_compile_a_morphism_template_composed_from_atomic_operations() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import hold, set_high, set_low\nfrom catseq.morphism import Morphism, MorphismDef, identity, morphism_template\nfrom catseq.time_utils import ns\n\n@morphism_template\ndef user_pulse(duration: float) -> MorphismDef:\n    return set_high() >> hold(duration) >> set_low()\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: user_pulse(40 * ns)}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::ttl0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {"board": "rwg0", "local_id": 0, "kind": "ttl"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);

    let arena_output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    assert!(
        arena_output.status.success(),
        "{}",
        String::from_utf8_lossy(&arena_output.stderr)
    );
    let artifact: serde_json::Value = serde_json::from_slice(&arena_output.stdout).unwrap();
    let arena = &artifact["morphism_arena"];
    let template_root = arena["templates"][0]["root"].as_u64().unwrap() as usize;
    assert_eq!(arena["nodes"][template_root]["kind"], "definition_ref");
    assert!(
        arena["operations"]
            .as_array()
            .unwrap()
            .iter()
            .all(|operation| !operation.as_str().unwrap().ends_with(".user_pulse"))
    );
    assert!(
        arena["definitions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|definition| definition.as_str().unwrap().ends_with(".user_pulse"))
    );

    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["logical_duration_cycles"], 10);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 1, "function": "wait", "args": [9]},
            {"offset_cycles": 10, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
}

#[test]
fn linear_ramp_is_a_structured_native_template_and_compiles_to_oasm() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.rwg import initialize, linear_ramp, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    setup = initialize(80.0) >> set_state([StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)])\n    ramp = linear_ramp([StaticWaveform(freq=2.0, amp=0.4)], 1 * us)\n    return identity(0) >> {rwg0: setup} >> {rwg0: ramp}\n",
    )
    .unwrap();

    let arena_output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    assert!(
        arena_output.status.success(),
        "{}",
        String::from_utf8_lossy(&arena_output.stderr)
    );
    let artifact: serde_json::Value = serde_json::from_slice(&arena_output.stdout).unwrap();
    let arena = &artifact["morphism_arena"];
    let templates = arena["templates"].as_array().unwrap();
    assert_eq!(templates.len(), 2);
    let ramp_root = templates[1]["root"].as_u64().unwrap() as usize;
    assert_eq!(arena["nodes"][ramp_root]["kind"], "serial");
    assert_eq!(arena["nodes"][ramp_root]["edge_count"], 5);
    let operations = arena["operations"].as_array().unwrap();
    assert!(operations.contains(&serde_json::json!("catseq.hardware.rwg.load")));
    assert!(operations.contains(&serde_json::json!("catseq.hardware.rwg.play")));
    assert!(!operations.contains(&serde_json::json!("catseq.hardware.rwg.set_state")));
    assert!(!operations.contains(&serde_json::json!(
        "catseq.hardware.rwg._load_linear_coefficients"
    )));
    assert!(!operations.contains(&serde_json::json!(
        "catseq.hardware.rwg._load_static_endpoint"
    )));
    assert!(!operations.contains(&serde_json::json!("catseq.hardware.rwg.linear_ramp")));
    let value_payloads = artifact["value_expr_arena"]["payloads"].as_array().unwrap();
    let waveform_derivations = value_payloads
        .iter()
        .filter(|payload| payload["kind"] == "rwg_waveforms")
        .map(|payload| payload["value"].as_str().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        waveform_derivations,
        vec!["static", "linear", "ramp_endpoint"]
    );

    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::rwg0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {"board": "rwg0", "local_id": 0, "kind": "rwg"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["logical_duration_cycles"], 250);
    let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["amp_coeffs"][1]
                .as_f64()
                .is_some_and(|slope| slope != 0.0)
    }));
    assert!(calls.iter().any(|call| {
        call["offset_cycles"].as_u64().unwrap() < 250
            && call["function"] == "rwg_load_waveform"
            && call["args"][0]["amp_coeffs"][0] == 0.4
    }));
    assert!(
        calls
            .iter()
            .any(|call| { call["offset_cycles"] == 250 && call["function"] == "rwg_play" }),
        "{calls:#?}"
    );
}

#[test]
fn user_template_can_compose_the_unified_rwg_load_and_play_atomics() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.rwg import initialize, load, play\nfrom catseq.morphism import Morphism, MorphismDef, identity, morphism_template\nfrom catseq.types import WaveformParams\n\n@morphism_template\ndef custom_state() -> MorphismDef:\n    params = [WaveformParams(sbg_id=0, freq_coeffs=(1.0, None, None, None), amp_coeffs=(0.2, None, None, None), initial_phase=0.0, phase_reset=True)]\n    return load(params) >> play()\n\ndef sequence() -> Morphism:\n    return identity(0) >> {rwg0: initialize(80.0) >> custom_state()}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::rwg0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {"board": "rwg0", "local_id": 0, "kind": "rwg"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["freq_coeffs"][0] == 1.0
            && call["args"][0]["amp_coeffs"][0] == 0.2
    }));
    assert!(calls.iter().any(|call| call["function"] == "rwg_play"));
}

#[test]
fn compile_binds_a_scan_duration_when_linking_the_oasm_call_plan() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\nclass Experiment:\n    def sequence(self, params: ExpParams) -> Morphism:\n        return identity(0) >> {ttl0: pulse(params[self.pulse_time] * us)}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::ttl0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {
                    "board": "rwg0",
                    "local_id": 0,
                    "kind": "ttl"
                }
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let link_bindings_path = path.with_extension("bindings.json");
    fs::write(
        &link_bindings_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "runtime_values": {"self.pulse_time": 0.02}
        }))
        .unwrap(),
    )
    .unwrap();
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_catseqc"))
            .args([
                "compile",
                path.to_str().unwrap(),
                "--entry",
                "Experiment.sequence",
                "--compile-environment",
                environment_path.to_str().unwrap(),
                "--target-profile",
                target_profile_path.to_str().unwrap(),
                "--link-bindings",
                link_bindings_path.to_str().unwrap(),
                "--format",
                "json",
            ])
            .output()
            .unwrap()
    };
    let output = run();
    fs::write(
        &link_bindings_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "runtime_values": {"self.pulse_time": 0.021}
        }))
        .unwrap(),
    )
    .unwrap();
    let nonintegral = run();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();
    fs::remove_file(link_bindings_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(!nonintegral.status.success());
    assert!(
        String::from_utf8_lossy(&nonintegral.stderr)
            .contains("exact non-negative target Cycle Count")
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["logical_duration_cycles"], 5);
    assert_eq!(response["clock_hz"], 250_000_000_u64);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 1, "function": "wait", "args": [4]},
            {"offset_cycles": 5, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
}

#[test]
fn compile_aligns_parallel_pulses_and_merges_same_board_ttl_writes() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(40 * ns), ttl1: pulse(20 * ns)}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let ttl0 = format!("{}::ttl0", path.display());
    let ttl1 = format!("{}::ttl1", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                ttl0: {"board": "rwg0", "local_id": 0, "kind": "ttl"},
                ttl1: {"board": "rwg0", "local_id": 1, "kind": "ttl"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "ttl_set", "args": [3, 3, "rwg"]},
            {"offset_cycles": 1, "function": "wait", "args": [4]},
            {"offset_cycles": 5, "function": "ttl_set", "args": [2, 0, "rwg"]},
            {"offset_cycles": 6, "function": "wait", "args": [4]},
            {"offset_cycles": 10, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
}

#[test]
fn compile_uses_the_target_board_kind_for_ttl_set() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(40 * ns)}\n",
    )
    .unwrap();
    let environment_path = path.with_extension("environment.json");
    let channel_key = format!("{}::ttl0", path.display());
    fs::write(
        &environment_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "channels": {
                channel_key: {"board": "main", "local_id": 0, "kind": "ttl"}
            }
        }))
        .unwrap(),
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"][0]["args"],
        serde_json::json!([1, 1, "main"])
    );
}
