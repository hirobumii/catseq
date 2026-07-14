use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use catseq_frontend::{
    TypedCheckReport, check_typed_bundle_entry_incremental_with_loader,
    check_typed_bundle_entry_with_loader, check_typed_entry, check_typed_entry_incremental,
};

fn main() -> ExitCode {
    match run(env::args().skip(1)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("catseqc: {message}");
            ExitCode::from(1)
        }
    }
}

fn run(mut args: impl Iterator<Item = String>) -> Result<(), String> {
    let command = args.next().ok_or_else(usage)?;
    if command != "check" {
        return Err(format!("unknown command {command:?}\n{}", usage()));
    }
    let path = args.next().ok_or_else(usage)?;
    let mut requested_entry = None;
    let mut output_format = OutputFormat::Text;
    let mut cache_dir = None::<PathBuf>;
    let mut source_root = None::<PathBuf>;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--entry" => requested_entry = Some(args.next().ok_or_else(usage)?),
            "--format" => {
                let value = args.next().ok_or_else(usage)?;
                output_format = OutputFormat::parse(&value)?;
            }
            "--cache-dir" => cache_dir = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--source-root" => source_root = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            _ => return Err(format!("unexpected argument {flag:?}\n{}", usage())),
        }
    }

    let source =
        fs::read_to_string(&path).map_err(|error| format!("cannot read {path}: {error}"))?;
    let requested = requested_entry.ok_or_else(|| format!("--entry is required\n{}", usage()))?;
    let report = match (source_root, cache_dir) {
        (Some(source_root), None) => {
            let entry_module = module_name(&source_root, PathBuf::from(&path).as_path())?;
            let mut loaded = BTreeMap::from([(entry_module.clone(), source.clone())]);
            let mut loader = |module: &str| -> Result<Option<String>, String> {
                if let Some(source) = loaded.get(module) {
                    return Ok(Some(source.clone()));
                }
                let source = load_source_module(&source_root, module)?;
                if let Some(source) = &source {
                    loaded.insert(module.to_owned(), source.clone());
                }
                Ok(source)
            };
            check_typed_bundle_entry_with_loader(&entry_module, &requested, &mut loader)
                .map_err(|error| error.to_string())?
        }
        (Some(source_root), Some(cache_dir)) => {
            let entry_module = module_name(&source_root, PathBuf::from(&path).as_path())?;
            let mut loaded = BTreeMap::from([(entry_module.clone(), source.clone())]);
            let mut loader = |module: &str| -> Result<Option<String>, String> {
                if let Some(source) = loaded.get(module) {
                    return Ok(Some(source.clone()));
                }
                let source = load_source_module(&source_root, module)?;
                if let Some(source) = &source {
                    loaded.insert(module.to_owned(), source.clone());
                }
                Ok(source)
            };
            check_typed_bundle_entry_incremental_with_loader(
                &entry_module,
                &requested,
                &cache_dir,
                &mut loader,
            )
            .map_err(|error| error.to_string())?
        }
        (None, Some(cache_dir)) => {
            check_typed_entry_incremental(&path, &source, &requested, &cache_dir)
                .map_err(|error| error.to_string())?
        }
        (None, None) => {
            check_typed_entry(&path, &source, &requested).map_err(|error| error.to_string())?
        }
    };
    match output_format {
        OutputFormat::Text => print_text_report(&report),
        OutputFormat::Json => println!("{}", report_json(&report)),
    }
    Ok(())
}

fn print_text_report(report: &TypedCheckReport) {
    let hir_nodes: usize = report
        .definitions()
        .iter()
        .map(|definition| definition.hir().nodes().len())
        .sum();
    println!(
        "{} ({} definitions, {} typed HIR nodes)",
        report.entry(),
        report.definitions().len(),
        hir_nodes,
    );
}

fn usage() -> String {
    String::from(
        "usage: catseqc check <source.py> [--source-root <path>] [--entry <qualified-name>] [--format text|json] [--cache-dir <path>]",
    )
}

fn load_source_module(root: &std::path::Path, module: &str) -> Result<Option<String>, String> {
    let relative = module.replace('.', std::path::MAIN_SEPARATOR_STR);
    let candidates = [
        root.join(&relative).with_extension("py"),
        root.join(&relative).join("__init__.py"),
    ];
    for path in candidates {
        if !path.is_file() {
            continue;
        }
        let source = fs::read_to_string(&path)
            .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
        return Ok(Some(source));
    }
    Ok(None)
}

fn module_name(root: &std::path::Path, path: &std::path::Path) -> Result<String, String> {
    let relative = path.strip_prefix(root).map_err(|_| {
        format!(
            "{} is outside source root {}",
            path.display(),
            root.display()
        )
    })?;
    let mut components: Vec<String> = relative
        .components()
        .map(|component| component.as_os_str().to_string_lossy().into_owned())
        .collect();
    let file = components
        .pop()
        .ok_or_else(|| format!("{} is not a Python module", path.display()))?;
    let stem = file
        .strip_suffix(".py")
        .ok_or_else(|| format!("{} is not a Python module", path.display()))?;
    if stem != "__init__" {
        components.push(stem.to_owned());
    }
    Ok(components.join("."))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OutputFormat {
    Text,
    Json,
}

impl OutputFormat {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "text" => Ok(Self::Text),
            "json" => Ok(Self::Json),
            _ => Err(format!(
                "unknown output format {value:?}; expected text or json"
            )),
        }
    }
}

fn report_json(report: &TypedCheckReport) -> serde_json::Value {
    let definitions: Vec<_> = report
        .definitions()
        .iter()
        .map(|definition| {
            let parameters: Vec<_> = definition
                .signature()
                .parameters()
                .iter()
                .map(|parameter| {
                    serde_json::json!({
                        "name": parameter.name(),
                        "type": parameter.source_type().to_string(),
                    })
                })
                .collect();
            serde_json::json!({
                "module": definition.module(),
                "qualified_name": definition.qualified_name(),
                "parameters": parameters,
                "return_type": definition.signature().return_type().to_string(),
                "hir": {
                    "definition": definition.hir().definition(),
                    "roots": definition.hir().roots(),
                    "edges": definition.hir().edges(),
                    "nodes": definition.hir().nodes().iter().enumerate().map(|(id, node)| {
                        serde_json::json!({
                            "id": id,
                            "kind": node.kind().as_str(),
                            "symbol": node.symbol(),
                            "edge_start": node.edge_start(),
                            "edge_count": node.edge_count(),
                            "anchor": {
                                "module": node.anchor().module(),
                                "line": node.anchor().line(),
                                "column": node.anchor().column(),
                            },
                        })
                    }).collect::<Vec<_>>(),
                    "facts": definition.hir().facts().iter().map(|fact| {
                        serde_json::json!({
                            "type": fact.source_type().map(ToString::to_string),
                            "availability": fact.availability().as_str(),
                            "roles": fact.roles().iter().map(|role| role.as_str()).collect::<Vec<_>>(),
                            "resolved_node": fact.resolved_node(),
                            "resolved_definition": fact.resolved_definition(),
                            "phase_frame": fact.phase_frame(),
                            "compile_value": fact.compile_value(),
                        })
                    }).collect::<Vec<_>>(),
                },
            })
        })
        .collect();
    serde_json::json!({
        "schema_version": report.schema_version(),
        "entry": report.entry(),
        "definitions": definitions,
        "diagnostics": report.diagnostics(),
        "incremental": {
            "executed": report.incremental().executed(),
            "green": report.incremental().green(),
            "red": report.incremental().red(),
            "result_cache_loads": report.incremental().result_cache_loads(),
            "bytes_read": report.incremental().bytes_read(),
            "bytes_written": report.incremental().bytes_written(),
            "fingerprint_nanos": report.incremental().fingerprint_nanos(),
            "executed_by_kind": report.incremental().executed_by_kind(),
        },
    })
}
