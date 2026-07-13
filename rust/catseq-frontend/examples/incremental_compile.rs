use std::env;
use std::fs;
use std::hint::black_box;
use std::process::ExitCode;
use std::time::Instant;

use catseq_frontend::{CacheStatus, SourceCompilerSession};

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("incremental_compile: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let path = args.next().ok_or_else(usage)?;
    let entry = args.next().ok_or_else(usage)?;
    let iterations: u32 = args
        .next()
        .unwrap_or_else(|| String::from("10000"))
        .parse()
        .map_err(|error| format!("invalid iteration count: {error}"))?;
    if iterations == 0 {
        return Err(String::from("iteration count must be positive"));
    }
    if args.next().is_some() {
        return Err(usage());
    }
    let source = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut session = SourceCompilerSession::new();

    let cold_start = Instant::now();
    let cold = session
        .compile_source(&path, &source, &entry)
        .map_err(|error| error.to_string())?;
    let cold_elapsed = cold_start.elapsed();
    black_box(cold.artifact());

    let exact_start = Instant::now();
    for _ in 0..iterations {
        let result = session
            .compile_source(&path, black_box(&source), &entry)
            .map_err(|error| error.to_string())?;
        assert_eq!(result.status(), CacheStatus::SourceReused);
        black_box(result.artifact());
    }
    let exact_elapsed = exact_start.elapsed();

    let source_a = format!("{source}\n# incremental benchmark revision a\n");
    let source_b = format!("{source}\n# incremental benchmark revision b\n");
    let hir_start = Instant::now();
    for index in 0..iterations {
        let revision = if index % 2 == 0 { &source_a } else { &source_b };
        let result = session
            .compile_source(&path, black_box(revision), &entry)
            .map_err(|error| error.to_string())?;
        assert_eq!(result.status(), CacheStatus::HirReused);
        black_box(result.artifact());
    }
    let hir_elapsed = hir_start.elapsed();

    println!("cold source→HIR→arena: {cold_elapsed:?}");
    println!(
        "exact source cache hit: {:?}/iteration",
        exact_elapsed / iterations
    );
    println!(
        "changed source, identical HIR: {:?}/iteration",
        hir_elapsed / iterations
    );
    println!(
        "artifact: {} HIR nodes, {} arena nodes",
        cold.artifact().program().hir().expressions().len(),
        cold.artifact()
            .program()
            .frozen()
            .reachable_storage_node_count()
            .map_err(|error| error.to_string())?
    );
    Ok(())
}

fn usage() -> String {
    String::from("usage: incremental_compile <source.py> <qualified-entry> [iterations]")
}
