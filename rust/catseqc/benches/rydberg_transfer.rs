//! Criterion benchmarks for the production rb1-next Rydberg Transfer program.
//!
//! The workload deliberately remains in rb1-next instead of becoming a CatSeq
//! fixture. Set `CATSEQ_RB1_ROOT` when that repository is not a sibling of
//! CatSeq.

use std::hint::black_box;
use std::path::{Path, PathBuf};
use std::time::Duration;

use catseq_frontend::{
    TypedCheckReport, check_typed_bundle_entry_with_loader,
    specialize_typed_report_to_native_arenas,
};
use catseq_rtmq::{CompileEnvironment, LinkBindings, TargetProfile, compile_oasm_call_plan};
use criterion::{Criterion, criterion_group, criterion_main};

const ENTRY_MODULE: &str = "experiments.computing.rydberg_transfer";
const ENTRY: &str = "RydbergTransferExp.build_sequence";

fn rb1_root() -> PathBuf {
    std::env::var_os("CATSEQ_RB1_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../rb1-next"))
}

fn load_module(root: &Path, module: &str) -> Result<Option<String>, String> {
    let relative = module.replace('.', std::path::MAIN_SEPARATOR_STR);
    let candidates = [
        root.join(&relative).with_extension("py"),
        root.join(&relative).join("__init__.py"),
    ];
    for path in candidates {
        if path.is_file() {
            return std::fs::read_to_string(&path)
                .map(Some)
                .map_err(|error| format!("cannot read {}: {error}", path.display()));
        }
    }
    Ok(None)
}

fn check_rydberg(root: &Path) -> TypedCheckReport {
    let mut loader = |module: &str| load_module(root, module);
    check_typed_bundle_entry_with_loader(ENTRY_MODULE, ENTRY, &mut loader)
        .expect("the rb1-next Rydberg Transfer source bundle must type-check")
}

fn bench_rydberg(c: &mut Criterion) {
    let root = rb1_root();
    assert!(
        root.is_dir(),
        "rb1-next source root {} does not exist; set CATSEQ_RB1_ROOT",
        root.display()
    );

    let environment: CompileEnvironment =
        serde_json::from_slice(include_bytes!("../tests/fixtures/rydberg_environment.json"))
            .expect("the pinned Rydberg compile environment must decode");
    let bindings: LinkBindings =
        serde_json::from_slice(include_bytes!("../tests/fixtures/rydberg_bindings.json"))
            .expect("the pinned Rydberg link bindings must decode");
    let target: TargetProfile =
        toml::from_str(include_str!("../../../catseq/targets/rtmq_v2.toml"))
            .expect("the packaged RTMQ v2 target profile must decode");

    let report = check_rydberg(&root);
    let program = specialize_typed_report_to_native_arenas(&report, target.clock_hz())
        .expect("the Rydberg program must specialize");

    let mut group = c.benchmark_group("rydberg_transfer");

    group.bench_function("frontend_with_source_io", |b| {
        b.iter(|| black_box(check_rydberg(&root)));
    });

    group.bench_function("template_specialization", |b| {
        b.iter(|| {
            black_box(
                specialize_typed_report_to_native_arenas(&report, target.clock_hz())
                    .expect("the Rydberg program must specialize"),
            )
        });
    });

    group.bench_function("arena_to_oasm_call_plan", |b| {
        b.iter(|| {
            black_box(
                compile_oasm_call_plan(&program, &environment, &target, &bindings)
                    .expect("the Rydberg program must lower to an OASM Call Plan"),
            )
        });
    });

    group.bench_function("frontend_specialization_to_oasm_plan", |b| {
        b.iter(|| {
            let report = check_rydberg(&root);
            let program = specialize_typed_report_to_native_arenas(&report, target.clock_hz())
                .expect("the Rydberg program must specialize");
            black_box(
                compile_oasm_call_plan(&program, &environment, &target, &bindings)
                    .expect("the Rydberg program must lower to an OASM Call Plan"),
            )
        });
    });

    group.finish();
}

criterion_group! {
    name = benches;
    config = Criterion::default()
        .sample_size(30)
        .warm_up_time(Duration::from_secs(2))
        .measurement_time(Duration::from_secs(10));
    targets = bench_rydberg
}
criterion_main!(benches);
