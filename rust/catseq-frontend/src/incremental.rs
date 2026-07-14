//! Minimal rustc-style incremental query graph for typed source checks.

use std::collections::{BTreeMap, HashMap};
use std::error::Error;
use std::fmt::Write as _;
use std::fmt::{Display, Formatter};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha3::{Digest, Sha3_256};

use crate::intrinsics::REGISTRY_SEMANTIC_VERSION;
use crate::typed::IncrementalStatsSnapshot;
use crate::{
    IncrementalStats, TypeSignature, TypedCheckError, TypedCheckReport, TypedCheckSummary,
    TypedDefinition, check_typed_bundle_entry_with_loader, check_typed_entry,
};

const CACHE_FORMAT_VERSION: u32 = 14;
const FRONTEND_SEMANTIC_VERSION: u32 = 12;
const DEP_GRAPH_FILE: &str = "dep-graph.json";
const CURRENT_FILE: &str = "CURRENT";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
struct Fingerprint([u8; 16]);

impl Fingerprint {
    fn of_bytes(bytes: &[u8]) -> Self {
        let digest = Sha3_256::digest(bytes);
        let mut fingerprint = [0; 16];
        fingerprint.copy_from_slice(&digest[..16]);
        Self(fingerprint)
    }

    fn of_parts(parts: &[&str]) -> Self {
        let mut hasher = Sha3_256::new();
        for part in parts {
            hasher.update((part.len() as u64).to_le_bytes());
            hasher.update(part.as_bytes());
        }
        let digest = hasher.finalize();
        let mut fingerprint = [0; 16];
        fingerprint.copy_from_slice(&digest[..16]);
        Self(fingerprint)
    }

    fn hex(self) -> String {
        let mut encoded = String::with_capacity(32);
        for byte in self.0 {
            write!(encoded, "{byte:02x}").expect("writing to a String cannot fail");
        }
        encoded
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
enum DepKind {
    SourceText,
    ParseModule,
    IndexModule,
    DefinitionHeader,
    LowerSourceHir,
    ResolveDefinition,
    ReachableDefinitions,
    InferTypes,
    InferAvailability,
    AnalyzeDependencyRoles,
    CollectDiagnostics,
    CheckEntry,
}

impl DepKind {
    const fn as_str(self) -> &'static str {
        match self {
            Self::SourceText => "SourceText",
            Self::ParseModule => "ParseModule",
            Self::IndexModule => "IndexModule",
            Self::DefinitionHeader => "DefinitionHeader",
            Self::LowerSourceHir => "LowerSourceHir",
            Self::ResolveDefinition => "ResolveDefinition",
            Self::ReachableDefinitions => "ReachableDefinitions",
            Self::InferTypes => "InferTypes",
            Self::InferAvailability => "InferAvailability",
            Self::AnalyzeDependencyRoles => "AnalyzeDependencyRoles",
            Self::CollectDiagnostics => "CollectDiagnostics",
            Self::CheckEntry => "CheckEntry",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct StoredNode {
    kind: DepKind,
    key_fingerprint: Fingerprint,
    result_fingerprint: Fingerprint,
    edge_start: u32,
    edge_count: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CachedReport {
    node_key: Fingerprint,
    result_fingerprint: Fingerprint,
    entry: String,
    definitions: Vec<TypedDefinition>,
    diagnostics: Vec<String>,
    queried_modules: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CachedSummary {
    node_key: Fingerprint,
    result_fingerprint: Fingerprint,
    entry: String,
    entry_signature: TypeSignature,
    definition_count: usize,
    hir_node_count: usize,
    diagnostics: Vec<String>,
    queried_modules: Vec<String>,
}

impl CachedSummary {
    fn from_report(
        node_key: Fingerprint,
        result_fingerprint: Fingerprint,
        report: &TypedCheckReport,
    ) -> Self {
        let summary = report.summary();
        Self {
            node_key,
            result_fingerprint,
            entry: summary.entry().to_owned(),
            entry_signature: summary.entry_signature().clone(),
            definition_count: summary.definition_count(),
            hir_node_count: summary.hir_node_count(),
            diagnostics: summary.diagnostics().to_vec(),
            queried_modules: summary.queried_modules().to_vec(),
        }
    }

    fn into_summary(self, incremental: IncrementalStats) -> TypedCheckSummary {
        TypedCheckSummary::from_cached(
            self.entry,
            self.entry_signature,
            self.definition_count,
            self.hir_node_count,
            self.diagnostics,
            self.queried_modules,
            incremental,
        )
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CachedReportRef {
    node_key: Fingerprint,
    result_fingerprint: Fingerprint,
    file_name: String,
}

impl CachedReport {
    fn from_report(
        node_key: Fingerprint,
        result_fingerprint: Fingerprint,
        report: &TypedCheckReport,
    ) -> Self {
        Self {
            node_key,
            result_fingerprint,
            entry: report.entry().to_owned(),
            definitions: report.definitions().to_vec(),
            diagnostics: report.diagnostics().to_vec(),
            queried_modules: report.queried_modules().to_vec(),
        }
    }

    fn into_report(self, incremental: IncrementalStats) -> TypedCheckReport {
        TypedCheckReport::from_cached(
            self.entry,
            self.definitions,
            self.diagnostics,
            self.queried_modules,
            incremental,
        )
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct PersistedSession {
    format_version: u32,
    compiler_version: String,
    nodes: Vec<StoredNode>,
    edges: Vec<u32>,
    summaries: Vec<CachedSummary>,
    reports: Vec<CachedReportRef>,
}

impl PersistedSession {
    fn empty() -> Self {
        Self {
            format_version: CACHE_FORMAT_VERSION,
            compiler_version: compiler_cache_version(),
            nodes: Vec::new(),
            edges: Vec::new(),
            summaries: Vec::new(),
            reports: Vec::new(),
        }
    }

    fn compatible(&self) -> bool {
        self.format_version == CACHE_FORMAT_VERSION
            && self.compiler_version == compiler_cache_version()
    }

    fn cached_summary(&self, key: Fingerprint, result: Fingerprint) -> Option<CachedSummary> {
        self.summaries
            .iter()
            .find(|summary| summary.node_key == key && summary.result_fingerprint == result)
            .cloned()
    }

    fn latest_cached_summary(&self, key: Fingerprint) -> Option<CachedSummary> {
        self.summaries
            .iter()
            .find(|summary| summary.node_key == key)
            .cloned()
    }

    fn cached_report_ref(&self, key: Fingerprint, result: Fingerprint) -> Option<CachedReportRef> {
        self.reports
            .iter()
            .find(|report| report.node_key == key && report.result_fingerprint == result)
            .cloned()
    }
}

fn compiler_cache_version() -> String {
    format!(
        "{}+frontend-{FRONTEND_SEMANTIC_VERSION}+intrinsics-{REGISTRY_SEMANTIC_VERSION}",
        env!("CARGO_PKG_VERSION"),
    )
}

#[derive(Debug)]
struct QuerySession {
    previous: PersistedSession,
    previous_dir: Option<PathBuf>,
    previous_lookup: HashMap<(DepKind, Fingerprint), u32>,
    current: PersistedSession,
    current_reports: Vec<(String, CachedReport)>,
    current_lookup: HashMap<(DepKind, Fingerprint), u32>,
    executed: u64,
    green: u64,
    red: u64,
    result_cache_loads: u64,
    bytes_read: u64,
    fingerprint_nanos: u64,
    executed_by_kind: BTreeMap<String, u64>,
}

impl QuerySession {
    fn open(cache_dir: &Path) -> Self {
        let (previous, bytes_read, previous_dir) =
            load_previous(cache_dir).unwrap_or_else(|| (PersistedSession::empty(), 0, None));
        let previous_lookup = previous
            .nodes
            .iter()
            .enumerate()
            .map(|(index, node)| ((node.kind, node.key_fingerprint), index as u32))
            .collect();
        Self {
            previous,
            previous_dir,
            previous_lookup,
            current: PersistedSession::empty(),
            current_reports: Vec::new(),
            current_lookup: HashMap::new(),
            executed: 0,
            green: 0,
            red: 0,
            result_cache_loads: 0,
            bytes_read,
            fingerprint_nanos: 0,
            executed_by_kind: BTreeMap::new(),
        }
    }

    fn append(
        &mut self,
        kind: DepKind,
        key_fingerprint: Fingerprint,
        result_fingerprint: Fingerprint,
        dependencies: &[u32],
    ) -> u32 {
        let edge_start = self.current.edges.len() as u32;
        self.current.edges.extend_from_slice(dependencies);
        let index = self.current.nodes.len() as u32;
        self.current.nodes.push(StoredNode {
            kind,
            key_fingerprint,
            result_fingerprint,
            edge_start,
            edge_count: dependencies.len() as u32,
        });
        self.current_lookup.insert((kind, key_fingerprint), index);
        index
    }

    fn try_mark_green(
        &mut self,
        kind: DepKind,
        key: Fingerprint,
        dependencies: &[u32],
    ) -> Option<(u32, Fingerprint)> {
        let previous = self.previous_node(kind, key)?;
        if previous.edge_count as usize != dependencies.len() {
            return None;
        }
        let edge_start = previous.edge_start as usize;
        for (offset, current_dependency) in dependencies.iter().enumerate() {
            let previous_dependency_index = *self.previous.edges.get(edge_start + offset)?;
            let previous_dependency = self
                .previous
                .nodes
                .get(previous_dependency_index as usize)?;
            let current_dependency = self.current.nodes.get(*current_dependency as usize)?;
            if previous_dependency.kind != current_dependency.kind
                || previous_dependency.key_fingerprint != current_dependency.key_fingerprint
                || previous_dependency.result_fingerprint != current_dependency.result_fingerprint
            {
                return None;
            }
        }
        let result = previous.result_fingerprint;
        let index = self.append(kind, key, result, dependencies);
        self.green += 1;
        Some((index, result))
    }

    fn previous_node(&self, kind: DepKind, key: Fingerprint) -> Option<&StoredNode> {
        let index = *self.previous_lookup.get(&(kind, key))?;
        self.previous.nodes.get(index as usize)
    }

    fn stats(&self) -> IncrementalStats {
        let graph_bytes = serde_json::to_vec(&self.current)
            .map(|encoded| encoded.len() as u64)
            .unwrap_or(0);
        let report_bytes: u64 = self
            .current_reports
            .iter()
            .filter_map(|(_, report)| serde_json::to_vec(report).ok())
            .map(|encoded| encoded.len() as u64)
            .sum();
        IncrementalStats::from_snapshot(IncrementalStatsSnapshot {
            executed: self.executed,
            green: self.green,
            red: self.red,
            result_cache_loads: self.result_cache_loads,
            bytes_read: self.bytes_read,
            bytes_written: graph_bytes.saturating_add(report_bytes),
            fingerprint_nanos: self.fingerprint_nanos,
            executed_by_kind: self.executed_by_kind.clone(),
        })
    }

    fn stats_without_write(&self) -> IncrementalStats {
        IncrementalStats::from_snapshot(IncrementalStatsSnapshot {
            executed: self.executed,
            green: self.green,
            red: self.red,
            result_cache_loads: self.result_cache_loads,
            bytes_read: self.bytes_read,
            bytes_written: 0,
            fingerprint_nanos: self.fingerprint_nanos,
            executed_by_kind: self.executed_by_kind.clone(),
        })
    }

    fn execute(&mut self, kind: DepKind) {
        self.executed += 1;
        *self
            .executed_by_kind
            .entry(kind.as_str().to_owned())
            .or_default() += 1;
    }

    fn append_executed(
        &mut self,
        kind: DepKind,
        key: Fingerprint,
        result: Fingerprint,
        dependencies: &[u32],
    ) -> u32 {
        self.execute(kind);
        if let Some(previous) = self.previous_node(kind, key) {
            if previous.result_fingerprint == result {
                self.green += 1;
            } else {
                self.red += 1;
            }
        }
        self.append(kind, key, result, dependencies)
    }

    fn promote_report(&mut self, key: Fingerprint, result: Fingerprint, report: &TypedCheckReport) {
        let file_name = format!("report-{}-{}.json", key.hex(), result.hex());
        self.current
            .summaries
            .push(CachedSummary::from_report(key, result, report));
        self.current.reports.push(CachedReportRef {
            node_key: key,
            result_fingerprint: result,
            file_name: file_name.clone(),
        });
        self.current_reports
            .push((file_name, CachedReport::from_report(key, result, report)));
    }

    fn loaded_result_cache(&mut self) {
        self.result_cache_loads += 1;
    }

    fn cached_report(&mut self, key: Fingerprint, result: Fingerprint) -> Option<CachedReport> {
        let report = self.previous.cached_report_ref(key, result)?;
        let path = self.previous_dir.as_ref()?.join(report.file_name);
        let bytes = fs::read(path).ok()?;
        let cached = serde_json::from_slice(&bytes).ok()?;
        self.bytes_read = self.bytes_read.saturating_add(bytes.len() as u64);
        self.loaded_result_cache();
        Some(cached)
    }

    fn record_fingerprint_time(&mut self, started: Instant) {
        self.fingerprint_nanos = self
            .fingerprint_nanos
            .saturating_add(started.elapsed().as_nanos() as u64);
    }

    fn try_replay_green(&mut self, kind: DepKind, key: Fingerprint) -> Option<Fingerprint> {
        let root = *self.previous_lookup.get(&(kind, key))?;
        let mut mapped = HashMap::<u32, u32>::new();
        let mut stack = vec![(root, false)];
        while let Some((previous_index, exiting)) = stack.pop() {
            if mapped.contains_key(&previous_index) {
                continue;
            }
            let previous_node = self.previous.nodes.get(previous_index as usize)?;
            if let Some(current_index) = self
                .current_lookup
                .get(&(previous_node.kind, previous_node.key_fingerprint))
                .copied()
            {
                let current_node = self.current.nodes.get(current_index as usize)?;
                if current_node.result_fingerprint != previous_node.result_fingerprint {
                    return None;
                }
                mapped.insert(previous_index, current_index);
                continue;
            }
            let start = previous_node.edge_start as usize;
            let end = start + previous_node.edge_count as usize;
            let dependencies = self.previous.edges.get(start..end)?;
            if !exiting {
                stack.push((previous_index, true));
                for dependency in dependencies.iter().rev() {
                    if !mapped.contains_key(dependency) {
                        stack.push((*dependency, false));
                    }
                }
                continue;
            }
            let current_dependencies = dependencies
                .iter()
                .map(|dependency| mapped.get(dependency).copied())
                .collect::<Option<Vec<_>>>()?;
            let current_index = self.append(
                previous_node.kind,
                previous_node.key_fingerprint,
                previous_node.result_fingerprint,
                &current_dependencies,
            );
            self.green += 1;
            mapped.insert(previous_index, current_index);
        }
        self.previous
            .nodes
            .get(root as usize)
            .map(|node| node.result_fingerprint)
    }

    fn publish(self, cache_dir: &Path) -> Result<(), IncrementalCheckError> {
        publish_session(cache_dir, &self.current, &self.current_reports)
    }
}

fn semantic_query(
    session: &mut QuerySession,
    kind: DepKind,
    key: Fingerprint,
    result: Fingerprint,
    dependencies: &[u32],
    execute_missing: bool,
) -> Option<u32> {
    if let Some((node, _)) = session.try_mark_green(kind, key, dependencies) {
        return Some(node);
    }
    execute_missing.then(|| session.append_executed(kind, key, result, dependencies))
}

fn fingerprint_json(value: &impl Serialize) -> Fingerprint {
    let encoded = serde_json::to_vec(value).expect("stable query value must serialize");
    Fingerprint::of_bytes(&encoded)
}

fn stable_query_key(label: &str, identity: &impl Serialize) -> Fingerprint {
    fingerprint_json(&(label, identity))
}

fn semantic_graph(
    session: &mut QuerySession,
    report: &TypedCheckReport,
    parse_nodes: &HashMap<String, u32>,
    execute_missing: bool,
) -> Option<u32> {
    let mut index_nodes = HashMap::<String, u32>::new();
    for module in report.queried_modules() {
        let parse_node = *parse_nodes.get(module)?;
        let mut headers: Vec<_> = report
            .definitions()
            .iter()
            .filter(|definition| definition.module() == module)
            .map(|definition| (definition.qualified_name(), definition.signature()))
            .collect();
        headers.sort_by_key(|(name, _)| *name);
        let key = stable_query_key("index-module", module);
        let result = fingerprint_json(&headers);
        let node = semantic_query(
            session,
            DepKind::IndexModule,
            key,
            result,
            &[parse_node],
            execute_missing,
        )?;
        index_nodes.insert(module.clone(), node);
    }

    let mut role_nodes = Vec::with_capacity(report.definitions().len());
    for definition in report.definitions() {
        let identity = (definition.module(), definition.qualified_name());
        let header_key = stable_query_key("definition-header", &identity);
        let header_result = fingerprint_json(definition.signature());
        let header_node = semantic_query(
            session,
            DepKind::DefinitionHeader,
            header_key,
            header_result,
            &[*index_nodes.get(definition.module())?],
            execute_missing,
        )?;

        let hir_result = fingerprint_json(definition.hir());
        let revision_identity = (identity, hir_result);
        let lower_key = stable_query_key("lower-source-hir", &revision_identity);
        let lower_node = semantic_query(
            session,
            DepKind::LowerSourceHir,
            lower_key,
            hir_result,
            &[header_node],
            execute_missing,
        )?;

        let resolutions: Vec<_> = definition
            .hir()
            .facts()
            .iter()
            .map(|fact| {
                (
                    fact.resolved_node(),
                    fact.resolved_definition(),
                    fact.resolved_definitions(),
                )
            })
            .collect();
        let resolve_key = stable_query_key("resolve-definition", &revision_identity);
        let resolve_result = fingerprint_json(&resolutions);
        let resolve_node = semantic_query(
            session,
            DepKind::ResolveDefinition,
            resolve_key,
            resolve_result,
            &[lower_node],
            execute_missing,
        )?;

        let types: Vec<_> = definition
            .hir()
            .facts()
            .iter()
            .map(|fact| fact.source_type())
            .collect();
        let types_key = stable_query_key("infer-types", &revision_identity);
        let types_result = fingerprint_json(&(definition.signature(), types));
        let types_node = semantic_query(
            session,
            DepKind::InferTypes,
            types_key,
            types_result,
            &[resolve_node],
            execute_missing,
        )?;

        let availability: Vec<_> = definition
            .hir()
            .facts()
            .iter()
            .map(|fact| fact.availability())
            .collect();
        let availability_key = stable_query_key("infer-availability", &revision_identity);
        let availability_result = fingerprint_json(&availability);
        let availability_node = semantic_query(
            session,
            DepKind::InferAvailability,
            availability_key,
            availability_result,
            &[types_node],
            execute_missing,
        )?;

        let roles: Vec<_> = definition
            .hir()
            .facts()
            .iter()
            .map(|fact| fact.roles())
            .collect();
        let roles_key = stable_query_key("analyze-dependency-roles", &revision_identity);
        let roles_result = fingerprint_json(&roles);
        let roles_node = semantic_query(
            session,
            DepKind::AnalyzeDependencyRoles,
            roles_key,
            roles_result,
            &[availability_node],
            execute_missing,
        )?;
        role_nodes.push(roles_node);
    }

    let reachable_identity = report.entry();
    let reachable_key = stable_query_key("reachable-definitions", &reachable_identity);
    let reachable_result = fingerprint_json(
        &report
            .definitions()
            .iter()
            .map(|definition| (definition.module(), definition.qualified_name()))
            .collect::<Vec<_>>(),
    );
    let reachable_node = semantic_query(
        session,
        DepKind::ReachableDefinitions,
        reachable_key,
        reachable_result,
        &role_nodes,
        execute_missing,
    )?;
    let diagnostics_key = stable_query_key("collect-diagnostics", &reachable_identity);
    let diagnostics_result = fingerprint_json(&report.diagnostics());
    let mut diagnostic_dependencies = Vec::with_capacity(role_nodes.len() + 1);
    diagnostic_dependencies.push(reachable_node);
    diagnostic_dependencies.extend(role_nodes);
    semantic_query(
        session,
        DepKind::CollectDiagnostics,
        diagnostics_key,
        diagnostics_result,
        &diagnostic_dependencies,
        execute_missing,
    )
}

#[derive(Debug)]
pub enum IncrementalCheckError {
    Check(Box<TypedCheckError>),
    Cache(std::io::Error),
    Encode(serde_json::Error),
}

impl Display for IncrementalCheckError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Check(error) => Display::fmt(error, formatter),
            Self::Cache(error) => write!(formatter, "incremental cache I/O failed: {error}"),
            Self::Encode(error) => write!(formatter, "incremental cache encoding failed: {error}"),
        }
    }
}

impl Error for IncrementalCheckError {}

impl From<TypedCheckError> for IncrementalCheckError {
    fn from(error: TypedCheckError) -> Self {
        Self::Check(Box::new(error))
    }
}

impl From<std::io::Error> for IncrementalCheckError {
    fn from(error: std::io::Error) -> Self {
        Self::Cache(error)
    }
}

impl From<serde_json::Error> for IncrementalCheckError {
    fn from(error: serde_json::Error) -> Self {
        Self::Encode(error)
    }
}

pub fn check_typed_entry_incremental(
    file_name: &str,
    source: &str,
    requested_entry: &str,
    cache_dir: &Path,
) -> Result<TypedCheckReport, IncrementalCheckError> {
    match check_typed_entry_incremental_impl(
        file_name,
        source,
        requested_entry,
        cache_dir,
        RequestedCheck::Report,
    )? {
        IncrementalCheckResult::Report(report) => Ok(report),
        IncrementalCheckResult::Summary(_) => unreachable!("report mode returns a report"),
    }
}

pub fn check_typed_entry_summary_incremental(
    file_name: &str,
    source: &str,
    requested_entry: &str,
    cache_dir: &Path,
) -> Result<TypedCheckSummary, IncrementalCheckError> {
    match check_typed_entry_incremental_impl(
        file_name,
        source,
        requested_entry,
        cache_dir,
        RequestedCheck::Summary,
    )? {
        IncrementalCheckResult::Summary(summary) => Ok(summary),
        IncrementalCheckResult::Report(_) => unreachable!("summary mode returns a summary"),
    }
}

#[derive(Clone, Copy)]
enum RequestedCheck {
    Summary,
    Report,
}

enum IncrementalCheckResult {
    Summary(TypedCheckSummary),
    Report(TypedCheckReport),
}

fn check_typed_entry_incremental_impl(
    file_name: &str,
    source: &str,
    requested_entry: &str,
    cache_dir: &Path,
    requested: RequestedCheck,
) -> Result<IncrementalCheckResult, IncrementalCheckError> {
    let mut session = QuerySession::open(cache_dir);
    let source_key = Fingerprint::of_parts(&["source", file_name]);
    let source_result = Fingerprint::of_bytes(source.as_bytes());
    let source_node = session.append(DepKind::SourceText, source_key, source_result, &[]);

    let parse_key = Fingerprint::of_parts(&["parse", file_name]);
    let parse = session.try_mark_green(DepKind::ParseModule, parse_key, &[source_node]);
    let (parse_node, _parse_result) = match parse {
        Some(reused) => reused,
        None => {
            let started = Instant::now();
            let result = semantic_parse_fingerprint(file_name, source)?;
            session.record_fingerprint_time(started);
            let node =
                session.append_executed(DepKind::ParseModule, parse_key, result, &[source_node]);
            (node, result)
        }
    };
    let parse_nodes = HashMap::from([(file_name.to_owned(), parse_node)]);

    let check_key = Fingerprint::of_parts(&["check", file_name, requested_entry]);
    if let Some(result) = session.try_replay_green(DepKind::CheckEntry, check_key) {
        match requested {
            RequestedCheck::Summary => {
                if let Some(cached) = session.previous.cached_summary(check_key, result) {
                    session.loaded_result_cache();
                    let summary = cached.into_summary(session.stats_without_write());
                    return Ok(IncrementalCheckResult::Summary(summary));
                }
            }
            RequestedCheck::Report => {
                if let Some(cached) = session.cached_report(check_key, result) {
                    let report = cached.into_report(session.stats_without_write());
                    return Ok(IncrementalCheckResult::Report(report));
                }
            }
        }
    }

    let report = check_typed_entry(file_name, source, requested_entry)?;
    let cached_bytes =
        serde_json::to_vec(&(report.entry(), report.definitions(), report.diagnostics()))?;
    let result = Fingerprint::of_bytes(&cached_bytes);
    let collect_node = semantic_graph(&mut session, &report, &parse_nodes, true)
        .expect("executing semantic queries always produces a diagnostics node");
    session.append_executed(DepKind::CheckEntry, check_key, result, &[collect_node]);
    session.promote_report(check_key, result, &report);
    let stats = session.stats();
    let output = match requested {
        RequestedCheck::Summary => {
            IncrementalCheckResult::Summary(report.summary().with_incremental(stats))
        }
        RequestedCheck::Report => IncrementalCheckResult::Report(report.with_incremental(stats)),
    };
    session.publish(cache_dir)?;
    Ok(output)
}

pub fn check_typed_bundle_entry_incremental(
    entry_module: &str,
    modules: &BTreeMap<String, String>,
    requested_entry: &str,
    cache_dir: &Path,
) -> Result<TypedCheckReport, IncrementalCheckError> {
    let mut loader = |module: &str| Ok(modules.get(module).cloned());
    check_typed_bundle_entry_incremental_with_loader(
        entry_module,
        requested_entry,
        cache_dir,
        &mut loader,
    )
}

pub fn check_typed_bundle_entry_summary_incremental(
    entry_module: &str,
    modules: &BTreeMap<String, String>,
    requested_entry: &str,
    cache_dir: &Path,
) -> Result<TypedCheckSummary, IncrementalCheckError> {
    let mut loader = |module: &str| Ok(modules.get(module).cloned());
    check_typed_bundle_entry_summary_incremental_with_loader(
        entry_module,
        requested_entry,
        cache_dir,
        &mut loader,
    )
}

pub fn check_typed_bundle_entry_incremental_with_loader<F>(
    entry_module: &str,
    requested_entry: &str,
    cache_dir: &Path,
    loader: &mut F,
) -> Result<TypedCheckReport, IncrementalCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    match check_typed_bundle_entry_incremental_impl(
        entry_module,
        requested_entry,
        cache_dir,
        loader,
        RequestedCheck::Report,
    )? {
        IncrementalCheckResult::Report(report) => Ok(report),
        IncrementalCheckResult::Summary(_) => unreachable!("report mode returns a report"),
    }
}

pub fn check_typed_bundle_entry_summary_incremental_with_loader<F>(
    entry_module: &str,
    requested_entry: &str,
    cache_dir: &Path,
    loader: &mut F,
) -> Result<TypedCheckSummary, IncrementalCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    match check_typed_bundle_entry_incremental_impl(
        entry_module,
        requested_entry,
        cache_dir,
        loader,
        RequestedCheck::Summary,
    )? {
        IncrementalCheckResult::Summary(summary) => Ok(summary),
        IncrementalCheckResult::Report(_) => unreachable!("summary mode returns a summary"),
    }
}

fn check_typed_bundle_entry_incremental_impl<F>(
    entry_module: &str,
    requested_entry: &str,
    cache_dir: &Path,
    loader: &mut F,
    requested: RequestedCheck,
) -> Result<IncrementalCheckResult, IncrementalCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let mut session = QuerySession::open(cache_dir);
    let check_key = Fingerprint::of_parts(&["check-bundle", entry_module, requested_entry]);
    let previous_summary = session.previous.latest_cached_summary(check_key);
    let mut parse_nodes = HashMap::<String, u32>::new();
    let mut sources = HashMap::<String, String>::new();

    if let Some(previous_summary) = &previous_summary {
        let mut previous_modules = previous_summary.queried_modules.clone();
        previous_modules.sort();
        query_bundle_modules(
            &mut session,
            &previous_modules,
            &mut parse_nodes,
            &mut sources,
            loader,
        )?;
        if let Some(result) = session.try_replay_green(DepKind::CheckEntry, check_key) {
            match requested {
                RequestedCheck::Summary => {
                    if let Some(cached) = session.previous.cached_summary(check_key, result) {
                        session.loaded_result_cache();
                        let summary = cached.into_summary(session.stats_without_write());
                        return Ok(IncrementalCheckResult::Summary(summary));
                    }
                }
                RequestedCheck::Report => {
                    if let Some(cached) = session.cached_report(check_key, result) {
                        let report = cached.into_report(session.stats_without_write());
                        return Ok(IncrementalCheckResult::Report(report));
                    }
                }
            }
        }
    }

    let report = check_typed_bundle_entry_with_loader(entry_module, requested_entry, loader)?;
    let mut queried_modules = report.queried_modules().to_vec();
    queried_modules.sort();
    query_bundle_modules(
        &mut session,
        &queried_modules,
        &mut parse_nodes,
        &mut sources,
        loader,
    )?;
    let cached_bytes = serde_json::to_vec(&(
        report.entry(),
        report.definitions(),
        report.diagnostics(),
        report.queried_modules(),
    ))?;
    let result = Fingerprint::of_bytes(&cached_bytes);
    let collect_node = semantic_graph(&mut session, &report, &parse_nodes, true)
        .expect("executing semantic queries always produces a diagnostics node");
    session.append_executed(DepKind::CheckEntry, check_key, result, &[collect_node]);
    session.promote_report(check_key, result, &report);
    let stats = session.stats();
    let output = match requested {
        RequestedCheck::Summary => {
            IncrementalCheckResult::Summary(report.summary().with_incremental(stats))
        }
        RequestedCheck::Report => IncrementalCheckResult::Report(report.with_incremental(stats)),
    };
    session.publish(cache_dir)?;
    Ok(output)
}

fn query_bundle_modules<F>(
    session: &mut QuerySession,
    module_names: &[String],
    parse_nodes: &mut HashMap<String, u32>,
    sources: &mut HashMap<String, String>,
    loader: &mut F,
) -> Result<Vec<u32>, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let mut dependencies = Vec::with_capacity(module_names.len());
    for module_name in module_names {
        if let Some(node) = parse_nodes.get(module_name) {
            dependencies.push(*node);
            continue;
        }
        let source_key = Fingerprint::of_parts(&["bundle-source", module_name]);
        if !sources.contains_key(module_name) {
            let source = loader(module_name).map_err(|message| TypedCheckError::SourceLoad {
                module: module_name.clone(),
                message,
            })?;
            if let Some(source) = source {
                sources.insert(module_name.clone(), source);
            }
        }
        let source = sources.get(module_name);
        let source_result = source.map_or_else(
            || Fingerprint::of_parts(&["missing-source", module_name]),
            |source| Fingerprint::of_bytes(source.as_bytes()),
        );
        let source_node = session.append(DepKind::SourceText, source_key, source_result, &[]);
        let parse_key = Fingerprint::of_parts(&["bundle-parse", module_name]);
        let parse_node =
            match session.try_mark_green(DepKind::ParseModule, parse_key, &[source_node]) {
                Some((node, _)) => node,
                None => {
                    let started = Instant::now();
                    let result = match source {
                        Some(source) => semantic_parse_fingerprint(module_name, source)?,
                        None => Fingerprint::of_parts(&["missing-module", module_name]),
                    };
                    session.record_fingerprint_time(started);
                    session.append_executed(DepKind::ParseModule, parse_key, result, &[source_node])
                }
            };
        parse_nodes.insert(module_name.clone(), parse_node);
        dependencies.push(parse_node);
    }
    Ok(dependencies)
}

fn semantic_parse_fingerprint(
    file_name: &str,
    source: &str,
) -> Result<Fingerprint, TypedCheckError> {
    let mut hasher = Sha3_256::new();
    let file = nac3ast::FileName::from(file_name.to_owned());
    for token in nac3parser::lexer::make_tokenizer(source, file) {
        let (_, token, _) = token.map_err(|error| TypedCheckError::Parse {
            file_name: file_name.to_owned(),
            message: format!("{} at {}", error.error, error.location),
        })?;
        let token = format!("{token:?}");
        hasher.update((token.len() as u64).to_le_bytes());
        hasher.update(token.as_bytes());
    }
    let digest = hasher.finalize();
    let mut fingerprint = [0; 16];
    fingerprint.copy_from_slice(&digest[..16]);
    Ok(Fingerprint(fingerprint))
}

fn load_previous(cache_dir: &Path) -> Option<(PersistedSession, u64, Option<PathBuf>)> {
    let current = fs::read_to_string(cache_dir.join(CURRENT_FILE)).ok()?;
    let session_dir = cache_dir.join(current.trim());
    let bytes = fs::read(session_dir.join(DEP_GRAPH_FILE)).ok()?;
    let session: PersistedSession = serde_json::from_slice(&bytes).ok()?;
    session
        .compatible()
        .then_some((session, bytes.len() as u64, Some(session_dir)))
}

fn publish_session(
    cache_dir: &Path,
    session: &PersistedSession,
    reports: &[(String, CachedReport)],
) -> Result<(), IncrementalCheckError> {
    fs::create_dir_all(cache_dir)?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let private_name = format!("in-progress-{}-{nonce}", std::process::id());
    let private_dir = cache_dir.join(&private_name);
    fs::create_dir(&private_dir)?;
    let encoded = serde_json::to_vec(session)?;
    if let Err(error) = fs::write(private_dir.join(DEP_GRAPH_FILE), encoded) {
        let _ = fs::remove_dir_all(&private_dir);
        return Err(error.into());
    }
    for (file_name, report) in reports {
        let encoded = serde_json::to_vec(report)?;
        if let Err(error) = fs::write(private_dir.join(file_name), encoded) {
            let _ = fs::remove_dir_all(&private_dir);
            return Err(error.into());
        }
    }
    let final_name = format!("session-{}-{nonce}", std::process::id());
    let final_dir = cache_dir.join(&final_name);
    fs::rename(&private_dir, &final_dir)?;

    let current_temp = current_temp_path(cache_dir);
    fs::write(&current_temp, &final_name)?;
    fs::rename(current_temp, cache_dir.join(CURRENT_FILE))?;
    Ok(())
}

fn current_temp_path(cache_dir: &Path) -> PathBuf {
    cache_dir.join(format!("CURRENT.{}.tmp", std::process::id()))
}
