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
        "class Experiment:\n    @arena_build\n    def sequence(self, params):\n        return identity(params[self.delay])\n",
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
    assert!(String::from_utf8_lossy(&output.stdout).contains("Experiment.sequence"));
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
        "@arena_build\ndef sequence(flag):\n    while flag:\n        side_effect()\n    return identity(1)\n",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_catseqc"))
        .args(["check", path.to_str().unwrap(), "--entry", "sequence"])
        .output()
        .unwrap();
    fs::remove_file(path).unwrap();

    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("while_statement"));
}
