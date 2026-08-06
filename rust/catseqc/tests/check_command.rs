use std::fs;
use std::process::Command;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use catseq_compiler::compile_json_request;

static PROCESS_NONCE: OnceLock<u128> = OnceLock::new();
static NEXT_SOURCE_FILE: AtomicU64 = AtomicU64::new(0);

fn source_file_path(process_nonce: u128, process_id: u32, sequence: u64) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "catseqc-source-{process_nonce}-{process_id}-{sequence}.py"
    ))
}

fn process_nonce() -> u128 {
    *PROCESS_NONCE.get_or_init(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock must be after the Unix epoch")
            .as_nanos()
    })
}

fn source_file() -> std::path::PathBuf {
    let sequence = NEXT_SOURCE_FILE.fetch_add(1, Ordering::Relaxed);
    let process_id = std::process::id();
    let path = source_file_path(process_nonce(), process_id, sequence);
    fs::write(
        &path,
        "class Experiment:\n    @arena_build\n    def sequence(self, params: ExpParams):\n        return identity(params[self.delay])\n",
    )
    .unwrap();
    path
}

#[test]
fn source_fixture_names_survive_pid_reuse() {
    let first_process = source_file_path(100, 42, 0);
    let restarted_process = source_file_path(101, 42, 0);

    assert_ne!(first_process, restarted_process);
}

fn ttl_target_profile(source_path: &std::path::Path) -> std::path::PathBuf {
    ttl_target_profile_at(source_path, 250_000_000)
}

fn ttl_target_profile_at(source_path: &std::path::Path, clock_hz: u64) -> std::path::PathBuf {
    let path = source_path.with_extension("target.json");
    fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": clock_hz,
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

fn compile_ttl_source(
    source_path: &std::path::Path,
    source: &str,
    clock_hz: u64,
) -> Result<serde_json::Value, String> {
    compile_ttl_source_with(
        source_path,
        source,
        "sequence",
        clock_hz,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }),
    )
}

fn compile_ttl_source_with(
    source_path: &std::path::Path,
    source: &str,
    entry: &str,
    clock_hz: u64,
    link_bindings: serde_json::Value,
) -> Result<serde_json::Value, String> {
    compile_ttl_source_with_inputs(
        source_path,
        source,
        entry,
        clock_hz,
        serde_json::json!({}),
        link_bindings,
    )
}

fn compile_ttl_source_with_inputs(
    source_path: &std::path::Path,
    source: &str,
    entry: &str,
    clock_hz: u64,
    entry_arguments: serde_json::Value,
    link_bindings: serde_json::Value,
) -> Result<serde_json::Value, String> {
    fs::write(source_path, source).unwrap();
    let module = source_path.file_stem().unwrap().to_string_lossy();
    let ttl0 = format!("{module}::ttl0");
    let ttl1 = format!("{module}::ttl1");
    let request = serde_json::to_vec(&serde_json::json!({
        "schema_version": 1,
        "source_path": source_path,
        "source_root": source_path.parent().unwrap(),
        "entry": entry,
        "compile_environment": {
            "schema_version": 1,
            "channels": {
                ttl0: {"board": "rwg0", "local_id": 0, "kind": "ttl"},
                ttl1: {"board": "rwg0", "local_id": 1, "kind": "ttl"}
            }
        },
        "target_profile": {
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": clock_hz,
            "duration_quantization": "strict",
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
                },
                "catseq.hardware.sync.global_sync": {
                    "lowering": "global_sync",
                    "instruction_cost_cycles": 0
                }
            }
        },
        "entry_arguments": entry_arguments,
        "link_bindings": link_bindings
    }))
    .unwrap();
    compile_json_request(&request)
        .and_then(|response| serde_json::from_slice(&response).map_err(|error| error.to_string()))
}

fn compile_rwg_source(
    source_path: &std::path::Path,
    source: &str,
) -> Result<serde_json::Value, String> {
    compile_rwg_source_with_bindings(
        source_path,
        source,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }),
    )
}

fn emit_rwg_arena(
    source_path: &std::path::Path,
    source: &str,
) -> Result<serde_json::Value, String> {
    fs::write(source_path, source).unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            source_path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into_owned());
    }
    serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())
}

fn compile_rwg_source_with_bindings(
    source_path: &std::path::Path,
    source: &str,
    link_bindings: serde_json::Value,
) -> Result<serde_json::Value, String> {
    fs::write(source_path, source).unwrap();
    let environment_path = source_path.with_extension("environment.json");
    let channel_key = format!("{}::rwg0", source_path.display());
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
    let link_bindings_path = source_path.with_extension("bindings.json");
    fs::write(
        &link_bindings_path,
        serde_json::to_vec(&link_bindings).unwrap(),
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "compile",
            source_path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--compile-environment",
            environment_path.to_str().unwrap(),
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--link-bindings",
            link_bindings_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(environment_path).unwrap();
    fs::remove_file(link_bindings_path).unwrap();
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into_owned());
    }
    serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())
}

#[test]
fn shared_compile_request_api_returns_an_oasm_call_plan() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(1))\n",
    )
    .unwrap();
    let request = serde_json::to_vec(&serde_json::json!({
        "schema_version": 1,
        "source_path": path,
        "source_root": path.parent().unwrap(),
        "entry": "sequence",
        "compile_environment": {"schema_version": 1, "channels": {}},
        "target_profile": {
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": 250_000_000_u64,
            "boards": {},
            "operations": {}
        },
        "link_bindings": {
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }
    }))
    .unwrap();

    let response = compile_json_request(&request).unwrap();
    fs::remove_file(path).unwrap();
    let response: serde_json::Value = serde_json::from_slice(&response).unwrap();

    assert_eq!(response["schema_version"], 1);
    assert_eq!(response["stage"], "oasm_call_plan");
    assert_eq!(response["entry"], "sequence");
    assert_eq!(response["logical_duration_cycles"], 1);
}

#[test]
fn compile_environment_declares_an_opaque_source_definition() {
    let path = source_file();
    fs::write(
        &path,
        "def sequence():\n    return amp_calib()\n\ndef amp_calib():\n    raise RuntimeError('host encoder only')\n",
    )
    .unwrap();
    let module = path.file_stem().unwrap().to_string_lossy();
    let operation = format!("{module}.amp_calib");
    let request = serde_json::to_vec(&serde_json::json!({
        "schema_version": 1,
        "source_path": path,
        "source_root": path.parent().unwrap(),
        "entry": "sequence",
        "compile_environment": {
            "schema_version": 1,
            "channels": {},
            "opaque_calls": {
                operation.clone(): {
                    "callable": "test.amp_calib",
                    "args": [],
                    "kwargs": {}
                }
            }
        },
        "target_profile": {
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": 250_000_000_u64,
            "boards": {"rwg0": {"kind": "rwg", "ttl_width": 32}},
            "operations": {
                operation: {
                    "lowering": "opaque",
                    "fixed_duration_cycles": 5,
                    "board": "rwg0",
                    "instruction_cost_cycles": 5
                }
            }
        },
        "link_bindings": {
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }
    }))
    .unwrap();

    let response = compile_json_request(&request).unwrap();
    fs::remove_file(path).unwrap();
    let response: serde_json::Value = serde_json::from_slice(&response).unwrap();

    assert_eq!(response["logical_duration_cycles"], 5);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"][0],
        serde_json::json!({
            "offset_cycles": 0,
            "function": "user_defined_func",
            "args": ["test.amp_calib", [], {}]
        })
    );
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
fn black_box_definition_remains_a_source_composition_boundary() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\n\ndef sequence() -> Morphism:\n    return legacy_atomic()\n\ndef legacy_atomic() -> Morphism:\n    return black_box(duration_cycles=1, board_funcs={})\n",
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
    assert_eq!(report["definitions"].as_array().unwrap().len(), 2);
    let definition = report["definitions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|definition| {
            definition["qualified_name"]
                .as_str()
                .is_some_and(|name| name.ends_with(".sequence") || name == "sequence")
        })
        .unwrap();
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
    assert_eq!(call.1["resolved_call_targets"].as_array().unwrap().len(), 1);
}

#[test]
fn black_box_keeps_board_calls_without_state_schema_in_the_native_arena() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\nfrom catseq.types import Board\n\nboard = Board('rwg0')\n\ndef callback() -> None:\n    pass\n\ndef sequence() -> Morphism:\n    return black_box(\n        duration_cycles=12,\n        board_funcs={board: callback},\n    )\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
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
    let arena = &artifact["morphism_arena"];
    let root = arena["root"].as_u64().unwrap() as usize;
    assert_eq!(arena["nodes"][root]["kind"], "opaque");
    assert_eq!(arena["opaque_calls"].as_array().unwrap().len(), 1);
    assert_eq!(arena["opaque_calls"][0]["board"], "rwg0");
    assert!(
        arena["opaque_calls"][0]["callable"]
            .as_str()
            .unwrap()
            .ends_with(".callback")
    );
    assert!(arena.get("opaque_state_effects").is_none());
}

#[test]
fn black_box_rejects_a_same_named_foreign_board_constructor() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\n\nclass Board:\n    def __init__(self, board_id: str) -> None:\n        self.id = board_id\n\nboard: Board = Board('rwg0')\n\ndef callback() -> None:\n    pass\n\ndef sequence() -> Morphism:\n    return black_box(\n        duration_cycles=12,\n        board_funcs={board: callback},\n    )\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("blackbox board key must resolve to a static Board"),
        "{stderr}"
    );
}

#[test]
fn black_box_rejects_a_class_binding_shadowing_the_board_import() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\nfrom catseq.types import Board\n\ndef host_board(board_id: str):\n    return board_id\n\ndef callback() -> None:\n    pass\n\nclass Experiment:\n    Board = host_board\n    board = Board('rwg0')\n\n    def sequence(self) -> Morphism:\n        return black_box(\n            duration_cycles=12,\n            board_funcs={self.board: callback},\n        )\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("blackbox board key must resolve to a static Board"),
        "{stderr}"
    );
}

#[test]
fn black_box_rejects_a_class_method_shadowing_the_board_import() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\nfrom catseq.types import Board\n\ndef callback() -> None:\n    pass\n\nclass Experiment:\n    def Board(board_id: str):\n        return board_id\n\n    board = Board('rwg0')\n\n    def sequence(self) -> Morphism:\n        return black_box(\n            duration_cycles=12,\n            board_funcs={self.board: callback},\n        )\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("blackbox board key must resolve to a static Board"),
        "{stderr}"
    );
}

#[test]
fn black_box_rejects_extra_board_fields_without_panicking() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.oasm import black_box\nfrom catseq.morphism import Morphism\nfrom catseq.types import Board\n\nboard = Board('rwg0', 'extra')\n\ndef callback() -> None:\n    pass\n\ndef sequence() -> Morphism:\n    return black_box(\n        duration_cycles=12,\n        board_funcs={board: callback},\n    )\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("native record Board accepts at most 1 positional field, got 2"),
        "{stderr}"
    );
    assert!(!stderr.contains("panicked"), "{stderr}");
}

#[test]
fn unrelated_black_box_is_rejected_as_a_reachable_host_call() {
    let path = source_file();
    fs::write(
        &path,
        "import time\nfrom catseq.morphism import Morphism\n\ndef sequence() -> Morphism:\n    return time.black_box()\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("reachable Host call time.black_box"),
        "{stderr}"
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
    assert_eq!(fact["resolved_call_targets"].as_array().unwrap().len(), 2);
    assert_eq!(fact["type"], "Morphism");
}

#[test]
fn repeated_comprehension_call_text_keeps_occurrence_targets_separate() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from functools import reduce\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\nclass ModuleA:\n    def init(self) -> Morphism:\n        return identity(cycles(1))\n\nclass ModuleB:\n    def init(self) -> Morphism:\n        return identity(cycles(2))\n\nmodule_a = ModuleA()\nmodule_b = ModuleB()\n\nclass Service:\n    @property\n    def first(self) -> list[ModuleA]:\n        return [module_a]\n\n    @property\n    def second(self) -> list[ModuleB]:\n        return [module_b]\n\n    def init(self) -> Morphism:\n        first_values = [module.init() for module in self.first]\n        second_values = [module.init() for module in self.second]\n        first = reduce(lambda left, right: left | right, first_values)\n        second = reduce(lambda left, right: left | right, second_values)\n        return first >> second\n\nservice = Service()\n\ndef sequence() -> Morphism:\n    return service.init()\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 3);
}

#[test]
fn property_comprehension_preserves_repeated_instance_targets() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\nclass Module:\n    def init(self) -> Morphism:\n        return identity(cycles(1))\n\nmodule_a = Module()\n\nclass Service:\n    @property\n    def modules(self) -> list[Module]:\n        return [module_a, module_a]\n\n    def init(self) -> Morphism:\n        values = [module.init() for module in self.modules]\n        return identity(cycles(len(values)))\n\nservice = Service()\n\ndef sequence() -> Morphism:\n    return service.init()\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 2);
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
fn call_accepts_a_scalar_for_an_optional_scalar_parameter() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\ndef pulse(frequency: float | None) -> Morphism:\n    return identity(1)\n\ndef sequence() -> Morphism:\n    return pulse(1.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn round_produces_an_integer_cycle_count() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(round(2.5))) >> identity(cycles(round(3.5)))\n",
        250_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 6);
}

#[test]
fn round_preserves_negative_ties_to_even_for_timeline_rewinds() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(10)) >> {ttl0: set_high()} >> identity(cycles(round(-2.5))) >> identity(cycles(round(-3.5))) >> {ttl0: set_low()}\n",
        250_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 10);
    let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    let ttl_offsets = calls
        .iter()
        .filter(|call| call["function"] == "ttl_set")
        .map(|call| call["offset_cycles"].as_u64().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(ttl_offsets, [4, 10]);
}

#[test]
fn round_keeps_link_time_values_symbolic_until_ties_to_even_linking() {
    let path = source_file();
    let response = compile_ttl_source_with(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence(params: ExpParams) -> Morphism:\n    return identity(cycles(round(params[sample_count])))\n",
        "sequence",
        250_000_000,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {"sample_count": 2.5},
            "environment_values": {}
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 2);
}

#[test]
fn round_rejects_results_outside_int64() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(round(1e30)))\n",
        250_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("round result overflows Int64"), "{error}");
}

#[test]
fn source_definition_named_round_keeps_its_source_semantics() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef round(value: float) -> Morphism:\n    return identity(cycles(7))\n\ndef sequence() -> Morphism:\n    return round(2.5)\n",
        250_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 7);
}

#[test]
fn foreign_round_is_not_treated_as_the_builtin_intrinsic() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from foreign_math import round\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(round(2.5)))\n",
        250_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("foreign_math.round"), "{error}");
    assert!(error.contains("reachable Host call"), "{error}");
}

#[test]
fn compile_binds_explicit_root_scalars_before_structural_specialization() {
    let path = source_file();
    let response = compile_ttl_source_with_inputs(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\ndef sequence(delay: Duration = cycles(2), omega: float | None = None) -> Morphism:\n    if omega is None:\n        omega = 1.0\n    return identity(delay) >> identity(cycles(round(omega)))\n",
        "sequence",
        250_000_000,
        serde_json::json!({"delay": 0.000000008, "omega": 3.0}),
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 5);
}

#[test]
fn explicit_none_overrides_a_non_none_optional_entry_default() {
    let path = source_file();
    let response = compile_ttl_source_with_inputs(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence(omega: float | None = 3.0) -> Morphism:\n    if omega is None:\n        omega = 1.0\n    return identity(cycles(round(omega)))\n",
        "sequence",
        250_000_000,
        serde_json::json!({"omega": null}),
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 1);
}

#[test]
fn compile_rejects_an_unknown_entry_argument() {
    let path = source_file();
    let error = compile_ttl_source_with_inputs(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence(count: int = 1) -> Morphism:\n    return identity(cycles(count))\n",
        "sequence",
        250_000_000,
        serde_json::json!({"coutn": 2}),
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {}
        }),
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("unknown entry argument \"coutn\""),
        "{error}"
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
        "from catseq.morphism import Morphism, identity, repeat_morphism\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return repeat_morphism(identity(cycles(1)), 3)\n",
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

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
        "from catseq.morphism import Morphism, identity, repeat_morphism\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return repeat_morphism(identity(cycles(1)), 0)\n",
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

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
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\nclass Experiment:\n    def sequence(self) -> Morphism:\n        return identity(cycles(1)) >> identity(cycles(2)) >> identity(cycles(3))\n",
    )
    .unwrap();
    let target_profile_path = ttl_target_profile(&path);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

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
fn emit_arena_uses_the_selected_target_clock() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\ndef sequence() -> Morphism:\n    return identity(1 * us)\n",
    )
    .unwrap();
    let target_profile_path = ttl_target_profile_at(&path, 100_000_000);
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile_path.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();
    fs::remove_file(target_profile_path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let artifact: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(
        artifact["value_expr_arena"]["payloads"]
            .as_array()
            .unwrap()
            .contains(&serde_json::json!({"kind": "duration_cycles", "value": 100}))
    );
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
fn compile_rejects_unitless_duration_spellings() {
    let path = source_file();
    let sources = [
        "from catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(1)\n",
        "from catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(1.0)\n",
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(1.0)}\n",
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    delay = 1e-6\n    return identity(0) >> {ttl0: pulse(delay)}\n",
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\n\nDELAY = 1e-6\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration\n\nDELAY: Duration = 1e-6\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
    ];

    for source in sources {
        let error = compile_ttl_source(&path, source, 250_000_000).unwrap_err();
        assert!(error.to_ascii_lowercase().contains("duration"), "{error}");
        assert!(
            error.contains("explicit unit") || error.contains("cycles("),
            "{error}"
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn compiler_preserves_same_instant_ttl_order_across_composition_paths() {
    let path = source_file();
    let cases = [
        (
            "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: set_high() >> set_low()}\n",
            1,
            0,
        ),
        (
            "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, MorphismDef, identity, morphism_template\n\n@morphism_template\ndef toggle() -> MorphismDef:\n    return set_low() >> set_high()\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: toggle()}\n",
            1,
            1,
        ),
        (
            "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: set_high() >> set_low(), ttl1: set_low() >> set_high()}\n",
            3,
            2,
        ),
    ];

    for (source, expected_mask, expected_state) in cases {
        let response = compile_ttl_source(&path, source, 250_000_000).unwrap();
        let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
            .as_array()
            .unwrap();
        let ttl_calls = calls
            .iter()
            .filter(|call| call["function"] == "ttl_set")
            .collect::<Vec<_>>();
        assert_eq!(ttl_calls.len(), 1, "{response:#}");
        assert_eq!(
            ttl_calls[0]["args"],
            serde_json::json!([expected_mask, expected_state, "rwg"])
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn compiler_preserves_same_instant_ttl_order_inside_a_hardware_loop() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity, repeat_morphism\n\ndef sequence() -> Morphism:\n    return repeat_morphism(identity(0) >> {ttl0: set_high() >> set_low() >> set_high()}, 3)\n",
        250_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    let ttl_calls = calls
        .iter()
        .filter(|call| call["function"] == "ttl_set")
        .collect::<Vec<_>>();
    assert_eq!(ttl_calls.len(), 1, "{response:#}");
    assert_eq!(ttl_calls[0]["args"], serde_json::json!([1, 1, "rwg"]));
}

#[test]
fn duration_conversion_uses_the_selected_clock_without_implicit_rounding() {
    let path = source_file();
    let exact = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(1 * us)}\n",
        100_000_000,
    )
    .unwrap();
    assert_eq!(exact["clock_hz"], 100_000_000);
    assert_eq!(exact["logical_duration_cycles"], 100);

    let nonintegral = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(15 * ns)}\n",
        100_000_000,
    )
    .unwrap_err();
    assert!(nonintegral.contains("exact signed target Cycle Delta"));
    fs::remove_file(path).unwrap();
}

#[test]
fn negative_duration_rewinds_the_logical_cursor_without_emitting_negative_time() {
    let path = source_file();
    let source = "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: set_high()} >> identity(-10 * ns) >> {ttl0: set_low()}\n";
    let response = compile_ttl_source(&path, source, 100_000_000).unwrap();
    let repeated = compile_ttl_source(&path, source, 100_000_000).unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["oasm_call_plan"], repeated["oasm_call_plan"]);
    assert_eq!(response["logical_duration_cycles"], 2);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [1]},
            {"offset_cycles": 1, "function": "ttl_set", "args": [1, 0, "rwg"]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]}
        ])
    );
}

#[test]
fn negative_duration_cannot_move_before_the_epoch_origin() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import set_high\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(-10 * ns) >> {ttl0: set_high()}\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("before Epoch origin"), "{error}");
}

#[test]
fn negative_duration_cannot_cross_a_nonzero_epoch_origin() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.hardware.sync import global_sync\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> global_sync() >> identity(-10 * ns)\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("before Epoch origin 2"), "{error}");
}

#[test]
fn negative_pulse_width_remains_a_physical_interval_error() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: pulse(-10 * ns)}\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("physical interval duration must be non-negative"),
        "{error}"
    );
}

#[test]
fn negative_duration_is_preserved_through_globals_functions_and_cycles() {
    let path = source_file();
    for source in [
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, ns\n\nREWIND: Duration = -10 * ns\n\ndef move(delay: Duration) -> Morphism:\n    return identity(delay)\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: set_high()} >> move(REWIND) >> {ttl0: set_low()}\n",
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(cycles(2)) >> {ttl0: set_high()} >> identity(cycles(-1)) >> {ttl0: set_low()}\n",
        "import catseq.time_utils as time\nfrom catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\nREWIND = -10 * time.ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: set_high()} >> identity(REWIND) >> {ttl0: set_low()}\n",
        "import catseq.time_utils as time\nfrom catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    rewind = -10 * time.ns\n    return identity(20 * ns) >> {ttl0: set_high()} >> identity(rewind) >> {ttl0: set_low()}\n",
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns as nanos\n\ndef sequence() -> Morphism:\n    return identity(20 * nanos) >> {ttl0: set_high()} >> identity(-10 * nanos) >> {ttl0: set_low()}\n",
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\ndef move(delay: Duration = cycles(-1)) -> Morphism:\n    return identity(delay)\n\ndef sequence() -> Morphism:\n    return identity(cycles(2)) >> {ttl0: set_high()} >> move() >> {ttl0: set_low()}\n",
    ] {
        let response = compile_ttl_source(&path, source, 100_000_000).unwrap();
        assert_eq!(response["logical_duration_cycles"], 2);
        assert_eq!(
            response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"][1]["offset_cycles"],
            1
        );
        assert_eq!(
            response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"][2]["offset_cycles"],
            2
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn duration_units_require_the_registered_import_identity() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "import catseq.time_utils\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(20 * catseq.time_utils.ns)\n",
        100_000_000,
    )
    .unwrap();
    assert_eq!(response["logical_duration_cycles"], 2);

    for source in [
        "from unrelated_or_missing_module import ns\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    return identity(20 * ns)\n",
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    ns = 1\n    return identity(ns)\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    time = 1\n    return identity(time.ns)\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\ndef move(time: float) -> Morphism:\n    return identity(time.ns)\n\ndef sequence() -> Morphism:\n    return move(1.0)\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\nclass Fake:\n    us: float = 1.0\n\ntime = Fake()\n\ndef sequence() -> Morphism:\n    return identity(time.us)\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    result = identity(time.us)\n    time = 1\n    return result\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\nclass Fake:\n    us: float = 1.0\n\nif True:\n    time = Fake()\n\ndef sequence() -> Morphism:\n    return identity(time.us)\n",
        "import catseq.time_utils as time\nfrom catseq.morphism import Morphism, identity\n\nclass Fake:\n    us: float = 1.0\n\ndef helper(value=(time := Fake())):\n    return value\n\ndef sequence() -> Morphism:\n    return identity(time.us)\n",
    ] {
        let error = compile_ttl_source(&path, source, 100_000_000).unwrap_err();
        assert!(
            error.contains("identity duration") || error.contains("identity requires a duration"),
            "{source}\n{error}"
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn duration_dimension_cannot_be_forged_by_annotation_or_division() {
    let path = source_file();
    for (source, entry) in [
        (
            "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, ns\n\nDELAY: Duration = 1.0 + 0 * ns\n\ndef sequence() -> Morphism:\n    return identity(DELAY)\n",
            "sequence",
        ),
        (
            "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\nclass Experiment:\n    def sequence(self, params: ExpParams) -> Morphism:\n        return identity(params[self.delay] / us)\n",
            "Experiment.sequence",
        ),
    ] {
        let error = compile_ttl_source_with(
            &path,
            source,
            entry,
            100_000_000,
            serde_json::json!({
                "schema_version": 1,
                "runtime_values": {"delay": 100},
                "environment_values": {}
            }),
        )
        .unwrap_err();
        assert!(
            error.contains("Duration compile values require")
                || error.contains("identity duration")
                || error.contains("identity requires a duration")
                || error.contains("type mismatch"),
            "{error}"
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn user_cycles_function_cannot_forge_a_link_time_duration() {
    let path = source_file();
    for expression in [
        "cycles(params[self.delay]) * 2",
        "-cycles(params[self.delay])",
        "+cycles(params[self.delay])",
    ] {
        let source = format!(
            "from catseq.morphism import Morphism, identity\n\ndef cycles(value: float) -> float:\n    return value\n\nclass Experiment:\n    def sequence(self, params: ExpParams) -> Morphism:\n        return identity({expression})\n"
        );
        let error = compile_ttl_source_with(
            &path,
            &source,
            "Experiment.sequence",
            100_000_000,
            serde_json::json!({
                "schema_version": 1,
                "runtime_values": {"delay": 3.0},
                "environment_values": {}
            }),
        )
        .unwrap_err();

        assert!(
            error.contains("identity duration")
                || error.contains("identity requires a duration")
                || error.contains("type mismatch"),
            "{expression}: {error}"
        );
    }
    fs::remove_file(path).unwrap();
}

#[test]
fn public_compile_environment_duration_slot_can_rewind() {
    let path = source_file();
    let module = path.file_stem().unwrap().to_string_lossy();
    let environment_key = format!("{module}.Experiment.rewind");
    let response = compile_ttl_source_with(
        &path,
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\nclass Experiment:\n    rewind: Duration\n\n    def sequence(self) -> Morphism:\n        return identity(cycles(2)) >> {ttl0: set_high()} >> identity(self.rewind) >> {ttl0: set_low()}\n",
        "Experiment.sequence",
        100_000_000,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {(environment_key): -1}
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 2);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [1]},
            {"offset_cycles": 1, "function": "ttl_set", "args": [1, 0, "rwg"]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]}
        ])
    );
}

#[test]
fn environment_slots_are_scoped_to_compile_instances() {
    let path = source_file();
    let module = path.file_stem().unwrap().to_string_lossy();
    let first_key = format!("{module}.service_a.rewind");
    let second_key = format!("{module}.service_b.rewind");
    let response = compile_ttl_source_with(
        &path,
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\nclass Service:\n    rewind: Duration\n\n    def move(self) -> Morphism:\n        return identity(self.rewind)\n\nservice_a = Service()\nservice_b = Service()\n\ndef sequence() -> Morphism:\n    return identity(cycles(5)) >> service_a.move() >> {ttl0: set_high()} >> service_b.move() >> {ttl0: set_low()}\n",
        "sequence",
        100_000_000,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {
                (first_key): -1,
                (second_key): -2
            }
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 5);
    let ttl_calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|call| call["function"] == "ttl_set")
        .collect::<Vec<_>>();
    assert_eq!(ttl_calls.len(), 2);
    assert_eq!(ttl_calls[0]["offset_cycles"], 2);
    assert_eq!(ttl_calls[0]["args"], serde_json::json!([1, 0, "rwg"]));
    assert_eq!(ttl_calls[1]["offset_cycles"], 4);
    assert_eq!(ttl_calls[1]["args"], serde_json::json!([1, 1, "rwg"]));
}

#[test]
fn comprehension_environment_slots_keep_each_instance_identity() {
    let path = source_file();
    let module = path.file_stem().unwrap().to_string_lossy();
    let first_key = format!("{module}.module_a.rewind");
    let second_key = format!("{module}.module_b.rewind");
    let response = compile_ttl_source_with(
        &path,
        "from functools import reduce\nfrom catseq.hardware.ttl import set_high\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\nclass Module:\n    rewind: Duration\n\n    def init(self) -> Morphism:\n        return identity(self.rewind) >> {ttl0: set_high()}\n\nmodule_a = Module()\nmodule_b = Module()\n\nclass Service:\n    @property\n    def module_list(self) -> list[Module]:\n        return [module_a, module_b]\n\n    def init(self) -> Morphism:\n        values = [module.init() for module in self.module_list]\n        return reduce(lambda left, right: left | right, values)\n\nservice = Service()\n\ndef sequence() -> Morphism:\n    return identity(cycles(5)) >> service.init()\n",
        "sequence",
        100_000_000,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {
                (first_key): -1,
                (second_key): -2
            }
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 5);
    let ttl_offsets = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|call| call["function"] == "ttl_set")
        .map(|call| call["offset_cycles"].as_u64().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(ttl_offsets, vec![3, 4]);
}

#[test]
fn negative_nonintegral_duration_is_rejected_explicitly() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> identity(-15 * ns)\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("exact signed target Cycle Delta"), "{error}");
}

#[test]
fn template_and_parallel_rewinds_share_one_signed_timeline() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import hold, set_high, set_low\nfrom catseq.morphism import Morphism, MorphismDef, identity, morphism_template\nfrom catseq.time_utils import ns\n\n@morphism_template\ndef high_then_rewind() -> MorphismDef:\n    return set_high() >> hold(-10 * ns) >> set_low()\n\n@morphism_template\ndef low_then_rewind() -> MorphismDef:\n    return set_low() >> hold(-10 * ns) >> set_high()\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: high_then_rewind(), ttl1: low_then_rewind()}\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 2);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [1]},
            {"offset_cycles": 1, "function": "ttl_set", "args": [3, 2, "rwg"]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [3, 1, "rwg"]}
        ])
    );
}

#[test]
fn rewind_interacts_with_same_instant_writes_by_source_order() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    return identity(20 * ns) >> {ttl0: set_high()} >> identity(-10 * ns) >> {ttl0: set_low()} >> identity(10 * ns) >> {ttl0: set_low()}\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    let calls = &response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"];
    assert_eq!(calls[1]["offset_cycles"], 1);
    assert_eq!(calls[1]["args"], serde_json::json!([1, 0, "rwg"]));
    assert_eq!(calls[2]["offset_cycles"], 2);
    assert_eq!(calls[2]["args"], serde_json::json!([1, 0, "rwg"]));
}

#[test]
fn rewinding_loop_body_is_expanded_without_losing_timeline_semantics() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import set_high\nfrom catseq.morphism import Morphism, identity, repeat_morphism\nfrom catseq.time_utils import ns\n\ndef sequence() -> Morphism:\n    body = identity(20 * ns) >> {ttl0: set_high()} >> identity(-10 * ns)\n    return repeat_morphism(body, 3)\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 4);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [2]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 3, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 4, "function": "ttl_set", "args": [1, 1, "rwg"]}
        ])
    );
}

#[test]
fn rewinding_loop_expansion_has_a_compiler_budget() {
    let path = source_file();
    let error = compile_ttl_source(
        &path,
        "from catseq.morphism import Morphism, identity, repeat_morphism\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    body = identity(cycles(1)) >> identity(cycles(-1))\n    return repeat_morphism(body, 100001)\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("exceeding compiler budget"), "{error}");
}

#[test]
fn explicit_cycles_constructor_spells_target_cycles_without_units() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import cycles\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(cycles(250))}\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 250);
}

#[test]
fn explicit_cycles_constructor_is_preserved_through_a_duration_global() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\nDELAY: Duration = cycles(250)\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 250);
}

#[test]
fn global_cycles_constructor_requires_the_registered_integer_intrinsic() {
    let path = source_file();
    let float_count = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, cycles\n\nDELAY: Duration = cycles(1.0)\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
        100_000_000,
    )
    .unwrap_err();
    assert!(float_count.contains("integer count"), "{float_count}");

    let user_function = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\n\ndef cycles(value: float) -> float:\n    return value\n\nDELAY = cycles(1.0)\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
        100_000_000,
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(user_function.contains("Duration"), "{user_function}");
}

#[test]
fn explicit_unit_is_preserved_through_an_unannotated_global() {
    let path = source_file();
    let response = compile_ttl_source(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import us\n\nDELAY = 1 * us\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: pulse(DELAY)}\n",
        100_000_000,
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(response["logical_duration_cycles"], 100);
}

#[test]
fn compile_specializes_reachable_morphism_definitions_before_oasm_lowering() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.hardware.ttl import pulse\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import Duration, ns\n\ndef service(duration: Duration) -> Morphism:\n    return identity(0) >> {ttl0: pulse(duration)}\n\ndef sequence() -> Morphism:\n    return service(40 * ns)\n",
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
        "from catseq.hardware.ttl import hold, set_high, set_low\nfrom catseq.morphism import Morphism, MorphismDef, identity, morphism_template\nfrom catseq.time_utils import Duration, ns\n\n@morphism_template\ndef user_pulse(duration: Duration) -> MorphismDef:\n    return set_high() >> hold(duration) >> set_low()\n\ndef sequence() -> Morphism:\n    return identity(0) >> {ttl0: user_pulse(40 * ns)}\n",
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
            "--target-profile",
            target_profile_path.to_str().unwrap(),
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
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");

    let arena_output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
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
fn catseq_replace_desugars_to_an_equivalent_native_record() {
    let path = source_file();
    let explicit = compile_rwg_source(
        &path,
        "from catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=2.0, amp=0.2, sbg_id=0, phase=0.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([target])}\n",
    )
    .unwrap();
    let replaced = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0, phase=0.5)\n    updated = replace(target, freq=2.0, phase=0.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    assert_eq!(replaced["oasm_call_plan"], explicit["oasm_call_plan"]);
}

#[test]
fn catseq_replace_accepts_a_static_waveform_with_no_initial_phase() {
    let path = source_file();
    let compiled = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ntarget = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0, phase=None)\n\ndef sequence() -> Morphism:\n    updated = replace(target, phase=0.125)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    let calls = compiled["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform" && call["args"][0]["initial_phase"] == 0.125
    }));
}

#[test]
fn compile_known_global_native_record_lowers_for_emit_arena_and_compile() {
    let path = source_file();
    let source = "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ntarget = StaticWaveform(freq=1.0, sbg_id=0)\n\ndef sequence() -> Morphism:\n    updated = replace(target, freq=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n";

    let arena = emit_rwg_arena(&path, source).unwrap();
    assert_eq!(arena["stage"], "morphism_arena");

    let compiled = compile_rwg_source(&path, source).unwrap();
    fs::remove_file(path).unwrap();
    let calls = compiled["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["sbg_id"] == 0
            && call["args"][0]["freq_coeffs"] == serde_json::json!([2.0, null, null, null])
            && call["args"][0]["amp_coeffs"] == serde_json::json!([null, null, null, null])
            && call["args"][0]["initial_phase"] == 0.0
            && call["args"][0]["phase_reset"] == true
            && call["args"][0]["fct"].is_null()
    }));
}

#[test]
fn annotated_global_native_record_alias_lowers_for_emit_arena_and_compile() {
    let path = source_file();
    let source = "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\noriginal = StaticWaveform(freq=1.0, sbg_id=0)\ntarget: StaticWaveform = original\n\ndef sequence() -> Morphism:\n    updated = replace(target, freq=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n";

    let arena = emit_rwg_arena(&path, source).unwrap();
    assert_eq!(arena["stage"], "morphism_arena");

    let compiled = compile_rwg_source(&path, source).unwrap();
    fs::remove_file(path).unwrap();
    let calls = compiled["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["sbg_id"] == 0
            && call["args"][0]["freq_coeffs"] == serde_json::json!([2.0, null, null, null])
    }));
}

#[test]
fn global_native_record_references_use_exact_compile_known_names() {
    let path = source_file();
    let source = "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\nfrequency = 1.0\nfrequency_extra = 3.0\ntarget = StaticWaveform(freq=frequency, sbg_id=0)\ntarget_extra = StaticWaveform(freq=frequency_extra, sbg_id=1)\nselected: StaticWaveform = target_extra\n\ndef sequence() -> Morphism:\n    updated = replace(selected, amp=0.25)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n";

    let arena = emit_rwg_arena(&path, source).unwrap();
    assert_eq!(arena["stage"], "morphism_arena");

    let compiled = compile_rwg_source(&path, source).unwrap();
    fs::remove_file(path).unwrap();
    let calls = compiled["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["sbg_id"] == 1
            && call["args"][0]["freq_coeffs"] == serde_json::json!([3.0, null, null, null])
            && call["args"][0]["amp_coeffs"] == serde_json::json!([0.25, null, null, null])
    }));
}

#[test]
fn compile_known_native_record_attribute_lowers_for_emit_arena() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform as Waveform\n\nclass Experiment:\n    Waveform = Waveform(freq=1.0, sbg_id=0)\n\n    def sequence(self) -> Morphism:\n        updated = replace(self.Waveform, freq=2.0)\n        return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.sequence",
            "--target-profile",
            target_profile.to_str().unwrap(),
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
    let arena: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(arena["stage"], "morphism_arena");
}

#[test]
fn class_native_record_closes_over_exact_compile_known_globals() {
    let path = source_file();
    let source = "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\nbase_frequency = 1.0\nbase_frequency_extra = 1.5\nselected_frequency = base_frequency_extra\nbase_sbg_id = 1\n\nclass Experiment:\n    target = StaticWaveform(freq=selected_frequency, sbg_id=base_sbg_id)\n\n    def build(self) -> Morphism:\n        updated = replace(self.target, amp=0.25)\n        return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n\nexperiment = Experiment()\n\ndef sequence() -> Morphism:\n    return experiment.build()\n";
    fs::write(&path, source).unwrap();
    let target_profile =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../catseq/targets/rtmq_v2.toml");
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args([
            "emit-arena",
            path.to_str().unwrap(),
            "--entry",
            "Experiment.build",
            "--target-profile",
            target_profile.to_str().unwrap(),
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let arena: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(arena["stage"], "morphism_arena");

    let compiled = compile_rwg_source(&path, source).unwrap();
    fs::remove_file(path).unwrap();
    let calls = compiled["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform"
            && call["args"][0]["sbg_id"] == 1
            && call["args"][0]["freq_coeffs"] == serde_json::json!([1.5, null, null, null])
            && call["args"][0]["amp_coeffs"] == serde_json::json!([0.25, null, null, null])
            && call["args"][0]["initial_phase"] == 0.0
            && call["args"][0]["phase_reset"] == true
            && call["args"][0]["fct"].is_null()
    }));
}

#[test]
fn catseq_replace_keeps_link_time_field_values_symbolic_until_linking() {
    let path = source_file();
    let source = "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence(params: ExpParams) -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)\n    updated = replace(target, freq=params[frequency])\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n";
    let artifact = emit_rwg_arena(&path, source).unwrap();
    let value_payloads = artifact["value_expr_arena"]["payloads"].as_array().unwrap();
    assert!(
        value_payloads.contains(&serde_json::json!({"kind": "runtime_slot", "value": "frequency"})),
        "{value_payloads:#?}"
    );
    assert!(
        value_payloads.iter().any(|payload| {
            payload["kind"] == "json" && payload["value"].to_string().contains("\"$value_expr\"")
        }),
        "{value_payloads:#?}"
    );

    let response = compile_rwg_source_with_bindings(
        &path,
        source,
        serde_json::json!({
            "schema_version": 1,
            "runtime_values": {"frequency": 2.5},
            "environment_values": {}
        }),
    )
    .unwrap();
    fs::remove_file(path).unwrap();

    let calls = response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"]
        .as_array()
        .unwrap();
    assert!(calls.iter().any(|call| {
        call["function"] == "rwg_load_waveform" && call["args"][0]["freq_coeffs"][0] == 2.5
    }));
}

#[test]
fn catseq_replace_requires_a_positional_native_record_base() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)\n    updated = replace(record=target, freq=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("first argument must be positional"),
        "{error}"
    );
}

#[test]
fn catseq_replace_rejects_unknown_native_record_fields() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)\n    updated = replace(target, frequency=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("unknown Native Record field `frequency`"),
        "{error}"
    );
    assert!(error.contains("StaticWaveform"), "{error}");
}

#[test]
fn catseq_replace_rejects_a_field_value_with_the_wrong_type() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)\n    updated = replace(target, freq='not-a-frequency')\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("freq"), "{error}");
    assert!(error.contains("Float64"), "{error}");
}

#[test]
fn catseq_replace_rejects_the_wrong_native_record_aggregate_element_type() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, load, play\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import WaveformParams\n\ndef sequence() -> Morphism:\n    target = WaveformParams(sbg_id=0)\n    updated = replace(target, freq_coeffs=('bad',))\n    return identity(0) >> {rwg0: initialize(80.0) >> load([updated]) >> play()}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("freq_coeffs"), "{error}");
    assert!(error.contains("Optional<Float64>"), "{error}");
}

#[test]
fn catseq_replace_rejects_a_non_native_record_base() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\n\ndef sequence() -> Morphism:\n    updated = replace(1, freq=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("catseq.replace requires a Native Record"),
        "{error}"
    );
}

#[test]
fn catseq_replace_rejects_a_compile_known_base_missing_a_required_field() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from catseq import replace\nfrom catseq.hardware.rwg import initialize, load, play\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import WaveformParams\n\nclass Experiment:\n    target = WaveformParams()\n\n    def build(self) -> Morphism:\n        updated = replace(self.target, phase_reset=True)\n        return identity(0) >> {rwg0: initialize(80.0) >> load([updated]) >> play()}\n\nexperiment = Experiment()\n\ndef sequence() -> Morphism:\n    return experiment.build()\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(
        error.contains("catseq.replace base `WaveformParams` is missing required field `sbg_id`"),
        "{error}"
    );
}

#[test]
fn typed_check_rejects_a_non_native_record_replace_base() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\n\ndef sequence():\n    return replace(1, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":4:"), "{stderr}");
}

#[test]
fn typed_check_requires_a_positional_native_record_replace_base() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(record=target, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace first argument must be positional"),
        "{stderr}"
    );
    assert!(stderr.contains(":6:"), "{stderr}");
}

#[test]
fn typed_check_rejects_an_unknown_native_record_replace_field() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(target, frequency=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("unknown Native Record field `frequency` for `StaticWaveform`"),
        "{stderr}"
    );
    assert!(stderr.contains(":6:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_native_record_replace_field_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(target, freq='not-a-frequency')\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(
            "catseq.replace field `freq` for `StaticWaveform` expects Optional<Float64>, found String"
        ),
        "{stderr}"
    );
    assert!(stderr.contains(":6:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_native_record_replace_aggregate_element_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import WaveformParams\n\ndef sequence():\n    target = WaveformParams(sbg_id=0)\n    return replace(target, freq_coeffs=('bad',))\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(
            "catseq.replace field `freq_coeffs` for `WaveformParams` expects Aggregate<Optional<Float64>>, found Aggregate<String>"
        ),
        "{stderr}"
    );
    assert!(stderr.contains(":6:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_compile_known_aggregate_attribute_element_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import WaveformParams\n\nclass Experiment:\n    bad_coeffs = ('bad',)\n    coeffs = bad_coeffs\n    target = WaveformParams(sbg_id=0)\n\n    def sequence(self):\n        return replace(self.target, freq_coeffs=self.coeffs)\n",
    )
    .unwrap();
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

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(
            "catseq.replace field `freq_coeffs` for `WaveformParams` expects Aggregate<Optional<Float64>>, found Aggregate<String>"
        ),
        "{stderr}"
    );
    assert!(stderr.contains(":10:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_compile_known_global_aggregate_element_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import WaveformParams\n\nbad_coeffs = ('bad',)\ncoeffs = bad_coeffs\ntarget = WaveformParams(sbg_id=0)\n\ndef sequence():\n    return replace(target, freq_coeffs=coeffs)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(
            "catseq.replace field `freq_coeffs` for `WaveformParams` expects Aggregate<Optional<Float64>>, found Aggregate<String>"
        ),
        "{stderr}"
    );
    assert!(stderr.contains(":9:"), "{stderr}");
}

#[test]
fn typed_check_accepts_compile_known_aggregate_aliases_with_valid_elements() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import WaveformParams\n\nbase_coeffs = (1.0, None)\ncoeffs = base_coeffs\ntarget = WaveformParams(sbg_id=0)\n\ndef sequence():\n    return replace(target, freq_coeffs=coeffs)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn typed_check_rejects_a_local_aggregate_alias_element_type_mismatch() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import WaveformParams\n\ndef sequence():\n    target = WaveformParams(sbg_id=0)\n    coeffs = ('bad',)\n    return replace(target, freq_coeffs=coeffs)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(
            "catseq.replace field `freq_coeffs` for `WaveformParams` expects Aggregate<Optional<Float64>>, found Aggregate<String>"
        ),
        "{stderr}"
    );
    assert!(stderr.contains(":7:"), "{stderr}");
}

#[test]
fn typed_check_does_not_accept_a_same_named_host_constructor_as_a_native_record() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\n\ndef sequence():\n    target = vendor.StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(target, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("reachable Host call vendor.StaticWaveform"),
        "{stderr}"
    );
    assert!(stderr.contains(":5:"), "{stderr}");
}

#[test]
fn typed_check_does_not_accept_a_same_named_compile_field_constructor() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\n\nclass Experiment:\n    target = vendor.StaticWaveform(freq=1.0, sbg_id=0)\n\n    def sequence(self):\n        return replace(self.target, freq=2.0)\n",
    )
    .unwrap();
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

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":8:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_class_binding_shadowing_a_native_record_import() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef host_waveform(freq, sbg_id):\n    return freq\n\nclass Experiment:\n    StaticWaveform = host_waveform\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n\n    def sequence(self):\n        return replace(self.target, freq=2.0)\n",
    )
    .unwrap();
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

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":12:"), "{stderr}");
}

#[test]
fn typed_check_does_not_accept_a_same_named_native_record_annotation() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\n\nclass Experiment:\n    target: vendor.StaticWaveform = vendor.StaticWaveform(freq=1.0, sbg_id=0)\n\n    def sequence(self):\n        return replace(self.target, freq=2.0)\n",
    )
    .unwrap();
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

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":8:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_registered_record_annotation_with_a_host_initializer() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\nfrom catseq.types import StaticWaveform\n\nclass Experiment:\n    target: StaticWaveform = vendor.StaticWaveform(freq=1.0, sbg_id=0)\n\n    def sequence(self):\n        return replace(self.target, freq=2.0)\n",
    )
    .unwrap();
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

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":9:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_registered_global_record_with_a_host_initializer() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\nfrom catseq.types import StaticWaveform\n\ntarget: StaticWaveform = vendor.StaticWaveform(freq=1.0, sbg_id=0)\n\ndef sequence():\n    return replace(target, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":8:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_registered_record_annotation_with_a_host_alias() {
    let path = source_file();
    fs::write(
        &path,
        "import vendor\nfrom catseq import replace\nfrom catseq.types import StaticWaveform\n\nforeign = vendor.StaticWaveform(freq=1.0, sbg_id=0)\ntarget: StaticWaveform = foreign\n\ndef sequence():\n    return replace(target, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("catseq.replace requires a Native Record"),
        "{stderr}"
    );
    assert!(stderr.contains(":9:"), "{stderr}");
}

#[test]
fn typed_check_accepts_a_registered_record_annotation_through_a_registered_alias() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\noriginal = StaticWaveform(freq=1.0, sbg_id=0)\ntarget: StaticWaveform = original\n\ndef sequence():\n    return replace(target, freq=2.0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn typed_check_preserves_the_nominal_schema_through_chained_replace_calls() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(replace(replace(target, freq=2.0), amp=0.4), phase=0.5)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

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
    let replace_facts = report["definitions"][0]["hir"]["facts"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|fact| fact["resolved_definition"] == "catseq.replace")
        .collect::<Vec<_>>();
    assert_eq!(replace_facts.len(), 3);
    assert!(replace_facts.iter().all(|fact| {
        fact["type"] == serde_json::Value::String("NativeRecord<StaticWaveform>".to_owned())
    }));
}

#[test]
fn dataclasses_replace_is_not_a_catseq_compiler_intrinsic() {
    let path = source_file();
    let error = compile_rwg_source(
        &path,
        "from dataclasses import replace\nfrom catseq.hardware.rwg import initialize, set_state\nfrom catseq.morphism import Morphism, identity\nfrom catseq.types import StaticWaveform\n\ndef sequence() -> Morphism:\n    target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)\n    updated = replace(target, freq=2.0)\n    return identity(0) >> {rwg0: initialize(80.0) >> set_state([updated])}\n",
    )
    .unwrap_err();
    fs::remove_file(path).unwrap();

    assert!(error.contains("dataclasses.replace"), "{error}");
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
        "from catseq.hardware.ttl import set_high, set_low\nfrom catseq.morphism import Morphism, identity\nfrom catseq.time_utils import ns, us\n\nclass Experiment:\n    def sequence(self, params: ExpParams) -> Morphism:\n        return identity(8 * ns) >> {ttl0: set_high()} >> identity(params[self.pulse_time] * us) >> {ttl0: set_low()}\n",
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
    fs::write(
        &link_bindings_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "runtime_values": {"self.pulse_time": -0.004}
        }))
        .unwrap(),
    )
    .unwrap();
    let rewind = run();
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
        rewind.status.success(),
        "{}",
        String::from_utf8_lossy(&rewind.stderr)
    );
    assert!(
        String::from_utf8_lossy(&nonintegral.stderr).contains("exact signed target Cycle Delta")
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["logical_duration_cycles"], 7);
    assert_eq!(response["clock_hz"], 250_000_000_u64);
    assert_eq!(
        response["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [2]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]},
            {"offset_cycles": 3, "function": "wait", "args": [4]},
            {"offset_cycles": 7, "function": "ttl_set", "args": [1, 0, "rwg"]}
        ])
    );
    let rewind: serde_json::Value = serde_json::from_slice(&rewind.stdout).unwrap();
    assert_eq!(rewind["logical_duration_cycles"], 2);
    assert_eq!(
        rewind["oasm_call_plan"]["epochs"][0]["boards"][0]["calls"],
        serde_json::json!([
            {"offset_cycles": 0, "function": "wait", "args": [1]},
            {"offset_cycles": 1, "function": "ttl_set", "args": [1, 0, "rwg"]},
            {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]}
        ])
    );
}

#[test]
fn typed_check_rejects_a_locally_shadowed_catseq_replace_call() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef helper(value):\n    return value\n\ndef sequence():\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    replace = helper\n    return replace(target)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("reachable Host call replace"), "{stderr}");
    assert!(stderr.contains(":10:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_nested_definition_shadowing_catseq_replace() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.types import StaticWaveform\n\ndef sequence():\n    def replace(value):\n        return value\n    target = StaticWaveform(freq=1.0, sbg_id=0)\n    return replace(target)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("unsupported reachable nested function statement"),
        "{stderr}"
    );
    assert!(stderr.contains(":5:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_locally_shadowed_native_record_constructor() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.types import StaticWaveform\n\ndef helper(freq, sbg_id):\n    return freq\n\ndef sequence():\n    StaticWaveform = helper\n    return StaticWaveform(freq=1.0, sbg_id=0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("reachable Host call StaticWaveform"),
        "{stderr}"
    );
    assert!(stderr.contains(":8:"), "{stderr}");
}

#[test]
fn typed_check_rejects_a_locally_shadowed_registered_intrinsic() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import identity\n\ndef helper(value):\n    return value\n\ndef sequence():\n    identity = helper\n    return identity(0)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("reachable Host call identity"), "{stderr}");
    assert!(stderr.contains(":8:"), "{stderr}");
}

#[test]
fn typed_check_keeps_self_method_resolution_for_an_intrinsic_leaf_name() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq.morphism import Morphism, identity\n\nclass Experiment:\n    def identity(self) -> Morphism:\n        return identity(0)\n\n    def sequence(self) -> Morphism:\n        return self.identity()\n",
    )
    .unwrap();
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
}

#[test]
fn typed_check_keeps_a_module_source_function_with_a_special_form_name() {
    let path = source_file();
    fs::write(
        &path,
        "from catseq import replace\nfrom catseq.morphism import Morphism, identity\n\ndef replace() -> Morphism:\n    return identity(0)\n\ndef sequence() -> Morphism:\n    return replace()\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
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
