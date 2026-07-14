use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::ExitCode;

use catseq_frontend::{
    IncrementalStats, SemanticFact, SourceHirNode, TypeSignature, TypedCheckReport,
    TypedCheckSummary, TypedDefinition, TypedParameter,
    check_typed_bundle_entry_incremental_with_loader,
    check_typed_bundle_entry_summary_incremental_with_loader, check_typed_bundle_entry_with_loader,
    check_typed_entry, check_typed_entry_incremental, check_typed_entry_summary_incremental,
};
use serde::Serialize;
use serde::ser::{SerializeSeq, SerializeStruct, Serializer};

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
    let command = CommandKind::parse(&args.next().ok_or_else(usage)?)?;
    let path = args.next().ok_or_else(usage)?;
    let mut requested_entry = None;
    let mut output_format = command.default_output_format();
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
    if command == CommandKind::EmitHir && output_format != OutputFormat::Json {
        return Err("emit-hir requires --format json".to_owned());
    }

    let source =
        fs::read_to_string(&path).map_err(|error| format!("cannot read {path}: {error}"))?;
    let requested = requested_entry.ok_or_else(|| format!("--entry is required\n{}", usage()))?;
    let checked = match source_root {
        Some(source_root) => check_source_bundle(
            &source_root,
            PathBuf::from(&path).as_path(),
            source,
            &requested,
            cache_dir.as_deref(),
            command,
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
        },
    };
    match (checked, output_format) {
        (CheckedOutput::Summary(summary), OutputFormat::Text) => print_text_summary(&summary),
        (CheckedOutput::Summary(summary), OutputFormat::Json) => write_json(&CheckJson(&summary))?,
        (CheckedOutput::Report(report), OutputFormat::Json) => write_json(&HirReportJson(&report))?,
        (CheckedOutput::Report(_), OutputFormat::Text) => {
            unreachable!("emit-hir text output is rejected before compilation")
        }
    }
    Ok(())
}

enum CheckedOutput {
    Summary(TypedCheckSummary),
    Report(TypedCheckReport),
}

fn check_source_bundle(
    source_root: &std::path::Path,
    entry_path: &std::path::Path,
    entry_source: String,
    requested: &str,
    cache_dir: Option<&std::path::Path>,
    command: CommandKind,
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
    }
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
        "usage: catseqc check <source.py> [--source-root <path>] [--entry <qualified-name>] [--format text|json] [--cache-dir <path>]\n       catseqc emit-hir <source.py> [--source-root <path>] [--entry <qualified-name>] [--format json] [--cache-dir <path>]",
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
}

impl CommandKind {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "check" => Ok(Self::Check),
            "emit-hir" => Ok(Self::EmitHir),
            _ => Err(format!("unknown command {value:?}\n{}", usage())),
        }
    }

    const fn default_output_format(self) -> OutputFormat {
        match self {
            Self::Check => OutputFormat::Text,
            Self::EmitHir => OutputFormat::Json,
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

fn write_json(value: &impl Serialize) -> Result<(), String> {
    let stdout = io::stdout();
    let mut output = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(&mut output, value)
        .map_err(|error| format!("cannot encode JSON output: {error}"))?;
    writeln!(output).map_err(|error| format!("cannot write JSON output: {error}"))
}

struct CheckJson<'a>(&'a TypedCheckSummary);

impl Serialize for CheckJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let summary = self.0;
        let mut state = serializer.serialize_struct("CheckResponse", 7)?;
        state.serialize_field("schema_version", &summary.schema_version())?;
        state.serialize_field("entry", summary.entry())?;
        state.serialize_field("entry_signature", &SignatureJson(summary.entry_signature()))?;
        state.serialize_field("definition_count", &summary.definition_count())?;
        state.serialize_field("hir_node_count", &summary.hir_node_count())?;
        state.serialize_field("diagnostics", summary.diagnostics())?;
        state.serialize_field("incremental", &IncrementalJson(summary.incremental()))?;
        state.end()
    }
}

struct HirReportJson<'a>(&'a TypedCheckReport);

impl Serialize for HirReportJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let report = self.0;
        let mut state = serializer.serialize_struct("HirResponse", 5)?;
        state.serialize_field("schema_version", &report.schema_version())?;
        state.serialize_field("entry", report.entry())?;
        state.serialize_field("definitions", &DefinitionsJson(report.definitions()))?;
        state.serialize_field("diagnostics", report.diagnostics())?;
        state.serialize_field("incremental", &IncrementalJson(report.incremental()))?;
        state.end()
    }
}

struct IncrementalJson<'a>(&'a IncrementalStats);

impl Serialize for IncrementalJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let stats = self.0;
        let mut state = serializer.serialize_struct("IncrementalStats", 8)?;
        state.serialize_field("executed", &stats.executed())?;
        state.serialize_field("green", &stats.green())?;
        state.serialize_field("red", &stats.red())?;
        state.serialize_field("result_cache_loads", &stats.result_cache_loads())?;
        state.serialize_field("bytes_read", &stats.bytes_read())?;
        state.serialize_field("bytes_written", &stats.bytes_written())?;
        state.serialize_field("fingerprint_seconds", &stats.fingerprint_seconds())?;
        state.serialize_field("executed_by_kind", stats.executed_by_kind())?;
        state.end()
    }
}

struct SignatureJson<'a>(&'a TypeSignature);

impl Serialize for SignatureJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("TypeSignature", 2)?;
        state.serialize_field("parameters", &ParametersJson(self.0.parameters()))?;
        state.serialize_field("return_type", &DisplayJson(self.0.return_type()))?;
        state.end()
    }
}

struct ParametersJson<'a>(&'a [TypedParameter]);

impl Serialize for ParametersJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for parameter in self.0 {
            sequence.serialize_element(&ParameterJson(parameter))?;
        }
        sequence.end()
    }
}

struct ParameterJson<'a>(&'a TypedParameter);

impl Serialize for ParameterJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("TypedParameter", 2)?;
        state.serialize_field("name", self.0.name())?;
        state.serialize_field("type", &DisplayJson(self.0.source_type()))?;
        state.end()
    }
}

struct DefinitionsJson<'a>(&'a [TypedDefinition]);

impl Serialize for DefinitionsJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for definition in self.0 {
            sequence.serialize_element(&DefinitionJson(definition))?;
        }
        sequence.end()
    }
}

struct DefinitionJson<'a>(&'a TypedDefinition);

impl Serialize for DefinitionJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let definition = self.0;
        let mut state = serializer.serialize_struct("TypedDefinition", 5)?;
        state.serialize_field("module", definition.module())?;
        state.serialize_field("qualified_name", definition.qualified_name())?;
        state.serialize_field(
            "parameters",
            &ParametersJson(definition.signature().parameters()),
        )?;
        state.serialize_field(
            "return_type",
            &DisplayJson(definition.signature().return_type()),
        )?;
        state.serialize_field("hir", &HirJson(definition))?;
        state.end()
    }
}

struct HirJson<'a>(&'a TypedDefinition);

impl Serialize for HirJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let hir = self.0.hir();
        let mut state = serializer.serialize_struct("TypedSourceHir", 5)?;
        state.serialize_field("definition", hir.definition())?;
        state.serialize_field("roots", hir.roots())?;
        state.serialize_field("edges", hir.edges())?;
        state.serialize_field("nodes", &NodesJson(hir.nodes()))?;
        state.serialize_field("facts", &FactsJson(hir.facts()))?;
        state.end()
    }
}

struct NodesJson<'a>(&'a [SourceHirNode]);

impl Serialize for NodesJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for (id, node) in self.0.iter().enumerate() {
            sequence.serialize_element(&NodeJson { id, node })?;
        }
        sequence.end()
    }
}

struct NodeJson<'a> {
    id: usize,
    node: &'a SourceHirNode,
}

impl Serialize for NodeJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("SourceHirNode", 6)?;
        state.serialize_field("id", &self.id)?;
        state.serialize_field("kind", self.node.kind().as_str())?;
        state.serialize_field("symbol", &self.node.symbol())?;
        state.serialize_field("edge_start", &self.node.edge_start())?;
        state.serialize_field("edge_count", &self.node.edge_count())?;
        state.serialize_field("anchor", &AnchorJson(self.node))?;
        state.end()
    }
}

struct AnchorJson<'a>(&'a SourceHirNode);

impl Serialize for AnchorJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let anchor = self.0.anchor();
        let mut state = serializer.serialize_struct("SourceAnchor", 3)?;
        state.serialize_field("module", anchor.module())?;
        state.serialize_field("line", &anchor.line())?;
        state.serialize_field("column", &anchor.column())?;
        state.end()
    }
}

struct FactsJson<'a>(&'a [SemanticFact]);

impl Serialize for FactsJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for fact in self.0 {
            sequence.serialize_element(&FactJson(fact))?;
        }
        sequence.end()
    }
}

struct FactJson<'a>(&'a SemanticFact);

impl Serialize for FactJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let fact = self.0;
        let mut state = serializer.serialize_struct("SemanticFact", 8)?;
        state.serialize_field("type", &OptionalDisplayJson(fact.source_type()))?;
        state.serialize_field("availability", fact.availability().as_str())?;
        state.serialize_field("roles", &RolesJson(fact))?;
        state.serialize_field("resolved_node", &fact.resolved_node())?;
        state.serialize_field("resolved_definition", &fact.resolved_definition())?;
        state.serialize_field("resolved_definitions", fact.resolved_definitions())?;
        state.serialize_field("phase_frame", &fact.phase_frame())?;
        state.serialize_field("compile_value", &fact.compile_value())?;
        state.end()
    }
}

struct RolesJson<'a>(&'a SemanticFact);

impl Serialize for RolesJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let roles = self.0.roles();
        let mut sequence = serializer.serialize_seq(Some(roles.len()))?;
        for role in roles {
            sequence.serialize_element(role.as_str())?;
        }
        sequence.end()
    }
}

struct DisplayJson<'a, T>(&'a T);

impl<T> Serialize for DisplayJson<'_, T>
where
    T: std::fmt::Display,
{
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self.0)
    }
}

struct OptionalDisplayJson<'a, T>(Option<&'a T>);

impl<T> Serialize for OptionalDisplayJson<'_, T>
where
    T: std::fmt::Display,
{
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.0 {
            Some(value) => serializer.serialize_some(&DisplayJson(value)),
            None => serializer.serialize_none(),
        }
    }
}
