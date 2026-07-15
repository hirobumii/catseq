use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use catseq_core::native_arenas::NativeArenas;
use catseq_frontend::{
    TypedCheckReport, TypedCheckSummary, check_typed_bundle_entry_incremental_with_loader,
    check_typed_bundle_entry_summary_incremental_with_loader, check_typed_bundle_entry_with_loader,
    check_typed_entry, check_typed_entry_incremental, check_typed_entry_summary_incremental,
    lower_typed_report_to_native_arenas, specialize_typed_report_to_native_arenas,
};
use catseq_rtmq::{
    CompileEnvironment, LinkBindings, OasmCallPlan, TargetProfile, compile_oasm_call_plan,
};
use serde::Deserialize;

mod compiler_thread;
mod response;

pub use compiler_thread::{CompilerThreadError, run_compiler_thread};

pub fn run_cli(args: impl IntoIterator<Item = String>) -> Result<(), String> {
    run(args.into_iter())
}

fn run(mut args: impl Iterator<Item = String>) -> Result<(), String> {
    let first = args.next().ok_or_else(usage)?;
    if first == "--version" {
        println!("catseqc {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    let command = CommandKind::parse(&first)?;
    let path = args.next().ok_or_else(usage)?;
    let mut requested_entry = None;
    let mut output_format = command.default_output_format();
    let mut cache_dir = None::<PathBuf>;
    let mut source_root = None::<PathBuf>;
    let mut compile_environment_path = None::<PathBuf>;
    let mut target_profile_path = None::<PathBuf>;
    let mut link_bindings_path = None::<PathBuf>;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--entry" => requested_entry = Some(args.next().ok_or_else(usage)?),
            "--format" => {
                let value = args.next().ok_or_else(usage)?;
                output_format = OutputFormat::parse(&value)?;
            }
            "--cache-dir" => cache_dir = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--source-root" => source_root = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--compile-environment" => {
                compile_environment_path = Some(PathBuf::from(args.next().ok_or_else(usage)?))
            }
            "--target-profile" => {
                target_profile_path = Some(PathBuf::from(args.next().ok_or_else(usage)?))
            }
            "--link-bindings" => {
                link_bindings_path = Some(PathBuf::from(args.next().ok_or_else(usage)?))
            }
            _ => return Err(format!("unexpected argument {flag:?}\n{}", usage())),
        }
    }
    if command != CommandKind::Check && output_format != OutputFormat::Json {
        return Err(format!("{} requires --format json", command.as_str()));
    }

    let source =
        fs::read_to_string(&path).map_err(|error| format!("cannot read {path}: {error}"))?;
    let requested = requested_entry.ok_or_else(|| format!("--entry is required\n{}", usage()))?;
    let compile_environment = compile_environment_path
        .as_ref()
        .map(|path| {
            let bytes = fs::read(path)
                .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
            serde_json::from_slice::<CompileEnvironment>(&bytes).map_err(|error| {
                format!(
                    "cannot decode compile environment {}: {error}",
                    path.display()
                )
            })
        })
        .transpose()?;
    if command == CommandKind::Compile && compile_environment.is_none() {
        return Err(format!("--compile-environment is required\n{}", usage()));
    }
    let target_profile = target_profile_path
        .as_ref()
        .map(|path| {
            let bytes = fs::read(path)
                .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
            if path.extension().and_then(|extension| extension.to_str()) == Some("toml") {
                let source = std::str::from_utf8(&bytes).map_err(|error| {
                    format!("cannot decode target profile {}: {error}", path.display())
                })?;
                toml::from_str::<TargetProfile>(source).map_err(|error| {
                    format!("cannot decode target profile {}: {error}", path.display())
                })
            } else {
                serde_json::from_slice::<TargetProfile>(&bytes).map_err(|error| {
                    format!("cannot decode target profile {}: {error}", path.display())
                })
            }
        })
        .transpose()?;
    if command == CommandKind::Compile && target_profile.is_none() {
        return Err(format!("--target-profile is required\n{}", usage()));
    }
    let link_bindings = link_bindings_path
        .as_ref()
        .map(|path| {
            let bytes = fs::read(path)
                .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
            serde_json::from_slice::<LinkBindings>(&bytes)
                .map_err(|error| format!("cannot decode link bindings {}: {error}", path.display()))
        })
        .transpose()?
        .unwrap_or_else(LinkBindings::empty);
    let checked = match source_root {
        Some(source_root) => check_source_bundle(
            &source_root,
            PathBuf::from(&path).as_path(),
            source,
            &requested,
            cache_dir.as_deref(),
            command,
            NativeCompileInputs {
                environment: compile_environment.as_ref(),
                target: target_profile.as_ref(),
                link_bindings: &link_bindings,
            },
        )?,
        None => match (command, cache_dir) {
            (CommandKind::Check, Some(cache_dir)) => CheckedOutput::Summary(
                check_typed_entry_summary_incremental(&path, &source, &requested, &cache_dir)
                    .map_err(|error| error.to_string())?,
            ),
            (CommandKind::Check, None) => CheckedOutput::Summary(
                check_typed_entry(&path, &source, &requested)
                    .map_err(|error| error.to_string())?
                    .summary(),
            ),
            (CommandKind::EmitHir, Some(cache_dir)) => CheckedOutput::Report(
                check_typed_entry_incremental(&path, &source, &requested, &cache_dir)
                    .map_err(|error| error.to_string())?,
            ),
            (CommandKind::EmitHir, None) => CheckedOutput::Report(
                check_typed_entry(&path, &source, &requested).map_err(|error| error.to_string())?,
            ),
            (CommandKind::EmitArena, Some(cache_dir)) => {
                let report = check_typed_entry_incremental(&path, &source, &requested, &cache_dir)
                    .map_err(|error| error.to_string())?;
                arena_output(report)?
            }
            (CommandKind::EmitArena, None) => {
                let report = check_typed_entry(&path, &source, &requested)
                    .map_err(|error| error.to_string())?;
                arena_output(report)?
            }
            (CommandKind::Compile, Some(cache_dir)) => {
                let report = check_typed_entry_incremental(&path, &source, &requested, &cache_dir)
                    .map_err(|error| error.to_string())?;
                compile_output(
                    report,
                    compile_environment.as_ref().expect("checked above"),
                    target_profile.as_ref().expect("checked above"),
                    &link_bindings,
                )?
            }
            (CommandKind::Compile, None) => {
                let report = check_typed_entry(&path, &source, &requested)
                    .map_err(|error| error.to_string())?;
                compile_output(
                    report,
                    compile_environment.as_ref().expect("checked above"),
                    target_profile.as_ref().expect("checked above"),
                    &link_bindings,
                )?
            }
        },
    };
    match (checked, output_format) {
        (CheckedOutput::Summary(summary), OutputFormat::Text) => print_text_summary(&summary),
        (CheckedOutput::Summary(summary), OutputFormat::Json) => response::write_check(&summary)?,
        (CheckedOutput::Report(report), OutputFormat::Json) => response::write_hir(&report)?,
        (CheckedOutput::Report(_), OutputFormat::Text) => {
            unreachable!("emit-hir text output is rejected before compilation")
        }
        (CheckedOutput::Arena { report, program }, OutputFormat::Json) => {
            response::write_arena(&report, &program.0, program.1)?
        }
        (CheckedOutput::Arena { .. }, OutputFormat::Text) => {
            unreachable!("emit-arena text output is rejected before compilation")
        }
        (
            CheckedOutput::CallPlan {
                report,
                plan,
                clock_hz,
                compile_time,
            },
            OutputFormat::Json,
        ) => response::write_call_plan(&report, &plan, clock_hz, compile_time)?,
        (CheckedOutput::CallPlan { .. }, OutputFormat::Text) => {
            unreachable!("compile text output is rejected before compilation")
        }
    }
    Ok(())
}

enum CheckedOutput {
    Summary(TypedCheckSummary),
    Report(TypedCheckReport),
    Arena {
        report: TypedCheckReport,
        program: (Box<NativeArenas>, Duration),
    },
    CallPlan {
        report: TypedCheckReport,
        plan: OasmCallPlan,
        clock_hz: u64,
        compile_time: Duration,
    },
}

fn arena_output(report: TypedCheckReport) -> Result<CheckedOutput, String> {
    let start = Instant::now();
    let program = lower_typed_report_to_native_arenas(&report, 250_000_000)
        .map_err(|error| error.to_string())?;
    let lowering_time = start.elapsed();
    Ok(CheckedOutput::Arena {
        report,
        program: (Box::new(program), lowering_time),
    })
}

fn compile_output(
    report: TypedCheckReport,
    environment: &CompileEnvironment,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<CheckedOutput, String> {
    let start = Instant::now();
    let program = specialize_typed_report_to_native_arenas(&report, target.clock_hz())
        .map_err(|error| error.to_string())?;
    let plan = compile_oasm_call_plan(&program, environment, target, link_bindings)
        .map_err(|error| error.to_string())?;
    Ok(CheckedOutput::CallPlan {
        report,
        plan,
        clock_hz: target.clock_hz(),
        compile_time: start.elapsed(),
    })
}

fn check_source_bundle(
    source_root: &std::path::Path,
    entry_path: &std::path::Path,
    entry_source: String,
    requested: &str,
    cache_dir: Option<&std::path::Path>,
    command: CommandKind,
    compile_inputs: NativeCompileInputs<'_>,
) -> Result<CheckedOutput, String> {
    let entry_module = module_name(source_root, entry_path)?;
    let mut loaded = BTreeMap::from([(entry_module.clone(), entry_source)]);
    let mut loader = |module: &str| -> Result<Option<String>, String> {
        if let Some(source) = loaded.get(module) {
            return Ok(Some(source.clone()));
        }
        let source = load_source_module(source_root, module)?;
        if let Some(source) = &source {
            loaded.insert(module.to_owned(), source.clone());
        }
        Ok(source)
    };
    match (command, cache_dir) {
        (CommandKind::Check, Some(cache_dir)) => Ok(CheckedOutput::Summary(
            check_typed_bundle_entry_summary_incremental_with_loader(
                &entry_module,
                requested,
                cache_dir,
                &mut loader,
            )
            .map_err(|error| error.to_string())?,
        )),
        (CommandKind::Check, None) => Ok(CheckedOutput::Summary(
            check_typed_bundle_entry_with_loader(&entry_module, requested, &mut loader)
                .map_err(|error| error.to_string())?
                .summary(),
        )),
        (CommandKind::EmitHir, Some(cache_dir)) => Ok(CheckedOutput::Report(
            check_typed_bundle_entry_incremental_with_loader(
                &entry_module,
                requested,
                cache_dir,
                &mut loader,
            )
            .map_err(|error| error.to_string())?,
        )),
        (CommandKind::EmitHir, None) => Ok(CheckedOutput::Report(
            check_typed_bundle_entry_with_loader(&entry_module, requested, &mut loader)
                .map_err(|error| error.to_string())?,
        )),
        (CommandKind::EmitArena, Some(cache_dir)) => {
            let report = check_typed_bundle_entry_incremental_with_loader(
                &entry_module,
                requested,
                cache_dir,
                &mut loader,
            )
            .map_err(|error| error.to_string())?;
            arena_output(report)
        }
        (CommandKind::EmitArena, None) => {
            let report =
                check_typed_bundle_entry_with_loader(&entry_module, requested, &mut loader)
                    .map_err(|error| error.to_string())?;
            arena_output(report)
        }
        (CommandKind::Compile, Some(cache_dir)) => {
            let report = check_typed_bundle_entry_incremental_with_loader(
                &entry_module,
                requested,
                cache_dir,
                &mut loader,
            )
            .map_err(|error| error.to_string())?;
            compile_output(
                report,
                compile_inputs.environment.expect("validated by caller"),
                compile_inputs.target.expect("validated by caller"),
                compile_inputs.link_bindings,
            )
        }
        (CommandKind::Compile, None) => {
            let report =
                check_typed_bundle_entry_with_loader(&entry_module, requested, &mut loader)
                    .map_err(|error| error.to_string())?;
            compile_output(
                report,
                compile_inputs.environment.expect("validated by caller"),
                compile_inputs.target.expect("validated by caller"),
                compile_inputs.link_bindings,
            )
        }
    }
}

#[derive(Clone, Copy)]
struct NativeCompileInputs<'a> {
    environment: Option<&'a CompileEnvironment>,
    target: Option<&'a TargetProfile>,
    link_bindings: &'a LinkBindings,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CompileRequest {
    schema_version: u32,
    source_path: PathBuf,
    source_root: PathBuf,
    entry: String,
    compile_environment: CompileEnvironment,
    target_profile: TargetProfile,
    link_bindings: LinkBindings,
    #[serde(default)]
    cache_dir: Option<PathBuf>,
}

pub fn compile_json_request(request: &[u8]) -> Result<Vec<u8>, String> {
    let request = serde_json::from_slice::<CompileRequest>(request)
        .map_err(|error| format!("cannot decode compile request: {error}"))?;
    if request.schema_version != 1 {
        return Err(format!(
            "unsupported compile request schema version {}",
            request.schema_version
        ));
    }
    let source = fs::read_to_string(&request.source_path)
        .map_err(|error| format!("cannot read {}: {error}", request.source_path.display()))?;
    let output = check_source_bundle(
        &request.source_root,
        &request.source_path,
        source,
        &request.entry,
        request.cache_dir.as_deref(),
        CommandKind::Compile,
        NativeCompileInputs {
            environment: Some(&request.compile_environment),
            target: Some(&request.target_profile),
            link_bindings: &request.link_bindings,
        },
    )?;
    let CheckedOutput::CallPlan {
        report,
        plan,
        clock_hz,
        compile_time,
    } = output
    else {
        unreachable!("compile command always returns an OASM call plan")
    };
    response::encode_call_plan(&report, &plan, clock_hz, compile_time)
}

fn print_text_summary(summary: &TypedCheckSummary) {
    println!(
        "{} ({} definitions, {} typed HIR nodes)",
        summary.entry(),
        summary.definition_count(),
        summary.hir_node_count(),
    );
}

fn usage() -> String {
    String::from(
        "usage: catseqc --version\n       catseqc check <source.py> [--source-root <path>] [--entry <qualified-name>] [--format text|json] [--cache-dir <path>]\n       catseqc emit-hir <source.py> [--source-root <path>] [--entry <qualified-name>] [--format json] [--cache-dir <path>]\n       catseqc emit-arena <source.py> [--source-root <path>] [--entry <qualified-name>] [--format json] [--cache-dir <path>]\n       catseqc compile <source.py> [--source-root <path>] --entry <qualified-name> --compile-environment <path> --target-profile <path> [--link-bindings <path>] [--format json] [--cache-dir <path>]",
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CommandKind {
    Check,
    EmitHir,
    EmitArena,
    Compile,
}

impl CommandKind {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "check" => Ok(Self::Check),
            "emit-hir" => Ok(Self::EmitHir),
            "emit-arena" => Ok(Self::EmitArena),
            "compile" => Ok(Self::Compile),
            _ => Err(format!("unknown command {value:?}\n{}", usage())),
        }
    }

    const fn default_output_format(self) -> OutputFormat {
        match self {
            Self::Check => OutputFormat::Text,
            Self::EmitHir | Self::EmitArena | Self::Compile => OutputFormat::Json,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Check => "check",
            Self::EmitHir => "emit-hir",
            Self::EmitArena => "emit-arena",
            Self::Compile => "compile",
        }
    }
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
