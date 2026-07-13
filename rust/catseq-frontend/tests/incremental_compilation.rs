use std::sync::Arc;

use catseq_frontend::{CacheStatus, SourceCompilerSession};

const SCAN_SOURCE: &str = "@arena_build\ndef sequence(self, params: ExpParams):\n    return pulse(params[self.duration])\n";

#[test]
fn identical_source_reuses_hir_and_arena_artifact() {
    let mut session = SourceCompilerSession::new();

    let first = session
        .compile_source("experiment.py", SCAN_SOURCE, "sequence")
        .unwrap();
    let node_count = session.arena().total_node_count();
    let second = session
        .compile_source("experiment.py", SCAN_SOURCE, "sequence")
        .unwrap();

    assert_eq!(first.status(), CacheStatus::Compiled);
    assert_eq!(second.status(), CacheStatus::SourceReused);
    assert!(Arc::ptr_eq(first.artifact(), second.artifact()));
    assert_eq!(session.arena().total_node_count(), node_count);
    assert_eq!(first.artifact().scan_slots().len(), 1);
}

#[test]
fn source_change_invalidates_the_cached_entry() {
    let mut session = SourceCompilerSession::new();
    let first = session
        .compile_source(
            "experiment.py",
            "@arena_build\ndef sequence():\n    return pulse(1)\n",
            "sequence",
        )
        .unwrap();
    let second = session
        .compile_source(
            "experiment.py",
            "@arena_build\ndef sequence():\n    return pulse(2)\n",
            "sequence",
        )
        .unwrap();

    assert_eq!(first.status(), CacheStatus::Compiled);
    assert_eq!(second.status(), CacheStatus::Compiled);
    assert!(!Arc::ptr_eq(first.artifact(), second.artifact()));
    assert_ne!(
        first.artifact().program().root(),
        second.artifact().program().root()
    );
    assert_eq!(session.cached_artifact_count(), 1);
}

#[test]
fn source_hir_reuses_the_arena_when_only_host_source_changes() {
    let mut session = SourceCompilerSession::new();
    let first = session
        .compile_source("experiment.py", SCAN_SOURCE, "sequence")
        .unwrap();
    let node_count = session.arena().total_node_count();
    let source_with_host_change = format!("{SCAN_SOURCE}\n# host-side analysis changed\n");

    let second = session
        .compile_source("experiment.py", &source_with_host_change, "sequence")
        .unwrap();

    assert_eq!(second.status(), CacheStatus::HirReused);
    assert!(Arc::ptr_eq(first.artifact(), second.artifact()));
    assert_eq!(session.arena().total_node_count(), node_count);
}

#[test]
fn changed_name_resolution_invalidates_an_identical_hir() {
    let mut session = SourceCompilerSession::new();
    let first_source =
        "from one import duration\n@arena_build\ndef sequence():\n    return pulse(duration)\n";
    let second_source =
        "from two import duration\n@arena_build\ndef sequence():\n    return pulse(duration)\n";

    let first = session
        .compile_source("experiment.py", first_source, "sequence")
        .unwrap();
    let second = session
        .compile_source("experiment.py", second_source, "sequence")
        .unwrap();

    assert_eq!(first.status(), CacheStatus::Compiled);
    assert_eq!(second.status(), CacheStatus::Compiled);
    assert!(!Arc::ptr_eq(first.artifact(), second.artifact()));
}
