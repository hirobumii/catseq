use std::io::{self, Write};
use std::time::Duration;

use catseq_core::native_arenas::NativeArenas;
use catseq_frontend::{
    IncrementalStats, SemanticFact, SourceHirNode, TypeSignature, TypedCheckReport,
    TypedCheckSummary, TypedDefinition, TypedParameter,
};
use catseq_rtmq::OasmCallPlan;
use serde::Serialize;
use serde::ser::{SerializeSeq, SerializeStruct, Serializer};

pub(crate) fn write_check(summary: &TypedCheckSummary) -> Result<(), String> {
    write_json(&CheckJson(summary))
}

pub(crate) fn write_hir(report: &TypedCheckReport) -> Result<(), String> {
    write_json(&HirReportJson(report))
}

pub(crate) fn write_arena(
    report: &TypedCheckReport,
    program: &NativeArenas,
    lowering_time: Duration,
) -> Result<(), String> {
    write_json(&ArenaReportJson {
        report,
        program,
        lowering_time,
    })
}

pub(crate) fn write_call_plan(
    report: &TypedCheckReport,
    plan: &OasmCallPlan,
    clock_hz: u64,
    compile_time: Duration,
) -> Result<(), String> {
    write_json(&CallPlanReportJson {
        report,
        plan,
        clock_hz,
        compile_time,
    })
}

pub(crate) fn encode_call_plan(
    report: &TypedCheckReport,
    plan: &OasmCallPlan,
    clock_hz: u64,
    compile_time: Duration,
) -> Result<Vec<u8>, String> {
    serde_json::to_vec(&CallPlanReportJson {
        report,
        plan,
        clock_hz,
        compile_time,
    })
    .map_err(|error| format!("cannot encode JSON output: {error}"))
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

struct ArenaReportJson<'a> {
    report: &'a TypedCheckReport,
    program: &'a NativeArenas,
    lowering_time: Duration,
}

impl Serialize for ArenaReportJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("ArenaResponse", 10)?;
        state.serialize_field("schema_version", &1_u32)?;
        state.serialize_field("stage", "morphism_arena")?;
        state.serialize_field("entry", self.report.entry())?;
        state.serialize_field("definition_count", &self.report.definitions().len())?;
        state.serialize_field(
            "typed_hir_node_count",
            &self
                .report
                .definitions()
                .iter()
                .map(|definition| definition.hir().nodes().len())
                .sum::<usize>(),
        )?;
        state.serialize_field("morphism_arena", self.program.morphisms())?;
        state.serialize_field("value_expr_arena", self.program.values())?;
        state.serialize_field("arena_lowering_seconds", &self.lowering_time.as_secs_f64())?;
        state.serialize_field("diagnostics", self.report.diagnostics())?;
        state.serialize_field("incremental", &IncrementalJson(self.report.incremental()))?;
        state.end()
    }
}

struct CallPlanReportJson<'a> {
    report: &'a TypedCheckReport,
    plan: &'a OasmCallPlan,
    clock_hz: u64,
    compile_time: Duration,
}

impl Serialize for CallPlanReportJson<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("CallPlanResponse", 9)?;
        state.serialize_field("schema_version", &1_u32)?;
        state.serialize_field("stage", "oasm_call_plan")?;
        state.serialize_field("entry", self.report.entry())?;
        state.serialize_field("oasm_call_plan", self.plan)?;
        state.serialize_field(
            "logical_duration_cycles",
            &self.plan.logical_duration_cycles(),
        )?;
        state.serialize_field("clock_hz", &self.clock_hz)?;
        state.serialize_field("native_compile_seconds", &self.compile_time.as_secs_f64())?;
        state.serialize_field("diagnostics", self.report.diagnostics())?;
        state.serialize_field("incremental", &IncrementalJson(self.report.incremental()))?;
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
        let mut state = serializer.serialize_struct("SourceHirNode", 12)?;
        state.serialize_field("id", &self.id)?;
        state.serialize_field("kind", self.node.kind().as_str())?;
        state.serialize_field("symbol", &self.node.symbol())?;
        state.serialize_field(
            "morphism_composition",
            &self
                .node
                .morphism_composition()
                .map(|operation| operation.as_str()),
        )?;
        state.serialize_field("literal", &self.node.literal())?;
        state.serialize_field(
            "value_operation",
            &self
                .node
                .value_operation()
                .map(|operation| operation.as_str()),
        )?;
        state.serialize_field(
            "comparison_operations",
            &self
                .node
                .comparison_operations()
                .iter()
                .map(|operation| operation.as_str())
                .collect::<Vec<_>>(),
        )?;
        state.serialize_field("edge_start", &self.node.edge_start())?;
        state.serialize_field("edge_count", &self.node.edge_count())?;
        state.serialize_field("control_body_count", &self.node.control_body_count())?;
        state.serialize_field("control_else_count", &self.node.control_else_count())?;
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
