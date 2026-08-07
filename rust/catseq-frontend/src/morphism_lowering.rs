//! Direct Typed Source HIR to target-resolved native arena lowering.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::morphism_arena::{
    BoundaryPolicy, MorphismArenaBuilder, MorphismNodeId, MorphismTemplateId, NativeProvenance,
    ProvenanceId, WaitSemantics,
};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{
    RwgWaveformDerivation, ValueExprArenaBuilder, ValueExprId, ValueExprPayload, ValueExprType,
};

use crate::intrinsics::{self, NativeMorphismTemplate};
use crate::native_records::{self, NativeRecordFieldType};
use crate::{
    BooleanOperation, ComparisonOperation, MorphismComposition, SourceHirKind, SourceHirNode,
    SourceLiteral, SourceType, TypedCheckReport, TypedDefinition, TypedSourceHir,
    ValueAvailability,
};

mod normalized_value;
mod value_lowering;

use normalized_value::{
    lower_normalized_default, normalized_board_id, normalized_has_duration_unit, normalized_to_json,
};
use value_lowering::{
    call_arguments, compare_lowered_values, is_numeric_intrinsic, lower_aggregate_intrinsic,
    lower_aggregate_operation, lower_compile_compare, lower_compile_value, lower_cycles_intrinsic,
    lower_duration_unit, lower_literal, lower_numeric_intrinsic, lower_static_subscript,
    lower_value_operation, lowered_to_json, scalar_to_expr, source_type_to_value_type,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MorphismLoweringError(String);

impl MorphismLoweringError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for MorphismLoweringError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for MorphismLoweringError {}

#[derive(Clone, PartialEq)]
enum LoweredValue {
    Null,
    Instance(String),
    Morphism(MorphismNodeId),
    Template(TemplatePlanId),
    ChannelBindings(Vec<ChannelBinding>),
    Aggregate(Vec<LoweredValue>),
    Json(serde_json::Value),
    Scalar(ScalarValue),
}

#[derive(Clone, PartialEq)]
enum ScalarValue {
    Bool(bool),
    Int(i64),
    Float(ExactDecimal),
    DurationCycles(ExactDecimal),
    String(String),
    Expr(ValueExprId),
}

#[derive(Clone, PartialEq)]
struct ChannelBinding {
    channel: String,
    template: TemplatePlanId,
}

#[derive(Clone, PartialEq)]
struct SpecializationArgument {
    target: SpecializationArgumentTarget,
    value: LoweredValue,
}

#[derive(Clone, PartialEq)]
enum SpecializationArgumentTarget {
    Position(usize),
    Keyword(String),
}

struct DefinitionSpecialization {
    value: Option<LoweredValue>,
    selected_source_for_error: Option<MorphismLoweringError>,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum SpecializationMode {
    Native,
    SelectedPathProbe,
}

struct BoundCallSpecialization {
    definition: Option<String>,
    arguments: Vec<SpecializationArgument>,
    selected_source_for_error: Option<MorphismLoweringError>,
}

struct SelectedPathState {
    call_errors: Vec<Option<MorphismLoweringError>>,
    bound_calls: Vec<Vec<BoundCallSpecialization>>,
    cache: Vec<Option<SelectedPathScan>>,
    truthiness_cache: Vec<Option<CachedTruthiness>>,
}

#[derive(Clone, Copy)]
enum CachedTruthiness {
    Known(bool),
    Unknown,
}

impl SelectedPathState {
    fn new(node_count: usize) -> Self {
        Self {
            call_errors: vec![None; node_count],
            bound_calls: (0..node_count).map(|_| Vec::new()).collect(),
            cache: vec![None; node_count],
            truthiness_cache: vec![None; node_count],
        }
    }

    fn invalidate(&mut self, node_id: usize) {
        self.cache[node_id] = None;
        self.truthiness_cache[node_id] = None;
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct TemplatePlanId(usize);

struct TemplatePlan {
    kind: TemplatePlanKind,
    provenance: ProvenanceId,
}

enum TemplatePlanKind {
    Operation {
        operation: String,
        arguments: Vec<ValueExprId>,
    },
    DefinitionRef {
        definition: String,
        arguments: Vec<ValueExprId>,
    },
    Wait {
        duration: ValueExprId,
        semantics: WaitSemantics,
    },
    Serial {
        children: Vec<TemplatePlanId>,
        boundaries: Vec<BoundaryPolicy>,
    },
    Parallel(Vec<TemplatePlanId>),
}

/// Lower the checked entry definition to the first durable CatSeq program
/// representation. Resolved source definitions remain shared
/// `DefinitionRef` leaves; no Source HIR owner is retained by the result.
pub fn lower_typed_report_to_native_arenas(
    report: &TypedCheckReport,
    clock_hz: u64,
) -> Result<NativeArenas, MorphismLoweringError> {
    let definition = report
        .definitions()
        .iter()
        .find(|definition| definition.qualified_name() == report.entry())
        .ok_or_else(|| {
            MorphismLoweringError::new(format!(
                "entry definition {} is absent from the typed report",
                report.entry()
            ))
        })?;
    let definitions = report
        .definitions()
        .iter()
        .map(|definition| definition.qualified_name())
        .collect();
    lower_entry(definition, &definitions, clock_hz)
}

/// Specialize every reachable source definition into one Python-free native
/// arena. This is the production lowering used by RTMQ compilation; unlike
/// [`lower_typed_report_to_native_arenas`], it never deliberately preserves a
/// source `DefinitionRef` boundary.
pub fn specialize_typed_report_to_native_arenas(
    report: &TypedCheckReport,
    clock_hz: u64,
) -> Result<NativeArenas, MorphismLoweringError> {
    specialize_typed_report_to_native_arenas_with_entry_arguments(
        report,
        clock_hz,
        &BTreeMap::new(),
    )
}

/// Specialize a checked source graph while binding explicitly supplied root
/// scalar parameters before Morphism structure is selected.
pub fn specialize_typed_report_to_native_arenas_with_entry_arguments(
    report: &TypedCheckReport,
    clock_hz: u64,
    entry_arguments: &BTreeMap<String, serde_json::Value>,
) -> Result<NativeArenas, MorphismLoweringError> {
    let definitions = report
        .definitions()
        .iter()
        .map(|definition| (definition.qualified_name(), definition))
        .collect::<HashMap<_, _>>();
    let entry = definitions.get(report.entry()).copied().ok_or_else(|| {
        MorphismLoweringError::new(format!(
            "entry definition {} is absent from the typed report",
            report.entry()
        ))
    })?;
    let mut lowerer = SpecializationLowerer::new(definitions, clock_hz);
    let parameters = entry
        .signature()
        .parameters()
        .iter()
        .filter(|parameter| !matches!(parameter.source_type(), SourceType::Instance(_)))
        .collect::<Vec<_>>();
    if let Some(name) = entry_arguments.keys().find(|name| {
        !parameters
            .iter()
            .any(|parameter| parameter.name() == name.as_str())
    }) {
        return Err(MorphismLoweringError::new(format!(
            "unknown entry argument {name:?} for {}",
            entry.qualified_name()
        )));
    }
    let arguments = parameters
        .into_iter()
        .filter_map(|parameter| {
            entry_arguments
                .get(parameter.name())
                .map(|value| (parameter, value))
        })
        .map(|(parameter, value)| {
            Ok(SpecializationArgument {
                target: SpecializationArgumentTarget::Keyword(parameter.name().to_owned()),
                value: lower_entry_argument(
                    entry.qualified_name(),
                    parameter.name(),
                    parameter.source_type(),
                    value,
                    clock_hz,
                )?,
            })
        })
        .collect::<Result<Vec<_>, MorphismLoweringError>>()?;
    let DefinitionSpecialization {
        value,
        selected_source_for_error,
    } = lowerer.lower_definition(entry, &arguments, default_instance_identity(entry))?;
    if let Some(error) = selected_source_for_error {
        return Err(error);
    }
    let root = match value {
        Some(LoweredValue::Morphism(root)) => root,
        _ => {
            return Err(MorphismLoweringError::new(format!(
                "{} does not specialize to a Morphism",
                entry.qualified_name()
            )));
        }
    };
    let morphisms = lowerer
        .builder
        .finish(root)
        .map_err(|error| MorphismLoweringError::new(error.to_string()))?;
    let values = lowerer
        .value_builder
        .finish()
        .map_err(|error| MorphismLoweringError::new(error.to_string()))?;
    NativeArenas::new(morphisms, values)
        .map_err(|error| MorphismLoweringError::new(error.to_string()))
}

fn lower_entry_argument(
    entry: &str,
    parameter: &str,
    source_type: &SourceType,
    value: &serde_json::Value,
    clock_hz: u64,
) -> Result<LoweredValue, MorphismLoweringError> {
    let mismatch = || {
        MorphismLoweringError::new(format!(
            "entry argument {entry}.{parameter} must be {source_type}, got {value}"
        ))
    };
    match source_type {
        SourceType::Optional(_) if value.is_null() => Ok(LoweredValue::Null),
        SourceType::Optional(inner) => {
            lower_entry_argument(entry, parameter, inner, value, clock_hz)
        }
        SourceType::Bool => value
            .as_bool()
            .map(|value| LoweredValue::Scalar(ScalarValue::Bool(value)))
            .ok_or_else(mismatch),
        SourceType::Int64 => json_i64(value)
            .map(|value| LoweredValue::Scalar(ScalarValue::Int(value)))
            .ok_or_else(mismatch),
        SourceType::Float64 => json_decimal(value)
            .map(|value| LoweredValue::Scalar(ScalarValue::Float(value)))
            .ok_or_else(mismatch),
        SourceType::Duration => json_decimal(value)
            .and_then(|value| value.checked_mul(ExactDecimal::from_u64(clock_hz)))
            .map(|value| LoweredValue::Scalar(ScalarValue::DurationCycles(value)))
            .ok_or_else(mismatch),
        SourceType::String => value
            .as_str()
            .map(|value| LoweredValue::Scalar(ScalarValue::String(value.to_owned())))
            .ok_or_else(mismatch),
        _ => Err(mismatch()),
    }
}

fn json_i64(value: &serde_json::Value) -> Option<i64> {
    value
        .as_i64()
        .or_else(|| value.as_u64().and_then(|value| i64::try_from(value).ok()))
}

fn json_decimal(value: &serde_json::Value) -> Option<ExactDecimal> {
    if let Some(value) = value.as_i64() {
        return Some(ExactDecimal::from_i64(value));
    }
    if let Some(value) = value.as_u64() {
        return Some(ExactDecimal::from_u64(value));
    }
    value.as_f64().and_then(ExactDecimal::from_f64_shortest)
}

struct SpecializationLowerer<'a> {
    definitions: HashMap<&'a str, &'a TypedDefinition>,
    clock_hz: u64,
    builder: MorphismArenaBuilder,
    value_builder: ValueExprArenaBuilder,
    template_plans: Vec<TemplatePlan>,
    published_templates: Vec<Option<MorphismTemplateId>>,
    active_definitions: Vec<&'a str>,
    compile_fields: HashMap<String, String>,
    mode: SpecializationMode,
}

impl<'a> SpecializationLowerer<'a> {
    fn new(definitions: HashMap<&'a str, &'a TypedDefinition>, clock_hz: u64) -> Self {
        Self::with_mode(definitions, clock_hz, SpecializationMode::Native)
    }

    fn with_mode(
        definitions: HashMap<&'a str, &'a TypedDefinition>,
        clock_hz: u64,
        mode: SpecializationMode,
    ) -> Self {
        let mut compile_fields = HashMap::new();
        for definition in definitions.values() {
            for (node, fact) in definition
                .hir()
                .nodes()
                .iter()
                .zip(definition.hir().facts())
            {
                if node.kind() == &SourceHirKind::Attribute
                    && let (Some(symbol), Some(value)) = (node.symbol(), fact.compile_value())
                    && let Some(field) = symbol.strip_prefix("self.")
                {
                    compile_fields
                        .entry(field.to_owned())
                        .or_insert_with(|| value.to_owned());
                }
            }
        }
        Self {
            definitions,
            clock_hz,
            builder: MorphismArenaBuilder::new(),
            value_builder: ValueExprArenaBuilder::new(),
            template_plans: Vec::new(),
            published_templates: Vec::new(),
            active_definitions: Vec::new(),
            compile_fields,
            mode,
        }
    }

    fn lower_definition(
        &mut self,
        definition: &'a TypedDefinition,
        arguments: &[SpecializationArgument],
        instance_identity: String,
    ) -> Result<DefinitionSpecialization, MorphismLoweringError> {
        if self
            .active_definitions
            .contains(&definition.qualified_name())
        {
            return Err(MorphismLoweringError::new(format!(
                "recursive Morphism specialization is unsupported: {} -> {}",
                self.active_definitions.join(" -> "),
                definition.qualified_name()
            )));
        }
        self.active_definitions.push(definition.qualified_name());
        let result = self.lower_definition_body(definition, arguments, &instance_identity);
        self.active_definitions.pop();
        result
    }

    fn lower_definition_body(
        &mut self,
        definition: &'a TypedDefinition,
        arguments: &[SpecializationArgument],
        instance_identity: &str,
    ) -> Result<DefinitionSpecialization, MorphismLoweringError> {
        let hir = definition.hir();
        let mut provenance = Vec::with_capacity(hir.nodes().len());
        for node in hir.nodes() {
            provenance.push(self.builder.intern_provenance(NativeProvenance::new(
                definition.qualified_name(),
                node.anchor().line() as u32,
                node.anchor().column() as u32,
            )));
        }
        let mut parameter_bindings = HashMap::new();
        let parameters = definition
            .signature()
            .parameters()
            .iter()
            .filter(|parameter| !matches!(parameter.source_type(), SourceType::Instance(_)))
            .collect::<Vec<_>>();
        for (index, parameter) in parameters.into_iter().enumerate() {
            let value = arguments
                .iter()
                .find(|argument| argument.target == SpecializationArgumentTarget::Position(index))
                .map(|argument| argument.value.clone())
                .or_else(|| {
                    arguments
                        .iter()
                        .find(|argument| {
                            argument.target
                                == SpecializationArgumentTarget::Keyword(
                                    parameter.name().to_owned(),
                                )
                        })
                        .map(|argument| argument.value.clone())
                })
                .or_else(|| {
                    parameter
                        .default_value()
                        .and_then(|value| lower_normalized_default(value, self.clock_hz))
                });
            if let Some(value) = value {
                parameter_bindings.insert(parameter.name(), value);
            }
        }
        let definition_names = self.definitions.keys().copied().collect::<HashSet<_>>();
        let special_form_dictionaries = special_form_dictionaries(hir);
        let mut values = vec![None::<LoweredValue>; hir.nodes().len()];
        // Scanners are short-lived so lowering can keep mutating `values`, but
        // their empty-binding results are shared. Each node is invalidated once
        // after lowering fills its value or call error, keeping the traversal
        // linear in the Source HIR rather than rescanning every descendant for
        // every node.
        let mut selected_paths = SelectedPathState::new(hir.nodes().len());
        let source_for_descendants = source_for_descendants(hir);
        let nested_statements = nested_control_statements(hir);
        let mut local_bindings = HashMap::<String, LoweredValue>::new();
        for node_id in 0..hir.nodes().len() {
            if source_for_descendants.contains(&(node_id as u32)) {
                continue;
            }
            let node = &hir.nodes()[node_id];
            if node.kind() == &SourceHirKind::Name
                && let Some(value) = node
                    .symbol()
                    .and_then(|name| local_bindings.get(name))
                    .cloned()
            {
                values[node_id] = Some(value);
                continue;
            }
            if node.kind() == &SourceHirKind::Name
                && let Some(value) = node
                    .symbol()
                    .and_then(|name| parameter_bindings.get(name))
                    .filter(|value| !matches!(value, LoweredValue::Null))
                    .cloned()
            {
                values[node_id] = Some(value);
                continue;
            }
            if let Some(resolved) = hir.facts()[node_id].resolved_node() {
                values[node_id] = values[resolved as usize].clone();
                continue;
            }
            if node.kind() == &SourceHirKind::Name
                && let Some(value) = node
                    .symbol()
                    .and_then(|name| parameter_bindings.get(name))
                    .cloned()
            {
                values[node_id] = Some(value);
                continue;
            }
            let children = node_children(node, hir);
            let fact = &hir.facts()[node_id];
            let source_type = fact.source_type();
            if matches!(
                self.scan_selected_path(
                    hir,
                    &values,
                    &mut selected_paths,
                    Some(node_id as u32),
                    instance_identity,
                )?,
                SelectedPathScan::SourceForError(_)
            ) {
                continue;
            }
            let lowered = match node.kind() {
                SourceHirKind::Constant => lower_literal(node),
                SourceHirKind::Name
                    if source_type == Some(&SourceType::Duration)
                        && fact
                            .resolved_definition()
                            .is_some_and(intrinsics::is_duration_unit) =>
                {
                    Ok(lower_duration_unit(
                        fact.resolved_definition().expect("checked above"),
                        self.clock_hz,
                    ))
                }
                SourceHirKind::Attribute
                    if source_type == Some(&SourceType::Duration)
                        && fact
                            .resolved_definition()
                            .is_some_and(intrinsics::is_duration_unit) =>
                {
                    Ok(lower_duration_unit(
                        fact.resolved_definition().expect("checked above"),
                        self.clock_hz,
                    ))
                }
                SourceHirKind::Name
                    if fact.compile_value().is_some()
                        && (source_type_to_value_type(source_type).is_some()
                            || normalized_has_duration_unit(
                                fact.compile_value().expect("checked above"),
                            )) =>
                {
                    lower_compile_value(
                        node,
                        fact.compile_value().expect("checked above"),
                        source_type,
                        self.clock_hz,
                    )
                }
                SourceHirKind::Name
                    if matches!(source_type, Some(SourceType::NativeRecord(_)))
                        && fact.compile_value().is_some() =>
                {
                    normalized_to_json(
                        fact.compile_value().expect("checked above"),
                        &HashMap::new(),
                    )
                    .map(|value| Some(LoweredValue::Json(value)))
                }
                SourceHirKind::Attribute if fact.availability() == ValueAvailability::Link => {
                    source_type_to_value_type(source_type)
                        .map(|value_type| {
                            Some(LoweredValue::Scalar(ScalarValue::Expr(
                                self.value_builder.environment_slot(
                                    environment_slot_name(node, instance_identity),
                                    value_type,
                                ),
                            )))
                        })
                        .ok_or_else(|| {
                            lowering_error(node, "environment value has no native scalar type")
                        })
                }
                SourceHirKind::Attribute
                    if fact.compile_value().is_some()
                        && (source_type_to_value_type(source_type).is_some()
                            || normalized_has_duration_unit(
                                fact.compile_value().expect("checked above"),
                            )) =>
                {
                    lower_compile_value(
                        node,
                        fact.compile_value().expect("checked above"),
                        source_type,
                        self.clock_hz,
                    )
                }
                SourceHirKind::Attribute
                    if matches!(source_type, Some(SourceType::NativeRecord(_)))
                        && fact.compile_value().is_some() =>
                {
                    normalized_to_json(
                        fact.compile_value().expect("checked above"),
                        &self.compile_fields,
                    )
                    .map(|value| Some(LoweredValue::Json(value)))
                }
                SourceHirKind::Attribute if node.symbol() == Some("np.pi") => {
                    Ok(Some(LoweredValue::Scalar(ScalarValue::Float(
                        ExactDecimal::from_f64_shortest(std::f64::consts::PI)
                            .expect("PI is finite"),
                    ))))
                }
                SourceHirKind::Subscript if fact.availability() == ValueAvailability::Link => {
                    let slot = children
                        .get(1)
                        .and_then(|child| hir.nodes()[*child as usize].symbol())
                        .unwrap_or("scan_value");
                    source_type_to_value_type(source_type)
                        .map(|value_type| {
                            Some(LoweredValue::Scalar(ScalarValue::Expr(
                                self.value_builder.runtime_slot(slot, value_type),
                            )))
                        })
                        .ok_or_else(|| {
                            lowering_error(node, "link-time value has no native scalar type")
                        })
                }
                SourceHirKind::Binary | SourceHirKind::Unary
                    if node.value_operation().is_some() =>
                {
                    let aggregate = lower_aggregate_operation(node, children, &values);
                    lower_value_operation(
                        node,
                        children,
                        &values,
                        source_type,
                        &mut self.value_builder,
                    )
                    .map(|value| aggregate.or(value))
                }
                SourceHirKind::Call
                    if fact
                        .resolved_definitions()
                        .iter()
                        .any(|resolved| self.definitions.contains_key(resolved.as_str())) =>
                {
                    match collect_specialization_arguments(node, children, |child| {
                        Ok(values[child as usize].clone())
                    }) {
                        Ok(arguments) => self
                            .lower_resolved_call(node_id as u32, hir, &arguments, instance_identity)
                            .map(|specialization| {
                                selected_paths.call_errors[node_id] =
                                    specialization.selected_source_for_error;
                                specialization.value
                            }),
                        Err(error) => Err(error),
                    }
                }
                SourceHirKind::Call
                    if self.mode == SpecializationMode::SelectedPathProbe
                        && matches!(
                            source_type,
                            Some(SourceType::Morphism | SourceType::MorphismTemplate)
                        ) =>
                {
                    Ok(None)
                }
                SourceHirKind::Call if fact.resolved_definition() == Some("functools.reduce") => {
                    let aggregate = children.iter().skip(1).find_map(|child| {
                        match values[*child as usize].clone() {
                            Some(LoweredValue::Aggregate(values)) => Some(values),
                            _ => None,
                        }
                    });
                    aggregate
                        .map(|values| {
                            self.materialize_aggregate(values, provenance[node_id])
                                .map(LoweredValue::Morphism)
                        })
                        .transpose()
                }
                SourceHirKind::Call
                    if fact.resolved_definition() == Some("catseq.time_utils.cycles") =>
                {
                    lower_cycles_intrinsic(node, children, &values, &mut self.value_builder)
                }
                SourceHirKind::Call
                    if fact.resolved_definition().is_some_and(is_repeat_morphism) =>
                {
                    lower_repeat_call(
                        node,
                        children,
                        &values,
                        &mut self.builder,
                        &mut self.value_builder,
                        provenance[node_id],
                    )
                }
                SourceHirKind::Call if matches!(source_type, Some(SourceType::NativeRecord(_))) => {
                    lower_native_record_call(node, children, fact, &values, &self.value_builder)
                }
                SourceHirKind::Call if source_type == Some(&SourceType::FixedAggregate) => {
                    lower_aggregate_intrinsic(node, children, fact, &values)
                }
                SourceHirKind::Call
                    if matches!(source_type, Some(SourceType::Float64 | SourceType::Int64))
                        && fact.resolved_definition().is_some_and(is_numeric_intrinsic) =>
                {
                    lower_numeric_intrinsic(
                        node,
                        children,
                        fact.resolved_definition().expect("checked above"),
                        &values,
                        &mut self.value_builder,
                    )
                }
                SourceHirKind::Call if self.mode == SpecializationMode::SelectedPathProbe => {
                    Ok(None)
                }
                SourceHirKind::Call => lower_call(
                    node_id,
                    node,
                    children,
                    hir,
                    &definition_names,
                    &values,
                    &mut self.template_plans,
                    &mut self.published_templates,
                    &mut self.builder,
                    &mut self.value_builder,
                    provenance[node_id],
                ),
                SourceHirKind::Dictionary
                    if special_form_dictionaries
                        .native_payloads
                        .contains(&(node_id as u32)) =>
                {
                    lower_string_dictionary(hir, node_id as u32, &values, node)
                        .map(|value| Some(LoweredValue::Json(serde_json::Value::Object(value))))
                }
                SourceHirKind::Dictionary => lower_dictionary(
                    children,
                    hir,
                    &values,
                    special_form_dictionaries
                        .deferred
                        .contains(&(node_id as u32)),
                ),
                SourceHirKind::Aggregate => Ok(children
                    .iter()
                    .map(|child| values[*child as usize].clone())
                    .collect::<Option<Vec<_>>>()
                    .map(LoweredValue::Aggregate)),
                SourceHirKind::Comprehension => {
                    lower_comprehension(node, children, hir, &values, &mut self.value_builder)
                }
                SourceHirKind::Compare => lower_compile_compare(node, children, &values),
                SourceHirKind::ConditionalExpression => {
                    let condition = children
                        .first()
                        .and_then(|child| values[*child as usize].clone());
                    let selected = match condition {
                        Some(LoweredValue::Scalar(ScalarValue::Bool(true))) => children.get(1),
                        Some(LoweredValue::Scalar(ScalarValue::Bool(false)))
                        | Some(LoweredValue::Null) => children.get(2),
                        _ => children.get(2),
                    };
                    Ok(selected.and_then(|child| values[*child as usize].clone()))
                }
                SourceHirKind::If => {
                    lower_compile_if(node, children, hir, &values, &mut local_bindings)
                }
                SourceHirKind::Binary
                    if self.mode == SpecializationMode::SelectedPathProbe
                        && matches!(
                            source_type,
                            Some(SourceType::Morphism | SourceType::MorphismTemplate)
                        ) =>
                {
                    Ok(None)
                }
                SourceHirKind::Binary
                    if matches!(
                        source_type,
                        Some(SourceType::Morphism | SourceType::MorphismTemplate)
                    ) =>
                {
                    lower_composition(
                        node,
                        children,
                        &values,
                        &mut self.template_plans,
                        &mut self.published_templates,
                        &mut self.builder,
                        provenance[node_id],
                    )
                }
                SourceHirKind::Return => Ok(children
                    .first()
                    .and_then(|child| values[*child as usize].clone())),
                SourceHirKind::Assignment | SourceHirKind::Expression => Ok(children
                    .last()
                    .and_then(|child| values[*child as usize].clone())),
                _ => Ok(None),
            };
            let lowered = match lowered {
                Ok(value) => value,
                // A selected source-for is retained separately in the scan
                // state. Every ordinary lowering failure is only an unknown
                // value while this isolated lowerer determines reachability.
                Err(_) if self.mode == SpecializationMode::SelectedPathProbe => None,
                Err(error) => return Err(error),
            };
            values[node_id] = lowered;
            selected_paths.invalidate(node_id);
            if node.kind() == &SourceHirKind::Assignment
                && !nested_statements.contains(&(node_id as u32))
            {
                bind_assignment(node_id as u32, hir, &values, &mut local_bindings);
            }
        }
        let selected_path =
            self.scan_selected_path(hir, &values, &mut selected_paths, None, instance_identity)?;
        let value = hir
            .roots()
            .iter()
            .rev()
            .find_map(|root| values[*root as usize].clone());
        let selected_source_for_error = match selected_path {
            SelectedPathScan::SourceForError(error) => Some(error),
            SelectedPathScan::Normal | SelectedPathScan::Return => None,
            SelectedPathScan::NeedsCallSpecialization { .. } => {
                unreachable!("selected call specialization is resolved before returning")
            }
        };
        if self.mode == SpecializationMode::Native
            && value.is_none()
            && selected_source_for_error.is_none()
        {
            return Err(MorphismLoweringError::new(format!(
                "{} does not produce a native specialization value",
                definition.qualified_name()
            )));
        }
        Ok(DefinitionSpecialization {
            value,
            selected_source_for_error,
        })
    }

    fn lower_resolved_call(
        &mut self,
        node_id: u32,
        hir: &'a TypedSourceHir,
        arguments: &[SpecializationArgument],
        instance_identity: &str,
    ) -> Result<DefinitionSpecialization, MorphismLoweringError> {
        let node = &hir.nodes()[node_id as usize];
        let fact = &hir.facts()[node_id as usize];
        let mut specializations = Vec::new();
        let mut selected_source_for_error = None;
        if fact.resolved_call_targets().is_empty() {
            for resolved in fact.resolved_definitions() {
                let Some(callee) = self.definitions.get(resolved.as_str()).copied() else {
                    continue;
                };
                let Some(specialization) = self.lower_call_target(
                    callee,
                    arguments,
                    call_instance_identity(node, instance_identity, callee),
                )?
                else {
                    continue;
                };
                if selected_source_for_error.is_none() {
                    selected_source_for_error = specialization.selected_source_for_error;
                }
                specializations.extend(specialization.value);
            }
        } else {
            for target in fact.resolved_call_targets() {
                let Some(callee) = self.definitions.get(target.definition()).copied() else {
                    continue;
                };
                let target_instance = target.instance_identity().map_or_else(
                    || call_instance_identity(node, instance_identity, callee),
                    str::to_owned,
                );
                let Some(specialization) =
                    self.lower_call_target(callee, arguments, target_instance)?
                else {
                    continue;
                };
                if selected_source_for_error.is_none() {
                    selected_source_for_error = specialization.selected_source_for_error;
                }
                specializations.extend(specialization.value);
            }
        }
        let value = match specializations.len() {
            0 => None,
            1 => specializations.pop(),
            _ => Some(LoweredValue::Aggregate(specializations)),
        };
        Ok(DefinitionSpecialization {
            value,
            selected_source_for_error,
        })
    }

    fn lower_call_target(
        &mut self,
        callee: &'a TypedDefinition,
        arguments: &[SpecializationArgument],
        instance_identity: String,
    ) -> Result<Option<DefinitionSpecialization>, MorphismLoweringError> {
        match self.lower_definition(callee, arguments, instance_identity) {
            Ok(specialization) => Ok(Some(specialization)),
            // Other resolved targets may still contain the selected loop.
            Err(_) if self.mode == SpecializationMode::SelectedPathProbe => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn probe_resolved_call(
        &self,
        node_id: u32,
        hir: &'a TypedSourceHir,
        arguments: &[SpecializationArgument],
        instance_identity: &str,
    ) -> Result<Option<MorphismLoweringError>, MorphismLoweringError> {
        let mut probe = Self::with_mode(
            self.definitions.clone(),
            self.clock_hz,
            SpecializationMode::SelectedPathProbe,
        );
        probe
            .lower_resolved_call(node_id, hir, arguments, instance_identity)
            .map(|specialization| specialization.selected_source_for_error)
    }

    fn lower_named_call(
        &mut self,
        node_id: u32,
        hir: &'a TypedSourceHir,
        definition: &str,
        arguments: &[SpecializationArgument],
        instance_identity: &str,
    ) -> Result<DefinitionSpecialization, MorphismLoweringError> {
        let Some(callee) = self.definitions.get(definition).copied() else {
            return Ok(DefinitionSpecialization {
                value: None,
                selected_source_for_error: None,
            });
        };
        let target_instance =
            call_instance_identity(&hir.nodes()[node_id as usize], instance_identity, callee);
        Ok(self
            .lower_call_target(callee, arguments, target_instance)?
            .unwrap_or(DefinitionSpecialization {
                value: None,
                selected_source_for_error: None,
            }))
    }

    fn probe_named_call(
        &self,
        node_id: u32,
        hir: &'a TypedSourceHir,
        definition: &str,
        arguments: &[SpecializationArgument],
        instance_identity: &str,
    ) -> Result<Option<MorphismLoweringError>, MorphismLoweringError> {
        let mut probe = Self::with_mode(
            self.definitions.clone(),
            self.clock_hz,
            SpecializationMode::SelectedPathProbe,
        );
        probe
            .lower_named_call(node_id, hir, definition, arguments, instance_identity)
            .map(|specialization| specialization.selected_source_for_error)
    }

    fn scan_selected_path(
        &mut self,
        hir: &'a TypedSourceHir,
        values: &[Option<LoweredValue>],
        selected_paths: &mut SelectedPathState,
        node_id: Option<u32>,
        instance_identity: &str,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        loop {
            let scan = {
                let mut scanner = SelectedPathScanner::new(
                    hir,
                    values,
                    selected_paths,
                    self.mode == SpecializationMode::SelectedPathProbe,
                    self.clock_hz,
                );
                match node_id {
                    Some(node_id) => scanner.scan_node(node_id, &HashMap::new())?,
                    None => scanner.scan_definition()?,
                }
            };
            let SelectedPathScan::NeedsCallSpecialization {
                node_id,
                definition,
                arguments,
            } = scan
            else {
                return Ok(scan);
            };
            // Native lowering remains authoritative for non-loop diagnostics
            // and values. A top-level scan uses an isolated, selection-only
            // lowerer so failed probes cannot mutate the output arenas. Nested
            // probes reuse that isolated lowerer to retain recursion tracking.
            let selected_source_for_error = match definition.as_deref() {
                Some(definition) if self.mode == SpecializationMode::SelectedPathProbe => {
                    self.lower_named_call(node_id, hir, definition, &arguments, instance_identity)?
                        .selected_source_for_error
                }
                Some(definition) => {
                    self.probe_named_call(node_id, hir, definition, &arguments, instance_identity)?
                }
                None if self.mode == SpecializationMode::SelectedPathProbe => {
                    self.lower_resolved_call(node_id, hir, &arguments, instance_identity)?
                        .selected_source_for_error
                }
                None => self.probe_resolved_call(node_id, hir, &arguments, instance_identity)?,
            };
            selected_paths.bound_calls[node_id as usize].push(BoundCallSpecialization {
                definition,
                arguments,
                selected_source_for_error,
            });
        }
    }

    fn materialize_aggregate(
        &mut self,
        values: Vec<LoweredValue>,
        provenance: ProvenanceId,
    ) -> Result<MorphismNodeId, MorphismLoweringError> {
        let mut children = Vec::with_capacity(values.len());
        for value in values {
            children.push(materialize_morphism_value(
                value,
                &self.template_plans,
                &mut self.published_templates,
                &mut self.builder,
                provenance,
            )?);
        }
        match children.as_slice() {
            [] => Err(MorphismLoweringError::new(
                "cannot reduce an empty Morphism aggregate",
            )),
            [only] => Ok(*only),
            _ => Ok(self.builder.parallel(&children, provenance)),
        }
    }
}

fn lower_comprehension(
    node: &SourceHirNode,
    children: &[u32],
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    value_builder: &mut ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let [element, target, iterable, filters @ ..] = children else {
        return Err(lowering_error(
            node,
            "a native comprehension requires an element, target, and iterable",
        ));
    };
    let Some(LoweredValue::Aggregate(items)) = values[*iterable as usize].clone() else {
        // Static instance-property comprehensions are expanded by reachability
        // analysis into the element call's resolved-definition set.  The
        // aggregate is therefore already complete even though the property
        // itself is not retained as a runtime container in Source HIR.
        let element_fact = &hir.facts()[*element as usize];
        if element_fact.resolved_call_targets().is_empty() {
            return Ok(None);
        }
        return Ok(values[*element as usize].clone().map(|value| match value {
            value @ LoweredValue::Aggregate(_) => value,
            value => LoweredValue::Aggregate(vec![value]),
        }));
    };
    let mut result = Vec::with_capacity(items.len());
    for item in items {
        let mut bindings = HashMap::new();
        bind_comprehension_target(*target, item, hir, &mut bindings, node)?;
        let mut accepted = true;
        for filter in filters {
            match eval_compile_expression(*filter, hir, values, &bindings, value_builder)? {
                Some(LoweredValue::Scalar(ScalarValue::Bool(value))) => accepted &= value,
                Some(_) => {
                    return Err(lowering_error(
                        node,
                        "comprehension filter is not a compile-time bool",
                    ));
                }
                None => return Ok(None),
            }
        }
        if accepted {
            let value = eval_compile_expression(*element, hir, values, &bindings, value_builder)?
                .ok_or_else(|| {
                lowering_error(node, "comprehension element is not compile-time evaluable")
            })?;
            result.push(value);
        }
    }
    Ok(Some(LoweredValue::Aggregate(result)))
}

fn collect_specialization_arguments(
    node: &SourceHirNode,
    children: &[u32],
    mut value_for: impl FnMut(u32) -> Result<Option<LoweredValue>, MorphismLoweringError>,
) -> Result<Vec<SpecializationArgument>, MorphismLoweringError> {
    let mut arguments = Vec::new();
    for (index, child) in children.iter().skip(1).enumerate() {
        let Some(value) = value_for(*child)? else {
            continue;
        };
        let target = if index < node.call_positional_count() as usize {
            SpecializationArgumentTarget::Position(index)
        } else {
            SpecializationArgumentTarget::Keyword(
                node.call_keyword_names()[index - node.call_positional_count() as usize].clone(),
            )
        };
        arguments.push(SpecializationArgument { target, value });
    }
    Ok(arguments)
}

fn eval_compile_expression(
    node_id: u32,
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    bindings: &HashMap<String, LoweredValue>,
    value_builder: &mut ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let node = &hir.nodes()[node_id as usize];
    if node.kind() == &SourceHirKind::Name
        && let Some(value) = node.symbol().and_then(|name| bindings.get(name)).cloned()
    {
        return Ok(Some(value));
    }
    let children = node_children(node, hir);
    let mut evaluated = values.to_vec();
    for child in children {
        evaluated[*child as usize] =
            eval_compile_expression(*child, hir, values, bindings, value_builder)?;
    }
    let fact = &hir.facts()[node_id as usize];
    let source_type = fact.source_type();
    let lowered = match node.kind() {
        SourceHirKind::Constant => lower_literal(node)?,
        SourceHirKind::Name | SourceHirKind::Attribute => values[node_id as usize].clone(),
        SourceHirKind::Aggregate => children
            .iter()
            .map(|child| evaluated[*child as usize].clone())
            .collect::<Option<Vec<_>>>()
            .map(LoweredValue::Aggregate),
        SourceHirKind::Binary | SourceHirKind::Unary if node.value_operation().is_some() => {
            let value = lower_aggregate_operation(node, children, &evaluated).or(
                lower_value_operation(node, children, &evaluated, source_type, value_builder)?,
            );
            if value.is_none() {
                return Err(lowering_error(
                    node,
                    format!(
                        "cannot evaluate {} inside a comprehension",
                        node.value_operation().expect("checked above").as_str()
                    ),
                ));
            }
            value
        }
        SourceHirKind::Call if fact.resolved_definition() == Some("catseq.time_utils.cycles") => {
            lower_cycles_intrinsic(node, children, &evaluated, value_builder)?
        }
        SourceHirKind::Call if matches!(source_type, Some(SourceType::NativeRecord(_))) => {
            lower_native_record_call(node, children, fact, &evaluated, value_builder)?
        }
        SourceHirKind::Call if source_type == Some(&SourceType::FixedAggregate) => {
            lower_aggregate_intrinsic(node, children, fact, &evaluated)?
        }
        SourceHirKind::Call
            if matches!(source_type, Some(SourceType::Float64 | SourceType::Int64))
                && fact.resolved_definition().is_some_and(is_numeric_intrinsic) =>
        {
            lower_numeric_intrinsic(
                node,
                children,
                fact.resolved_definition().expect("checked above"),
                &evaluated,
                value_builder,
            )?
        }
        SourceHirKind::Subscript => lower_static_subscript(children, &evaluated),
        SourceHirKind::Compare => lower_compile_compare(node, children, &evaluated)?,
        SourceHirKind::Comprehension => {
            lower_comprehension(node, children, hir, &evaluated, value_builder)?
        }
        SourceHirKind::ConditionalExpression => {
            let selected = match children
                .first()
                .and_then(|child| evaluated[*child as usize].clone())
            {
                Some(LoweredValue::Scalar(ScalarValue::Bool(true))) => children.get(1),
                Some(LoweredValue::Scalar(ScalarValue::Bool(false))) => children.get(2),
                _ => return Ok(None),
            };
            selected.and_then(|child| evaluated[*child as usize].clone())
        }
        _ => values[node_id as usize].clone(),
    };
    Ok(lowered)
}

fn bind_comprehension_target(
    target: u32,
    value: LoweredValue,
    hir: &TypedSourceHir,
    bindings: &mut HashMap<String, LoweredValue>,
    owner: &SourceHirNode,
) -> Result<(), MorphismLoweringError> {
    let node = &hir.nodes()[target as usize];
    match node.kind() {
        SourceHirKind::Name => {
            let name = node
                .symbol()
                .ok_or_else(|| lowering_error(owner, "comprehension target has no name"))?;
            bindings.insert(name.to_owned(), value);
            Ok(())
        }
        SourceHirKind::Aggregate => {
            let LoweredValue::Aggregate(values) = value else {
                return Err(lowering_error(
                    owner,
                    "cannot unpack a non-aggregate comprehension item",
                ));
            };
            let children = node_children(node, hir);
            if children.len() != values.len() {
                return Err(lowering_error(
                    owner,
                    "comprehension target and item have different arity",
                ));
            }
            for (child, value) in children.iter().zip(values) {
                bind_comprehension_target(*child, value, hir, bindings, owner)?;
            }
            Ok(())
        }
        _ => Err(lowering_error(
            owner,
            "unsupported native comprehension target",
        )),
    }
}

fn lower_entry(
    definition: &TypedDefinition,
    definitions: &HashSet<&str>,
    clock_hz: u64,
) -> Result<NativeArenas, MorphismLoweringError> {
    let hir = definition.hir();
    let mut builder = MorphismArenaBuilder::new();
    let mut value_builder = ValueExprArenaBuilder::new();
    let mut provenance = Vec::with_capacity(hir.nodes().len());
    for node in hir.nodes() {
        provenance.push(builder.intern_provenance(NativeProvenance::new(
            definition.qualified_name(),
            node.anchor().line() as u32,
            node.anchor().column() as u32,
        )));
    }

    let mut values = vec![None::<LoweredValue>; hir.nodes().len()];
    let mut template_plans = Vec::<TemplatePlan>::new();
    let mut published_templates = Vec::<Option<MorphismTemplateId>>::new();
    let special_form_dictionaries = special_form_dictionaries(hir);
    for node_id in 0..hir.nodes().len() {
        if let Some(resolved) = hir.facts()[node_id].resolved_node() {
            values[node_id] = values[resolved as usize].clone();
            continue;
        }
        let node = &hir.nodes()[node_id];
        let children = node_children(node, hir);
        let source_type = hir.facts()[node_id].source_type();
        let lowered = match node.kind() {
            SourceHirKind::Constant => lower_literal(node)?,
            SourceHirKind::Name | SourceHirKind::Attribute
                if source_type == Some(&SourceType::Duration)
                    && hir.facts()[node_id]
                        .resolved_definition()
                        .is_some_and(intrinsics::is_duration_unit) =>
            {
                lower_duration_unit(
                    hir.facts()[node_id]
                        .resolved_definition()
                        .expect("checked above"),
                    clock_hz,
                )
            }
            SourceHirKind::Name | SourceHirKind::Attribute
                if matches!(source_type, Some(SourceType::NativeRecord(_)))
                    && hir.facts()[node_id].compile_value().is_some() =>
            {
                Some(LoweredValue::Json(normalized_to_json(
                    hir.facts()[node_id].compile_value().expect("checked above"),
                    &HashMap::new(),
                )?))
            }
            SourceHirKind::Attribute
                if hir.facts()[node_id].availability() == ValueAvailability::Link =>
            {
                let value_type = source_type_to_value_type(source_type).ok_or_else(|| {
                    lowering_error(node, "environment value has no native scalar type")
                })?;
                Some(LoweredValue::Scalar(ScalarValue::Expr(
                    value_builder.environment_slot(
                        environment_slot_name(node, &default_instance_identity(definition)),
                        value_type,
                    ),
                )))
            }
            SourceHirKind::Subscript
                if hir.facts()[node_id].availability() == ValueAvailability::Link =>
            {
                let slot = children
                    .get(1)
                    .and_then(|child| hir.nodes()[*child as usize].symbol())
                    .unwrap_or("scan_value");
                let value_type = source_type_to_value_type(source_type).ok_or_else(|| {
                    lowering_error(node, "link-time value has no native scalar type")
                })?;
                Some(LoweredValue::Scalar(ScalarValue::Expr(
                    value_builder.runtime_slot(slot, value_type),
                )))
            }
            SourceHirKind::Binary if node.value_operation().is_some() => {
                lower_value_operation(node, children, &values, source_type, &mut value_builder)?
            }
            SourceHirKind::Unary if node.value_operation().is_some() => {
                lower_value_operation(node, children, &values, source_type, &mut value_builder)?
            }
            SourceHirKind::Call
                if hir.facts()[node_id].resolved_definition()
                    == Some("catseq.time_utils.cycles") =>
            {
                lower_cycles_intrinsic(node, children, &values, &mut value_builder)?
            }
            SourceHirKind::Call if matches!(source_type, Some(SourceType::NativeRecord(_))) => {
                lower_native_record_call(
                    node,
                    children,
                    &hir.facts()[node_id],
                    &values,
                    &value_builder,
                )?
            }
            SourceHirKind::Call if source_type == Some(&SourceType::FixedAggregate) => {
                lower_aggregate_intrinsic(node, children, &hir.facts()[node_id], &values)?
            }
            SourceHirKind::Call => lower_call(
                node_id,
                node,
                children,
                hir,
                definitions,
                &values,
                &mut template_plans,
                &mut published_templates,
                &mut builder,
                &mut value_builder,
                provenance[node_id],
            )?,
            SourceHirKind::Dictionary
                if special_form_dictionaries
                    .native_payloads
                    .contains(&(node_id as u32)) =>
            {
                Some(LoweredValue::Json(serde_json::Value::Object(
                    lower_string_dictionary(hir, node_id as u32, &values, node)?,
                )))
            }
            SourceHirKind::Dictionary => lower_dictionary(
                children,
                hir,
                &values,
                special_form_dictionaries
                    .deferred
                    .contains(&(node_id as u32)),
            )?,
            SourceHirKind::Aggregate => children
                .iter()
                .map(|child| values[*child as usize].clone())
                .collect::<Option<Vec<_>>>()
                .map(LoweredValue::Aggregate),
            SourceHirKind::Binary
                if matches!(
                    source_type,
                    Some(SourceType::Morphism | SourceType::MorphismTemplate)
                ) =>
            {
                lower_composition(
                    node,
                    children,
                    &values,
                    &mut template_plans,
                    &mut published_templates,
                    &mut builder,
                    provenance[node_id],
                )?
            }
            SourceHirKind::Return => children
                .first()
                .and_then(|child| values[*child as usize].clone()),
            SourceHirKind::Assignment | SourceHirKind::Expression => children
                .last()
                .and_then(|child| values[*child as usize].clone()),
            _ => None,
        };
        values[node_id] = lowered;
    }

    let root = hir
        .roots()
        .iter()
        .rev()
        .filter_map(|root| values[*root as usize].clone())
        .find_map(|value| match value {
            LoweredValue::Morphism(root) => Some(root),
            _ => None,
        })
        .ok_or_else(|| {
            MorphismLoweringError::new(format!(
                "{} does not produce a native Morphism root",
                definition.qualified_name()
            ))
        })?;
    let morphisms = builder
        .finish(root)
        .map_err(|error| MorphismLoweringError::new(error.to_string()))?;
    let values = value_builder
        .finish()
        .map_err(|error| MorphismLoweringError::new(error.to_string()))?;
    NativeArenas::new(morphisms, values)
        .map_err(|error| MorphismLoweringError::new(error.to_string()))
}

#[allow(clippy::too_many_arguments)]
fn lower_call(
    node_id: usize,
    node: &SourceHirNode,
    children: &[u32],
    hir: &TypedSourceHir,
    definitions: &HashSet<&str>,
    values: &[Option<LoweredValue>],
    template_plans: &mut Vec<TemplatePlan>,
    published_templates: &mut Vec<Option<MorphismTemplateId>>,
    builder: &mut MorphismArenaBuilder,
    value_builder: &mut ValueExprArenaBuilder,
    provenance: ProvenanceId,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let fact = &hir.facts()[node_id];
    let Some(source_type) = fact.source_type() else {
        return Ok(None);
    };
    let resolved = fact.resolved_definition().ok_or_else(|| {
        lowering_error(
            node,
            format!("Morphism call {:?} is unresolved", node.symbol()),
        )
    })?;
    match source_type {
        // A definition-owned channel map is a contextual aggregate, not a
        // durable arena value. Its specialization contract is a completed
        // Morphism, so erase the aggregate at this definition boundary.
        SourceType::ChannelBindings if definitions.contains(resolved) => {
            Ok(Some(LoweredValue::Morphism(builder.definition_ref(
                resolved,
                &call_arguments(children, values, value_builder, node)?,
                provenance,
            ))))
        }
        SourceType::MorphismTemplate => {
            let mut arguments = call_arguments(children, values, value_builder, node)?;
            if arguments.is_empty() && resolved.rsplit('.').next() == Some("hold") {
                arguments.push(value_builder.constant(ValueExprPayload::DurationCycles(0)));
            }
            let id = if definitions.contains(resolved) {
                let id = TemplatePlanId(template_plans.len());
                template_plans.push(TemplatePlan {
                    kind: TemplatePlanKind::DefinitionRef {
                        definition: resolved.to_owned(),
                        arguments,
                    },
                    provenance,
                });
                id
            } else {
                push_intrinsic_template_plan(
                    resolved,
                    arguments,
                    template_plans,
                    value_builder,
                    provenance,
                    node,
                )?
            };
            Ok(Some(LoweredValue::Template(id)))
        }
        SourceType::Morphism if is_repeat_morphism(resolved) => {
            lower_repeat_call(node, children, values, builder, value_builder, provenance)
        }
        SourceType::Morphism if intrinsics::is_oasm_black_box(resolved) => lower_oasm_black_box(
            node,
            children,
            hir,
            values,
            builder,
            value_builder,
            provenance,
        ),
        SourceType::Morphism if intrinsics::is_identity(resolved) => {
            let mut duration = call_arguments(children, values, value_builder, node)?
                .first()
                .copied()
                .ok_or_else(|| lowering_error(node, "identity requires a duration"))?;
            if value_builder.value_type(duration) != Some(ValueExprType::Duration) {
                let explicit_zero = children.get(1).is_some_and(|child| {
                    matches!(
                        hir.nodes()[*child as usize].literal(),
                        Some(SourceLiteral::Int(value)) if value == "0"
                    )
                });
                if !explicit_zero {
                    return Err(lowering_error(
                        node,
                        "identity duration must use an explicit unit (s, ms, us, or ns) or cycles(...); only identity(0) is unitless",
                    ));
                }
                duration = value_builder.constant(ValueExprPayload::DurationCycles(0));
            }
            Ok(Some(LoweredValue::Morphism(
                builder.logical_shift(duration, provenance),
            )))
        }
        SourceType::Morphism if resolved == "rb1system.utils.dict_to_morphism" => {
            let bindings = children
                .iter()
                .skip(1)
                .find_map(|child| match values[*child as usize].clone() {
                    Some(LoweredValue::ChannelBindings(bindings)) => Some(bindings),
                    _ => None,
                })
                .ok_or_else(|| {
                    lowering_error(node, "dict_to_morphism requires channel bindings")
                })?;
            let root = materialize_bindings(
                bindings,
                template_plans,
                published_templates,
                builder,
                provenance,
            )?;
            Ok(Some(LoweredValue::Morphism(root)))
        }
        SourceType::Morphism if resolved == "catseq.instantiate" => {
            let template = children
                .first()
                .and_then(|child| values[*child as usize].clone())
                .and_then(|value| match value {
                    LoweredValue::Template(template) => Some(template),
                    _ => None,
                })
                .ok_or_else(|| {
                    lowering_error(node, "template invocation has no native template")
                })?;
            let channel_node = children.get(1).copied().ok_or_else(|| {
                lowering_error(node, "template invocation has no channel argument")
            })?;
            let channel = native_channel_key(hir, channel_node);
            let root = instantiate_template(
                template,
                &channel,
                template_plans,
                published_templates,
                builder,
            )?;
            Ok(Some(LoweredValue::Morphism(root)))
        }
        SourceType::Morphism if definitions.contains(resolved) => {
            Ok(Some(LoweredValue::Morphism(builder.definition_ref(
                resolved,
                &call_arguments(children, values, value_builder, node)?,
                provenance,
            ))))
        }
        SourceType::Morphism => Ok(Some(LoweredValue::Morphism(builder.atomic(
            resolved,
            &call_arguments(children, values, value_builder, node)?,
            provenance,
        )))),
        _ => Ok(None),
    }
}

fn lower_dictionary(
    children: &[u32],
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    deferred_to_special_form: bool,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let half = children.len() / 2;
    let mut bindings = Vec::with_capacity(half);
    for (channel, template) in children[..half].iter().zip(&children[half..]) {
        let Some(LoweredValue::Template(template)) = values[*template as usize].clone() else {
            if deferred_to_special_form {
                return Ok(None);
            }
            return Err(lowering_error(
                &hir.nodes()[*template as usize],
                "channel binding value is not a MorphismTemplate",
            ));
        };
        bindings.push(ChannelBinding {
            channel: native_channel_key(hir, *channel),
            template,
        });
    }
    Ok(Some(LoweredValue::ChannelBindings(bindings)))
}

#[derive(Default)]
struct SpecialFormDictionaries {
    deferred: HashSet<u32>,
    native_payloads: HashSet<u32>,
}

fn special_form_dictionaries(hir: &TypedSourceHir) -> SpecialFormDictionaries {
    let mut dictionaries = SpecialFormDictionaries::default();
    for (node_id, node) in hir.nodes().iter().enumerate() {
        if node.kind() != &SourceHirKind::Call
            || !hir.facts()[node_id]
                .resolved_definition()
                .is_some_and(intrinsics::is_oasm_black_box)
        {
            continue;
        }

        let children = node_children(node, hir);
        for argument in children.iter().skip(1) {
            let mut candidate = *argument;
            let mut resolved = HashSet::new();
            while resolved.insert(candidate) {
                let Some(next) = hir.facts()[candidate as usize].resolved_node() else {
                    break;
                };
                candidate = next;
            }
            if hir.nodes()[candidate as usize].kind() == &SourceHirKind::Dictionary {
                dictionaries.deferred.insert(candidate);
            }
        }

        for (position, name) in [(2, "user_args"), (3, "user_kwargs"), (4, "metadata")] {
            if let Some(argument) = call_argument_node(node, children, position, name) {
                collect_native_payload_dictionaries(
                    hir,
                    argument,
                    &mut dictionaries.native_payloads,
                );
            }
        }
    }
    dictionaries
}

fn collect_native_payload_dictionaries(
    hir: &TypedSourceHir,
    root: u32,
    dictionaries: &mut HashSet<u32>,
) {
    let mut pending = vec![root];
    let mut visited = HashSet::new();
    while let Some(candidate) = pending.pop() {
        if !visited.insert(candidate) {
            continue;
        }
        if hir.nodes()[candidate as usize].kind() == &SourceHirKind::Dictionary {
            dictionaries.insert(candidate);
        }
        if let Some(resolved) = hir.facts()[candidate as usize].resolved_node() {
            pending.push(resolved);
        }
        pending.extend(node_children(&hir.nodes()[candidate as usize], hir));
    }
}

#[allow(clippy::too_many_arguments)]
fn lower_oasm_black_box(
    node: &SourceHirNode,
    children: &[u32],
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    builder: &mut MorphismArenaBuilder,
    value_builder: &mut ValueExprArenaBuilder,
    provenance: ProvenanceId,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    const PARAMETERS: [&str; 5] = [
        "duration_cycles",
        "board_funcs",
        "user_args",
        "user_kwargs",
        "metadata",
    ];
    let positional_count = node.call_positional_count() as usize;
    if positional_count > PARAMETERS.len() {
        return Err(lowering_error(
            node,
            format!(
                "black_box accepts at most {} positional arguments",
                PARAMETERS.len()
            ),
        ));
    }
    for keyword in node.call_keyword_names() {
        let Some(position) = PARAMETERS.iter().position(|parameter| parameter == keyword) else {
            return Err(lowering_error(
                node,
                format!("black_box got unexpected keyword argument {keyword:?}"),
            ));
        };
        if position < positional_count {
            return Err(lowering_error(
                node,
                format!("black_box got multiple values for argument {keyword:?}"),
            ));
        }
    }

    let duration_node = call_argument_node(node, children, 0, "duration_cycles")
        .ok_or_else(|| lowering_error(node, "black_box requires duration_cycles"))?;
    let board_funcs_node = call_argument_node(node, children, 1, "board_funcs")
        .ok_or_else(|| lowering_error(node, "black_box requires board_funcs"))?;

    let duration_value = values[duration_node as usize]
        .clone()
        .ok_or_else(|| lowering_error(node, "blackbox duration is not compile/link evaluable"))?;
    let LoweredValue::Scalar(duration_value) = duration_value else {
        return Err(lowering_error(
            node,
            "blackbox duration_cycles must be an integer Cycle Count",
        ));
    };
    let duration = scalar_to_expr(duration_value, value_builder, node)?;
    if value_builder.value_type(duration) != Some(ValueExprType::Int64) {
        return Err(lowering_error(
            node,
            "blackbox duration_cycles must have type int",
        ));
    }

    let arguments_json = call_argument_node(node, children, 2, "user_args")
        .and_then(|argument| values[argument as usize].as_ref())
        .map(lowered_to_json)
        .transpose()?
        .unwrap_or_else(|| serde_json::Value::Array(Vec::new()));
    if !arguments_json.is_array() {
        return Err(lowering_error(
            node,
            "blackbox user_args must be a tuple or list",
        ));
    }
    let keyword_arguments_json = call_argument_node(node, children, 3, "user_kwargs")
        .map(|argument| lower_string_dictionary(hir, argument, values, node))
        .transpose()?
        .unwrap_or_default();
    let metadata_json = call_argument_node(node, children, 4, "metadata")
        .map(|argument| lower_string_dictionary(hir, argument, values, node))
        .transpose()?
        .unwrap_or_default();
    let arguments = value_builder.constant(ValueExprPayload::Json(arguments_json));
    let keyword_arguments = value_builder.constant(ValueExprPayload::Json(
        serde_json::Value::Object(keyword_arguments_json),
    ));
    let metadata = value_builder.constant(ValueExprPayload::Json(serde_json::Value::Object(
        metadata_json,
    )));

    let mut boards = BTreeSet::new();
    let mut calls = Vec::new();
    for (board_node, callable_node) in dictionary_entries(hir, board_funcs_node, node)? {
        let board_source = &hir.nodes()[board_node as usize];
        let board_fact = &hir.facts()[board_node as usize];
        let board = board_fact
            .compile_value()
            .map(normalized_board_id)
            .transpose()
            .map_err(|error| lowering_error(board_source, error.to_string()))?
            .flatten()
            .ok_or_else(|| {
                lowering_error(
                    board_source,
                    "blackbox board key must resolve to a static Board",
                )
            })?;
        if !boards.insert(board.clone()) {
            return Err(lowering_error(
                board_source,
                format!("blackbox board {board:?} has more than one callback"),
            ));
        }
        let callable = hir.facts()[callable_node as usize]
            .resolved_definition()
            .filter(|definition| !definition.contains("<locals>"))
            .ok_or_else(|| {
                lowering_error(
                    &hir.nodes()[callable_node as usize],
                    "blackbox callback must be a module-level function",
                )
            })?
            .to_owned();
        calls.push((board, callable, arguments, keyword_arguments));
    }
    if calls.is_empty() {
        return Err(lowering_error(
            node,
            "black_box board_funcs cannot be empty",
        ));
    }

    Ok(Some(LoweredValue::Morphism(
        builder.opaque(duration, &calls, metadata, provenance),
    )))
}

fn call_argument_node(
    call: &SourceHirNode,
    children: &[u32],
    position: usize,
    name: &str,
) -> Option<u32> {
    if position < call.call_positional_count() as usize {
        return children.get(position + 1).copied();
    }
    call.call_keyword_names()
        .iter()
        .position(|keyword| keyword == name)
        .and_then(|keyword| children.get(1 + call.call_positional_count() as usize + keyword))
        .copied()
}

fn dictionary_entries(
    hir: &TypedSourceHir,
    mut dictionary: u32,
    call: &SourceHirNode,
) -> Result<Vec<(u32, u32)>, MorphismLoweringError> {
    let mut visited = BTreeSet::new();
    while visited.insert(dictionary) {
        let Some(resolved) = hir.facts()[dictionary as usize].resolved_node() else {
            break;
        };
        dictionary = resolved;
    }
    let dictionary_node = &hir.nodes()[dictionary as usize];
    if dictionary_node.kind() != &SourceHirKind::Dictionary {
        return Err(lowering_error(
            call,
            "blackbox argument must be a dictionary literal",
        ));
    }
    let children = node_children(dictionary_node, hir);
    if !children.len().is_multiple_of(2) {
        return Err(lowering_error(
            call,
            "blackbox dictionary has an invalid shape",
        ));
    }
    let half = children.len() / 2;
    Ok(children[..half]
        .iter()
        .copied()
        .zip(children[half..].iter().copied())
        .collect())
}

fn lower_string_dictionary(
    hir: &TypedSourceHir,
    dictionary: u32,
    values: &[Option<LoweredValue>],
    call: &SourceHirNode,
) -> Result<serde_json::Map<String, serde_json::Value>, MorphismLoweringError> {
    if matches!(values[dictionary as usize], Some(LoweredValue::Null)) {
        return Ok(serde_json::Map::new());
    }
    let mut lowered = serde_json::Map::new();
    for (key, value) in dictionary_entries(hir, dictionary, call)? {
        let Some(SourceLiteral::String(key)) = hir.nodes()[key as usize].literal() else {
            return Err(lowering_error(
                &hir.nodes()[key as usize],
                "blackbox keyword keys must be string literals",
            ));
        };
        let value = values[value as usize]
            .as_ref()
            .ok_or_else(|| lowering_error(call, "blackbox keyword value is not evaluable"))?;
        lowered.insert(key.clone(), lowered_to_json(value)?);
    }
    Ok(lowered)
}

fn lower_native_record_call(
    node: &SourceHirNode,
    children: &[u32],
    fact: &crate::SemanticFact,
    values: &[Option<LoweredValue>],
    value_builder: &ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let resolved = fact.resolved_definition().unwrap_or_default();
    if resolved == "numpy.load" || resolved.ends_with(".np.load") {
        return Ok(Some(LoweredValue::Json(serde_json::Value::Null)));
    }
    if intrinsics::is_native_record_replace(resolved) {
        return lower_native_record_replace(node, children, values, value_builder);
    }
    let arguments = children
        .iter()
        .skip(1)
        .enumerate()
        .map(|(index, child)| {
            values[*child as usize].clone().map(|value| {
                let name = (index >= node.call_positional_count() as usize).then(|| {
                    node.call_keyword_names()[index - node.call_positional_count() as usize].clone()
                });
                (name, value)
            })
        })
        .collect::<Option<Vec<_>>>();
    let Some(arguments) = arguments else {
        return Ok(None);
    };
    let schema_name = match fact.source_type() {
        Some(SourceType::NativeRecord(schema)) => schema.as_str(),
        _ => resolved.rsplit('.').next().unwrap_or("NativeRecord"),
    };
    let Some(schema) = native_records::schema(schema_name) else {
        return Ok(None);
    };
    let mut record = serde_json::Map::new();
    record.insert(
        "$type".to_owned(),
        serde_json::Value::String(schema.name().to_owned()),
    );
    for (position, (name, value)) in arguments.into_iter().enumerate() {
        let field = match name {
            Some(name) => schema.field(&name).ok_or_else(|| {
                lowering_error(
                    node,
                    format!(
                        "unknown Native Record field `{name}` for `{}`",
                        schema.name()
                    ),
                )
            })?,
            None => schema.field_at(position).ok_or_else(|| {
                lowering_error(
                    node,
                    format!(
                        "too many positional fields for Native Record `{}`",
                        schema.name()
                    ),
                )
            })?,
        };
        if !native_record_value_matches(field.field_type(), &value, value_builder) {
            return Err(native_record_field_type_error(
                node,
                "Native Record construction",
                schema.name(),
                field.name(),
                field.field_type(),
                &value,
                value_builder,
            ));
        }
        record.insert(field.name().to_owned(), lowered_to_json(&value)?);
    }
    schema.populate_defaults(&mut record);
    Ok(Some(LoweredValue::Json(serde_json::Value::Object(record))))
}

fn lower_native_record_replace(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
    value_builder: &ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let mut arguments = Vec::with_capacity(children.len().saturating_sub(1));
    for (index, child) in children.iter().skip(1).enumerate() {
        let name = if index < node.call_positional_count() as usize {
            None
        } else {
            Some(
                node.call_keyword_names()
                    .get(index - node.call_positional_count() as usize)
                    .cloned()
                    .ok_or_else(|| {
                        lowering_error(node, "catseq.replace has an invalid keyword argument")
                    })?,
            )
        };
        let description = name
            .as_deref()
            .map(|name| format!("field `{name}`"))
            .unwrap_or_else(|| format!("positional argument {}", index + 1));
        let value = values[*child as usize].clone().ok_or_else(|| {
            lowering_error(
                node,
                format!("catseq.replace {description} cannot be lowered to a native value"),
            )
        })?;
        arguments.push((name, value));
    }

    let Some((base_name, base)) = arguments.first().cloned() else {
        return Err(lowering_error(
            node,
            "catseq.replace requires a Native Record as its first argument",
        ));
    };
    if base_name.is_some() {
        return Err(lowering_error(
            node,
            "catseq.replace first argument must be positional",
        ));
    }
    let LoweredValue::Json(serde_json::Value::Object(mut record)) = base else {
        return Err(lowering_error(
            node,
            "catseq.replace requires a Native Record as its first argument",
        ));
    };
    let schema_name = record
        .get("$type")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| {
            lowering_error(
                node,
                "catseq.replace requires a registered Native Record schema",
            )
        })?;
    let schema = native_records::schema(&schema_name).ok_or_else(|| {
        lowering_error(
            node,
            format!("catseq.replace does not support Native Record `{schema_name}`"),
        )
    })?;

    schema.populate_defaults(&mut record);

    for name in record.keys() {
        if name == "$type" {
            continue;
        }
        if schema.field(name).is_none() {
            return Err(lowering_error(
                node,
                format!(
                    "unknown Native Record field `{name}` for `{}`",
                    schema.name()
                ),
            ));
        }
    }
    for field in schema.fields() {
        let value = record.get(field.name()).ok_or_else(|| {
            lowering_error(
                node,
                format!(
                    "catseq.replace base `{}` is missing required field `{}`",
                    schema.name(),
                    field.name()
                ),
            )
        })?;
        let value = LoweredValue::Json(value.clone());
        if !native_record_value_matches(field.field_type(), &value, value_builder) {
            return Err(native_record_field_type_error(
                node,
                "catseq.replace",
                schema.name(),
                field.name(),
                field.field_type(),
                &value,
                value_builder,
            ));
        }
    }

    for (name, value) in arguments.into_iter().skip(1) {
        let Some(name) = name else {
            return Err(lowering_error(node, "catseq.replace fields must be named"));
        };
        let field = schema.field(&name).ok_or_else(|| {
            lowering_error(
                node,
                format!(
                    "unknown Native Record field `{name}` for `{}`",
                    schema.name()
                ),
            )
        })?;
        if !native_record_value_matches(field.field_type(), &value, value_builder) {
            return Err(native_record_field_type_error(
                node,
                "catseq.replace",
                schema.name(),
                field.name(),
                field.field_type(),
                &value,
                value_builder,
            ));
        }
        record.insert(field.name().to_owned(), lowered_to_json(&value)?);
    }
    Ok(Some(LoweredValue::Json(serde_json::Value::Object(record))))
}

fn native_record_field_type_error(
    node: &SourceHirNode,
    operation: &str,
    schema: &str,
    field: &str,
    expected: NativeRecordFieldType,
    found: &LoweredValue,
    value_builder: &ValueExprArenaBuilder,
) -> MorphismLoweringError {
    lowering_error(
        node,
        format!(
            "{operation} field `{field}` for `{schema}` expects {expected}, found {}",
            native_record_value_description(found, value_builder)
        ),
    )
}

fn native_record_value_matches(
    expected: NativeRecordFieldType,
    value: &LoweredValue,
    value_builder: &ValueExprArenaBuilder,
) -> bool {
    match expected {
        NativeRecordFieldType::Bool => native_record_value_is_bool(value, value_builder),
        NativeRecordFieldType::Int64 => native_record_value_is_int(value, value_builder),
        NativeRecordFieldType::Float64 => native_record_value_is_float(value, value_builder),
        NativeRecordFieldType::OptionalInt64 => {
            native_record_value_is_null(value) || native_record_value_is_int(value, value_builder)
        }
        NativeRecordFieldType::OptionalFloat64 => {
            native_record_value_is_null(value) || native_record_value_is_float(value, value_builder)
        }
        NativeRecordFieldType::AggregateOfOptionalFloat64 => match value {
            LoweredValue::Aggregate(values) => values.iter().all(|value| {
                native_record_value_is_null(value)
                    || native_record_value_is_float(value, value_builder)
            }),
            LoweredValue::Json(serde_json::Value::Array(values)) => values
                .iter()
                .all(|value| native_record_json_is_optional_float(value, value_builder)),
            _ => false,
        },
    }
}

fn native_record_value_is_null(value: &LoweredValue) -> bool {
    matches!(
        value,
        LoweredValue::Null | LoweredValue::Json(serde_json::Value::Null)
    )
}

fn native_record_value_is_bool(
    value: &LoweredValue,
    value_builder: &ValueExprArenaBuilder,
) -> bool {
    match value {
        LoweredValue::Scalar(ScalarValue::Bool(_))
        | LoweredValue::Json(serde_json::Value::Bool(_)) => true,
        LoweredValue::Scalar(ScalarValue::Expr(id)) => {
            value_builder.value_type(*id) == Some(ValueExprType::Bool)
        }
        LoweredValue::Json(value) => {
            native_record_json_expr_type(value, value_builder) == Some(ValueExprType::Bool)
        }
        _ => false,
    }
}

fn native_record_value_is_int(value: &LoweredValue, value_builder: &ValueExprArenaBuilder) -> bool {
    match value {
        LoweredValue::Scalar(ScalarValue::Int(_)) => true,
        LoweredValue::Json(serde_json::Value::Number(number)) => {
            number.as_i64().is_some()
                || number
                    .as_u64()
                    .is_some_and(|value| i64::try_from(value).is_ok())
        }
        LoweredValue::Scalar(ScalarValue::Expr(id)) => {
            value_builder.value_type(*id) == Some(ValueExprType::Int64)
        }
        LoweredValue::Json(value) => {
            native_record_json_expr_type(value, value_builder) == Some(ValueExprType::Int64)
        }
        _ => false,
    }
}

fn native_record_value_is_float(
    value: &LoweredValue,
    value_builder: &ValueExprArenaBuilder,
) -> bool {
    match value {
        LoweredValue::Scalar(ScalarValue::Int(_) | ScalarValue::Float(_))
        | LoweredValue::Json(serde_json::Value::Number(_)) => true,
        LoweredValue::Scalar(ScalarValue::Expr(id)) => matches!(
            value_builder.value_type(*id),
            Some(ValueExprType::Int64 | ValueExprType::Float64)
        ),
        LoweredValue::Json(value) => matches!(
            native_record_json_expr_type(value, value_builder),
            Some(ValueExprType::Int64 | ValueExprType::Float64)
        ),
        _ => false,
    }
}

fn native_record_json_is_optional_float(
    value: &serde_json::Value,
    value_builder: &ValueExprArenaBuilder,
) -> bool {
    value.is_null()
        || value.is_number()
        || matches!(
            native_record_json_expr_type(value, value_builder),
            Some(ValueExprType::Int64 | ValueExprType::Float64)
        )
}

fn native_record_json_expr_type(
    value: &serde_json::Value,
    value_builder: &ValueExprArenaBuilder,
) -> Option<ValueExprType> {
    let index = value
        .as_object()?
        .get("$value_expr")?
        .as_u64()
        .and_then(|index| u32::try_from(index).ok())?;
    value_builder.value_type(ValueExprId::from_index(index))
}

fn native_record_value_description(
    value: &LoweredValue,
    value_builder: &ValueExprArenaBuilder,
) -> String {
    match value {
        LoweredValue::Null | LoweredValue::Json(serde_json::Value::Null) => "Unit".to_owned(),
        LoweredValue::Scalar(ScalarValue::Bool(_))
        | LoweredValue::Json(serde_json::Value::Bool(_)) => "Bool".to_owned(),
        LoweredValue::Scalar(ScalarValue::Int(_)) => "Int64".to_owned(),
        LoweredValue::Scalar(ScalarValue::Float(_))
        | LoweredValue::Json(serde_json::Value::Number(_)) => "Float64".to_owned(),
        LoweredValue::Scalar(ScalarValue::DurationCycles(_)) => "Duration".to_owned(),
        LoweredValue::Scalar(ScalarValue::String(_))
        | LoweredValue::Json(serde_json::Value::String(_)) => "String".to_owned(),
        LoweredValue::Scalar(ScalarValue::Expr(id)) => value_builder
            .value_type(*id)
            .map(|value_type| format!("Link<{value_type:?}>"))
            .unwrap_or_else(|| "unknown Link value".to_owned()),
        LoweredValue::Aggregate(_) | LoweredValue::Json(serde_json::Value::Array(_)) => {
            "Aggregate with incompatible element types".to_owned()
        }
        LoweredValue::Json(value) => native_record_json_expr_type(value, value_builder)
            .map(|value_type| format!("Link<{value_type:?}>"))
            .unwrap_or_else(|| "JSON value".to_owned()),
        LoweredValue::Morphism(_) => "Morphism".to_owned(),
        LoweredValue::Template(_) => "MorphismTemplate".to_owned(),
        LoweredValue::Instance(_) => "CompileInstance".to_owned(),
        LoweredValue::ChannelBindings(_) => "ChannelBindings".to_owned(),
    }
}

fn lower_composition(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
    template_plans: &mut Vec<TemplatePlan>,
    published_templates: &mut Vec<Option<MorphismTemplateId>>,
    builder: &mut MorphismArenaBuilder,
    provenance: ProvenanceId,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    if children.len() != 2 {
        return Err(lowering_error(
            node,
            "Morphism composition is not binary in Source HIR",
        ));
    }
    let operation = node
        .morphism_composition()
        .ok_or_else(|| lowering_error(node, "Morphism Binary node has no composition operation"))?;
    let left = values[children[0] as usize].clone();
    let right = values[children[1] as usize].clone();
    match (left, right) {
        (Some(LoweredValue::Template(left)), Some(LoweredValue::Template(right))) => {
            let id = TemplatePlanId(template_plans.len());
            let kind = match operation {
                MorphismComposition::AutoSerial => TemplatePlanKind::Serial {
                    children: vec![left, right],
                    boundaries: vec![BoundaryPolicy::Auto],
                },
                MorphismComposition::StrictSerial => TemplatePlanKind::Serial {
                    children: vec![left, right],
                    boundaries: vec![BoundaryPolicy::Strict],
                },
                MorphismComposition::Parallel => TemplatePlanKind::Parallel(vec![left, right]),
            };
            template_plans.push(TemplatePlan { kind, provenance });
            Ok(Some(LoweredValue::Template(id)))
        }
        (Some(left), Some(right)) => {
            let left = materialize_morphism_value(
                left,
                template_plans,
                published_templates,
                builder,
                provenance,
            )?;
            let right = materialize_morphism_value(
                right,
                template_plans,
                published_templates,
                builder,
                provenance,
            )?;
            let root = match operation {
                MorphismComposition::AutoSerial => {
                    builder.serial(&[left, right], &[BoundaryPolicy::Auto], provenance)
                }
                MorphismComposition::StrictSerial => {
                    builder.serial(&[left, right], &[BoundaryPolicy::Strict], provenance)
                }
                MorphismComposition::Parallel => builder.parallel(&[left, right], provenance),
            };
            Ok(Some(LoweredValue::Morphism(root)))
        }
        (None, _) | (_, None) => Ok(None),
    }
}

fn materialize_morphism_value(
    value: LoweredValue,
    template_plans: &[TemplatePlan],
    published_templates: &mut Vec<Option<MorphismTemplateId>>,
    builder: &mut MorphismArenaBuilder,
    provenance: ProvenanceId,
) -> Result<MorphismNodeId, MorphismLoweringError> {
    match value {
        LoweredValue::Morphism(root) => Ok(root),
        LoweredValue::ChannelBindings(bindings) => materialize_bindings(
            bindings,
            template_plans,
            published_templates,
            builder,
            provenance,
        ),
        LoweredValue::Aggregate(values) => {
            let mut children = Vec::with_capacity(values.len());
            for value in values {
                children.push(materialize_morphism_value(
                    value,
                    template_plans,
                    published_templates,
                    builder,
                    provenance,
                )?);
            }
            Ok(builder.parallel(&children, provenance))
        }
        LoweredValue::Template(template)
            if matches!(
                &template_plans[template.0].kind,
                TemplatePlanKind::Operation { operation, .. }
                    if operation == "catseq.hardware.sync.global_sync"
            ) =>
        {
            let TemplatePlanKind::Operation {
                operation,
                arguments,
            } = &template_plans[template.0].kind
            else {
                unreachable!("matched above")
            };
            Ok(builder.atomic(operation, arguments, template_plans[template.0].provenance))
        }
        LoweredValue::Null
        | LoweredValue::Instance(_)
        | LoweredValue::Json(_)
        | LoweredValue::Template(_)
        | LoweredValue::Scalar(_) => Err(MorphismLoweringError::new(
            "unbound MorphismTemplate used where Morphism is required",
        )),
    }
}

fn materialize_bindings(
    bindings: Vec<ChannelBinding>,
    template_plans: &[TemplatePlan],
    published_templates: &mut Vec<Option<MorphismTemplateId>>,
    builder: &mut MorphismArenaBuilder,
    provenance: ProvenanceId,
) -> Result<MorphismNodeId, MorphismLoweringError> {
    let mut children = Vec::with_capacity(bindings.len());
    for binding in bindings {
        children.push(instantiate_template(
            binding.template,
            &binding.channel,
            template_plans,
            published_templates,
            builder,
        )?);
    }
    match children.as_slice() {
        [] => Err(MorphismLoweringError::new("empty channel binding map")),
        [only] => Ok(*only),
        _ => Ok(builder.parallel(&children, provenance)),
    }
}

fn instantiate_template(
    root: TemplatePlanId,
    channel: &str,
    plans: &[TemplatePlan],
    published_templates: &mut Vec<Option<MorphismTemplateId>>,
    builder: &mut MorphismArenaBuilder,
) -> Result<MorphismNodeId, MorphismLoweringError> {
    if published_templates.len() < plans.len() {
        published_templates.resize(plans.len(), None);
    }
    if let Some(template) = published_templates[root.0] {
        return Ok(builder.instantiate(template, channel, plans[root.0].provenance));
    }
    let mut reachable = vec![false; root.0 + 1];
    let mut pending = vec![root];
    while let Some(plan) = pending.pop() {
        if std::mem::replace(&mut reachable[plan.0], true) {
            continue;
        }
        match &plans[plan.0].kind {
            TemplatePlanKind::Operation { .. }
            | TemplatePlanKind::DefinitionRef { .. }
            | TemplatePlanKind::Wait { .. } => {}
            TemplatePlanKind::Serial { children, .. } | TemplatePlanKind::Parallel(children) => {
                pending.extend(children.iter().copied())
            }
        }
    }
    let mut lowered = vec![None; root.0 + 1];
    for index in 0..=root.0 {
        if !reachable[index] {
            continue;
        }
        let plan = &plans[index];
        let node = match &plan.kind {
            TemplatePlanKind::Operation {
                operation,
                arguments,
            } => builder.atomic(operation, arguments, plan.provenance),
            TemplatePlanKind::DefinitionRef {
                definition,
                arguments,
            } => builder.definition_ref(definition, arguments, plan.provenance),
            TemplatePlanKind::Wait {
                duration,
                semantics,
            } => match semantics {
                WaitSemantics::LogicalDisplacement => {
                    builder.logical_shift(*duration, plan.provenance)
                }
                WaitSemantics::PhysicalInterval => {
                    builder.physical_wait(*duration, plan.provenance)
                }
            },
            TemplatePlanKind::Serial {
                children,
                boundaries,
            } => {
                let children = children
                    .iter()
                    .map(|child| lowered[child.0].expect("template plan is topological"))
                    .collect::<Vec<_>>();
                builder.serial(&children, boundaries, plan.provenance)
            }
            TemplatePlanKind::Parallel(children) => {
                let children = children
                    .iter()
                    .map(|child| lowered[child.0].expect("template plan is topological"))
                    .collect::<Vec<_>>();
                builder.parallel(&children, plan.provenance)
            }
        };
        lowered[index] = Some(node);
    }
    let body = lowered[root.0]
        .ok_or_else(|| MorphismLoweringError::new("template root was not lowered"))?;
    let template = builder.publish_template(body);
    published_templates[root.0] = Some(template);
    Ok(builder.instantiate(template, channel, plans[root.0].provenance))
}

fn push_intrinsic_template_plan(
    operation: &str,
    arguments: Vec<ValueExprId>,
    plans: &mut Vec<TemplatePlan>,
    values: &mut ValueExprArenaBuilder,
    provenance: ProvenanceId,
    source: &SourceHirNode,
) -> Result<TemplatePlanId, MorphismLoweringError> {
    let push_operation =
        |plans: &mut Vec<TemplatePlan>, operation: &str, arguments: Vec<ValueExprId>| {
            let id = TemplatePlanId(plans.len());
            plans.push(TemplatePlan {
                kind: TemplatePlanKind::Operation {
                    operation: operation.to_owned(),
                    arguments,
                },
                provenance,
            });
            id
        };
    let push_wait =
        |plans: &mut Vec<TemplatePlan>, duration: ValueExprId, semantics: WaitSemantics| {
            let id = TemplatePlanId(plans.len());
            plans.push(TemplatePlan {
                kind: TemplatePlanKind::Wait {
                    duration,
                    semantics,
                },
                provenance,
            });
            id
        };
    let required_argument = |index: usize, description: &str| {
        arguments
            .get(index)
            .copied()
            .ok_or_else(|| lowering_error(source, format!("{description} is absent")))
    };
    let required_duration_argument = |index: usize, description: &str| {
        let argument = required_argument(index, description)?;
        if values.value_type(argument) != Some(ValueExprType::Duration) {
            return Err(lowering_error(
                source,
                format!(
                    "{description} must be a Duration with an explicit unit (s, ms, us, or ns) or cycles(...)"
                ),
            ));
        }
        Ok(argument)
    };

    let Some(template) = intrinsics::native_morphism_template(operation) else {
        return Ok(push_operation(plans, operation, arguments));
    };
    let (children, boundaries) = match template {
        NativeMorphismTemplate::Hold => {
            return Ok(push_wait(
                plans,
                required_duration_argument(0, "hold duration")?,
                WaitSemantics::LogicalDisplacement,
            ));
        }
        NativeMorphismTemplate::TtlPulse => {
            let duration = required_duration_argument(0, "TTL pulse duration")?;
            let high = push_operation(plans, "catseq.hardware.ttl.set_high", Vec::new());
            let wait = push_wait(plans, duration, WaitSemantics::PhysicalInterval);
            let low = push_operation(plans, "catseq.hardware.ttl.set_low", Vec::new());
            (vec![high, wait, low], vec![BoundaryPolicy::Auto; 2])
        }
        NativeMorphismTemplate::RwgSetState => {
            let targets = required_argument(0, "RWG static targets")?;
            let phase_reset = arguments
                .get(1)
                .copied()
                .unwrap_or_else(|| values.constant(ValueExprPayload::Bool(true)));
            let waveforms =
                values.rwg_waveforms(RwgWaveformDerivation::Static, &[targets, phase_reset]);
            let load = push_operation(plans, "catseq.hardware.rwg.load", vec![waveforms]);
            let play = push_operation(plans, "catseq.hardware.rwg.play", Vec::new());
            (vec![load, play], vec![BoundaryPolicy::Auto])
        }
        NativeMorphismTemplate::RwgRfPulse => {
            let duration = required_duration_argument(0, "RWG RF pulse duration")?;
            let on = push_operation(plans, "catseq.hardware.rwg.rf_on", Vec::new());
            let wait = push_wait(plans, duration, WaitSemantics::PhysicalInterval);
            let off = push_operation(plans, "catseq.hardware.rwg.rf_off", Vec::new());
            (vec![on, wait, off], vec![BoundaryPolicy::Auto; 2])
        }
        NativeMorphismTemplate::RwgLinearRamp => {
            let targets = required_argument(0, "RWG linear ramp targets")?;
            let duration = required_duration_argument(1, "RWG linear ramp duration")?;
            let ramp_waveforms =
                values.rwg_waveforms(RwgWaveformDerivation::Linear, &[targets, duration]);
            let endpoint_waveforms =
                values.rwg_waveforms(RwgWaveformDerivation::RampEndpoint, &[ramp_waveforms]);
            let load_ramp = push_operation(plans, "catseq.hardware.rwg.load", vec![ramp_waveforms]);
            let start = push_operation(plans, "catseq.hardware.rwg.play", Vec::new());
            let wait = push_wait(plans, duration, WaitSemantics::PhysicalInterval);
            let load_endpoint =
                push_operation(plans, "catseq.hardware.rwg.load", vec![endpoint_waveforms]);
            let finish = push_operation(plans, "catseq.hardware.rwg.play", Vec::new());
            (
                vec![load_ramp, start, wait, load_endpoint, finish],
                vec![BoundaryPolicy::Auto; 4],
            )
        }
    };
    let root = TemplatePlanId(plans.len());
    plans.push(TemplatePlan {
        kind: TemplatePlanKind::Serial {
            children,
            boundaries,
        },
        provenance,
    });
    Ok(root)
}

fn nested_control_statements(hir: &TypedSourceHir) -> HashSet<u32> {
    let mut nested = HashSet::new();
    for node in hir.nodes() {
        let expression_count = match node.kind() {
            SourceHirKind::If | SourceHirKind::While => 1,
            SourceHirKind::Loop => 2,
            _ => continue,
        };
        let count = node.control_body_count() as usize + node.control_else_count() as usize;
        nested.extend(
            node_children(node, hir)
                .iter()
                .skip(expression_count)
                .take(count)
                .copied(),
        );
    }
    nested
}

fn source_for_descendants(hir: &TypedSourceHir) -> HashSet<u32> {
    let mut descendants = HashSet::new();
    for node in hir
        .nodes()
        .iter()
        .filter(|node| node.kind() == &SourceHirKind::Loop)
    {
        let mut pending = node_children(node, hir).to_vec();
        while let Some(descendant) = pending.pop() {
            if descendants.insert(descendant) {
                pending.extend_from_slice(node_children(&hir.nodes()[descendant as usize], hir));
            }
        }
    }
    descendants
}

fn lower_compile_if(
    node: &SourceHirNode,
    children: &[u32],
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    local_bindings: &mut HashMap<String, LoweredValue>,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let selected = selected_compile_if_statements(node, children, values)?;
    for statement in selected {
        apply_selected_statement(*statement, hir, values, local_bindings)?;
    }
    Ok(selected
        .iter()
        .rev()
        .find_map(|statement| values[*statement as usize].clone()))
}

fn selected_compile_if_statements<'a>(
    node: &SourceHirNode,
    children: &'a [u32],
    values: &[Option<LoweredValue>],
) -> Result<&'a [u32], MorphismLoweringError> {
    let condition = children
        .first()
        .and_then(|child| values[*child as usize].as_ref());
    let take_body = compile_if_take_body(node, condition)?;
    selected_control_statements(node, children, take_body)
}

fn compile_if_take_body(
    node: &SourceHirNode,
    condition: Option<&LoweredValue>,
) -> Result<bool, MorphismLoweringError> {
    let Some(condition) = condition else {
        return Err(lowering_error(
            node,
            "source if condition is not compile-time evaluable; hardware branches are not supported",
        ));
    };
    Ok(match condition {
        LoweredValue::Scalar(ScalarValue::Bool(value)) => *value,
        LoweredValue::Null => false,
        _ => {
            return Err(lowering_error(
                node,
                "source if condition is not a compile-time bool; hardware branches are not supported",
            ));
        }
    })
}

fn selected_control_statements<'a>(
    node: &SourceHirNode,
    children: &'a [u32],
    take_body: bool,
) -> Result<&'a [u32], MorphismLoweringError> {
    let body_start = 1;
    let body_end = body_start + node.control_body_count() as usize;
    let else_end = body_end + node.control_else_count() as usize;
    if else_end > children.len() {
        return Err(lowering_error(
            node,
            "invalid Source HIR control-flow shape",
        ));
    }
    Ok(if take_body {
        &children[body_start..body_end]
    } else {
        &children[body_end..else_end]
    })
}

fn apply_selected_statement(
    statement: u32,
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    local_bindings: &mut HashMap<String, LoweredValue>,
) -> Result<(), MorphismLoweringError> {
    match hir.nodes()[statement as usize].kind() {
        SourceHirKind::Assignment => bind_assignment(statement, hir, values, local_bindings),
        SourceHirKind::If => {
            let node = &hir.nodes()[statement as usize];
            let _ = lower_compile_if(node, node_children(node, hir), hir, values, local_bindings)?;
        }
        _ => {}
    }
    Ok(())
}

#[derive(Clone)]
enum SelectedPathScan {
    Normal,
    Return,
    SourceForError(MorphismLoweringError),
    NeedsCallSpecialization {
        node_id: u32,
        definition: Option<String>,
        arguments: Vec<SpecializationArgument>,
    },
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum SelectedExpressionMode {
    ScanSelectedPath,
    CompileValue,
}

struct SelectedPathScanner<'a> {
    hir: &'a TypedSourceHir,
    values: &'a [Option<LoweredValue>],
    state: &'a mut SelectedPathState,
    evaluator_values: ValueExprArenaBuilder,
    tolerate_lowering_errors: bool,
    clock_hz: u64,
}

struct ComprehensionClause {
    target: u32,
    iterable: u32,
    filters: Vec<u32>,
}

impl<'a> SelectedPathScanner<'a> {
    fn new(
        hir: &'a TypedSourceHir,
        values: &'a [Option<LoweredValue>],
        state: &'a mut SelectedPathState,
        tolerate_lowering_errors: bool,
        clock_hz: u64,
    ) -> Self {
        Self {
            hir,
            values,
            state,
            evaluator_values: ValueExprArenaBuilder::new(),
            tolerate_lowering_errors,
            clock_hz,
        }
    }

    fn scan_definition(&mut self) -> Result<SelectedPathScan, MorphismLoweringError> {
        let mut bindings = HashMap::new();
        self.scan_suite(self.hir.roots(), &mut bindings)
    }

    fn scan_suite(
        &mut self,
        statements: &[u32],
        bindings: &mut HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        for statement in statements {
            let kind = self.hir.nodes()[*statement as usize].kind();
            let scan = if kind == &SourceHirKind::If {
                match self.scan_if(*statement, bindings) {
                    Ok(scan) => scan,
                    Err(_) if self.tolerate_lowering_errors => SelectedPathScan::Normal,
                    Err(error) => return Err(error),
                }
            } else {
                self.scan_node(*statement, bindings)?
            };
            match scan {
                SelectedPathScan::Normal => {}
                completion => return Ok(completion),
            }
            if kind == &SourceHirKind::Assignment {
                self.bind_selected_assignment(*statement, bindings)?;
            }
        }
        Ok(SelectedPathScan::Normal)
    }

    fn scan_if(
        &mut self,
        node_id: u32,
        bindings: &mut HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        let hir = self.hir;
        let node = &hir.nodes()[node_id as usize];
        let children = node_children(node, hir).to_vec();
        let condition = children
            .first()
            .ok_or_else(|| lowering_error(node, "invalid Source HIR control-flow shape"))?;
        match self.scan_node(*condition, bindings)? {
            SelectedPathScan::Normal => {}
            completion => return Ok(completion),
        }
        let condition_value = self.compile_value(*condition, bindings)?;
        let take_body = compile_if_take_body(node, condition_value.as_ref())?;
        let selected = selected_control_statements(node, &children, take_body)?;
        self.scan_suite(selected, bindings)
    }

    fn bind_selected_assignment(
        &mut self,
        statement: u32,
        bindings: &mut HashMap<String, LoweredValue>,
    ) -> Result<(), MorphismLoweringError> {
        let hir = self.hir;
        let node = &hir.nodes()[statement as usize];
        let children = node_children(node, hir).to_vec();
        let Some(value_node) = children.last() else {
            return Ok(());
        };
        let value = match self.compile_value(*value_node, bindings) {
            Ok(Some(value)) => value,
            Ok(None) | Err(_) => return Ok(()),
        };
        for target in &children[..children.len().saturating_sub(1)] {
            let target_node = &hir.nodes()[*target as usize];
            if target_node.kind() == &SourceHirKind::Name
                && let Some(symbol) = target_node.symbol()
            {
                bindings.insert(symbol.to_owned(), value.clone());
            }
        }
        Ok(())
    }

    fn scan_node(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        if bindings.is_empty()
            && let Some(scan) = self.state.cache[node_id as usize].clone()
        {
            return Ok(scan);
        }
        let scan = match self.scan_node_uncached(node_id, bindings) {
            Ok(scan) => scan,
            // Source-for is represented by `SourceForError`, not `Err`, so a
            // tolerant probe can discard ordinary evaluator failures without
            // hiding a loop that another selected sibling reaches.
            Err(_) if self.tolerate_lowering_errors => SelectedPathScan::Normal,
            Err(error) => return Err(error),
        };
        if bindings.is_empty() && !matches!(scan, SelectedPathScan::NeedsCallSpecialization { .. })
        {
            self.state.cache[node_id as usize] = Some(scan.clone());
        }
        Ok(scan)
    }

    fn scan_node_uncached(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        let hir = self.hir;
        let node = &hir.nodes()[node_id as usize];
        if node.kind() == &SourceHirKind::Loop {
            return Ok(SelectedPathScan::SourceForError(
                source_for_specialization_error(node),
            ));
        }
        if node.kind() == &SourceHirKind::Lambda {
            return Ok(SelectedPathScan::Normal);
        }
        let children = node_children(node, hir).to_vec();
        if node.boolean_operation().is_some()
            || matches!(
                node.kind(),
                SourceHirKind::Compare | SourceHirKind::ConditionalExpression
            )
        {
            let (scan, _) = self.evaluate_selected_expression(
                node_id,
                bindings,
                SelectedExpressionMode::ScanSelectedPath,
            )?;
            return Ok(scan);
        }
        if node.kind() == &SourceHirKind::If {
            let mut selected_bindings = bindings.clone();
            return self.scan_if(node_id, &mut selected_bindings);
        }
        if node.kind() == &SourceHirKind::Comprehension {
            return self.scan_comprehension(node_id, node, &children, bindings);
        }
        if node.kind() == &SourceHirKind::Call
            && hir.facts()[node_id as usize].resolved_definition() == Some("functools.reduce")
        {
            return self.scan_reduce(node_id, &children, bindings);
        }
        for child in &children {
            match self.scan_node(*child, bindings)? {
                SelectedPathScan::Normal => {}
                completion => return Ok(completion),
            }
        }
        if node.kind() == &SourceHirKind::Call
            && !hir.facts()[node_id as usize]
                .resolved_definitions()
                .is_empty()
        {
            let arguments = collect_specialization_arguments(node, &children, |child| {
                self.compile_value(child, bindings)
            })?;
            let native_arguments = bindings.is_empty().then(|| {
                collect_specialization_arguments(node, &children, |child| {
                    Ok(self.values[child as usize].clone())
                })
            });
            let requires_selected_path_specialization = !bindings.is_empty()
                || native_arguments
                    .transpose()?
                    .as_ref()
                    .is_some_and(|native| native != &arguments);
            if requires_selected_path_specialization {
                if let Some(specialization) =
                    self.state.bound_calls[node_id as usize]
                        .iter()
                        .find(|specialization| {
                            specialization.definition.is_none()
                                && specialization.arguments == arguments
                        })
                {
                    return Ok(specialization
                        .selected_source_for_error
                        .as_ref()
                        .map_or(SelectedPathScan::Normal, |error| {
                            SelectedPathScan::SourceForError(error.clone())
                        }));
                } else {
                    return Ok(SelectedPathScan::NeedsCallSpecialization {
                        node_id,
                        definition: None,
                        arguments,
                    });
                }
            }
        }
        if let Some(error) = self.state.call_errors[node_id as usize].as_ref() {
            return Ok(SelectedPathScan::SourceForError(error.clone()));
        }
        if node.kind() == &SourceHirKind::Return {
            return Ok(SelectedPathScan::Return);
        }
        Ok(SelectedPathScan::Normal)
    }

    fn scan_comprehension(
        &mut self,
        node_id: u32,
        node: &SourceHirNode,
        children: &[u32],
        outer_bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        let element_count = node.comprehension_element_count() as usize;
        let Some(elements) = children.get(..element_count) else {
            return Err(lowering_error(node, "invalid comprehension element shape"));
        };
        let mut offset = element_count;
        let mut clauses = Vec::with_capacity(node.comprehension_filter_counts().len());
        for filter_count in node.comprehension_filter_counts() {
            let filter_count = *filter_count as usize;
            let Some(target) = children.get(offset).copied() else {
                return Err(lowering_error(node, "invalid comprehension target shape"));
            };
            let Some(iterable) = children.get(offset + 1).copied() else {
                return Err(lowering_error(node, "invalid comprehension iterable shape"));
            };
            let filter_start = offset + 2;
            let Some(filters) = children.get(filter_start..filter_start + filter_count) else {
                return Err(lowering_error(node, "invalid comprehension filter shape"));
            };
            clauses.push(ComprehensionClause {
                target,
                iterable,
                filters: filters.to_vec(),
            });
            offset = filter_start + filter_count;
        }
        if elements.is_empty() || clauses.is_empty() || offset != children.len() {
            return Err(lowering_error(node, "invalid comprehension shape"));
        }
        self.scan_comprehension_clause(node_id, node, elements, &clauses, 0, outer_bindings)
    }

    fn scan_comprehension_clause(
        &mut self,
        node_id: u32,
        node: &SourceHirNode,
        elements: &[u32],
        clauses: &[ComprehensionClause],
        clause_index: usize,
        outer_bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        let clause = &clauses[clause_index];
        match self.scan_node(clause.iterable, outer_bindings)? {
            SelectedPathScan::Normal => {}
            completion => return Ok(completion),
        }
        let items = match self.compile_value(clause.iterable, outer_bindings)? {
            Some(LoweredValue::Aggregate(items)) => Some(items),
            _ if clauses.len() == 1 => self.hir.facts()[node_id as usize]
                .comprehension_static_values()
                .and_then(|values| {
                    values
                        .iter()
                        .map(|value| lower_normalized_default(value, self.clock_hz))
                        .collect::<Option<Vec<_>>>()
                }),
            _ => None,
        };
        let Some(items) = items else {
            for filter in &clause.filters {
                match self.scan_node(*filter, outer_bindings)? {
                    SelectedPathScan::Normal => {}
                    completion => return Ok(completion),
                }
                if self.truthiness(*filter, outer_bindings)? == Some(false) {
                    return Ok(SelectedPathScan::Normal);
                }
            }
            return if clause_index + 1 < clauses.len() {
                self.scan_comprehension_clause(
                    node_id,
                    node,
                    elements,
                    clauses,
                    clause_index + 1,
                    outer_bindings,
                )
            } else {
                self.scan_comprehension_elements(elements, outer_bindings)
            };
        };
        for item in items {
            let mut bindings = outer_bindings.clone();
            bind_comprehension_target(clause.target, item, self.hir, &mut bindings, node)?;
            let mut accepted = true;
            for filter in &clause.filters {
                match self.scan_node(*filter, &bindings)? {
                    SelectedPathScan::Normal => {}
                    completion => return Ok(completion),
                }
                match self.truthiness(*filter, &bindings)? {
                    Some(value) => accepted &= value,
                    None => return Ok(SelectedPathScan::Normal),
                }
                if !accepted {
                    break;
                }
            }
            if accepted {
                let scan = if clause_index + 1 < clauses.len() {
                    self.scan_comprehension_clause(
                        node_id,
                        node,
                        elements,
                        clauses,
                        clause_index + 1,
                        &bindings,
                    )?
                } else {
                    self.scan_comprehension_elements(elements, &bindings)?
                };
                match scan {
                    SelectedPathScan::Normal => {}
                    completion => return Ok(completion),
                }
            }
        }
        Ok(SelectedPathScan::Normal)
    }

    fn scan_comprehension_elements(
        &mut self,
        elements: &[u32],
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        for element in elements {
            match self.scan_node(*element, bindings)? {
                SelectedPathScan::Normal => {}
                completion => return Ok(completion),
            }
        }
        Ok(SelectedPathScan::Normal)
    }

    fn scan_reduce(
        &mut self,
        node_id: u32,
        children: &[u32],
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<SelectedPathScan, MorphismLoweringError> {
        let callable = children.get(1).copied();
        let selected_callable = match callable {
            Some(callable) => self.selected_callable_node(callable, bindings)?,
            None => None,
        };
        let lambda = selected_callable.filter(|callable| {
            self.hir.nodes()[*callable as usize].kind() == &SourceHirKind::Lambda
        });
        let named_callback = selected_callable.and_then(|callable| {
            self.hir.facts()[callable as usize]
                .resolved_definition()
                .map(|definition| (callable, definition.to_owned()))
        });
        for child in children {
            match self.scan_node(*child, bindings)? {
                SelectedPathScan::Normal => {}
                completion => return Ok(completion),
            }
        }
        let node = &self.hir.nodes()[node_id as usize];
        let aggregate_node = call_argument_node(node, children, 1, "iterable");
        let initializer_node = call_argument_node(node, children, 2, "initial");
        let aggregate = match aggregate_node {
            Some(aggregate) => self.compile_value(aggregate, bindings)?,
            None => None,
        };
        let initializer = match initializer_node {
            Some(initializer) => self.compile_value(initializer, bindings)?,
            None => None,
        };
        if let Some(LoweredValue::Aggregate(items)) = aggregate {
            let lambda_body = lambda.and_then(|lambda| {
                node_children(&self.hir.nodes()[lambda as usize], self.hir)
                    .first()
                    .copied()
            });
            let lambda_parameters = lambda
                .map(|lambda| {
                    self.hir.nodes()[lambda as usize]
                        .lambda_parameter_names()
                        .to_vec()
                })
                .unwrap_or_default();
            let mut items = items.into_iter();
            let mut accumulator = if initializer_node.is_some() {
                initializer
            } else {
                items.next()
            };
            if accumulator.is_none() && initializer_node.is_some() && items.len() > 0 {
                if let Some(body) = lambda_body {
                    match self.scan_node(body, bindings)? {
                        SelectedPathScan::Normal => {}
                        completion => return Ok(completion),
                    }
                }
            }
            while let (Some(left), Some(right)) = (accumulator.clone(), items.next()) {
                if let Some(body) = lambda_body {
                    let mut lambda_bindings = bindings.clone();
                    if let Some(parameter) = lambda_parameters.first() {
                        lambda_bindings.insert(parameter.clone(), left);
                    }
                    if let Some(parameter) = lambda_parameters.get(1) {
                        lambda_bindings.insert(parameter.clone(), right.clone());
                    }
                    match self.scan_node(body, &lambda_bindings)? {
                        SelectedPathScan::Normal => {}
                        completion => return Ok(completion),
                    }
                    accumulator = self.compile_value(body, &lambda_bindings)?.or(Some(right));
                } else if let Some((callable, definition)) = named_callback.as_ref() {
                    let arguments = vec![
                        SpecializationArgument {
                            target: SpecializationArgumentTarget::Position(0),
                            value: left,
                        },
                        SpecializationArgument {
                            target: SpecializationArgumentTarget::Position(1),
                            value: right.clone(),
                        },
                    ];
                    if let Some(specialization) = self.state.bound_calls[*callable as usize]
                        .iter()
                        .find(|specialization| {
                            specialization.definition.as_deref() == Some(definition.as_str())
                                && specialization.arguments == arguments
                        })
                    {
                        if let Some(error) = specialization.selected_source_for_error.as_ref() {
                            return Ok(SelectedPathScan::SourceForError(error.clone()));
                        }
                    } else {
                        return Ok(SelectedPathScan::NeedsCallSpecialization {
                            node_id: *callable,
                            definition: Some(definition.clone()),
                            arguments,
                        });
                    }
                    accumulator = Some(right);
                }
            }
        }
        if let Some(error) = self.state.call_errors[node_id as usize].as_ref() {
            return Ok(SelectedPathScan::SourceForError(error.clone()));
        }
        Ok(SelectedPathScan::Normal)
    }

    fn selected_callable_node(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<Option<u32>, MorphismLoweringError> {
        let mut current = node_id;
        let mut visited = HashSet::new();
        while visited.insert(current) {
            if let Some(resolved) = self.hir.facts()[current as usize].resolved_node() {
                current = resolved;
                continue;
            }
            let node = &self.hir.nodes()[current as usize];
            if node.kind() == &SourceHirKind::ConditionalExpression {
                let children = node_children(node, self.hir);
                let Some(condition) = children.first() else {
                    return Ok(None);
                };
                let selected = match self.truthiness(*condition, bindings)? {
                    Some(true) => children.get(1).copied(),
                    Some(false) => children.get(2).copied(),
                    None => None,
                };
                let Some(selected) = selected else {
                    return Ok(None);
                };
                current = selected;
                continue;
            }
            return Ok(Some(current));
        }
        Ok(None)
    }

    fn truthiness(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<Option<bool>, MorphismLoweringError> {
        if bindings.is_empty()
            && let Some(cached) = self.state.truthiness_cache[node_id as usize]
        {
            return Ok(match cached {
                CachedTruthiness::Known(value) => Some(value),
                CachedTruthiness::Unknown => None,
            });
        }
        let truthiness = self
            .compile_value(node_id, bindings)?
            .as_ref()
            .and_then(lowered_truthiness);
        if bindings.is_empty() {
            self.state.truthiness_cache[node_id as usize] = Some(match truthiness {
                Some(value) => CachedTruthiness::Known(value),
                None => CachedTruthiness::Unknown,
            });
        }
        Ok(truthiness)
    }

    fn compile_value(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<Option<LoweredValue>, MorphismLoweringError> {
        let node = &self.hir.nodes()[node_id as usize];
        if node.boolean_operation().is_some()
            || matches!(
                node.kind(),
                SourceHirKind::Compare | SourceHirKind::ConditionalExpression
            )
        {
            let (_, value) = self.evaluate_selected_expression(
                node_id,
                bindings,
                SelectedExpressionMode::CompileValue,
            )?;
            return Ok(value);
        }
        if bindings.is_empty() {
            return Ok(self.values[node_id as usize].clone());
        }
        self.evaluate(node_id, bindings)
    }

    fn evaluate_selected_expression(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
        mode: SelectedExpressionMode,
    ) -> Result<(SelectedPathScan, Option<LoweredValue>), MorphismLoweringError> {
        let node = &self.hir.nodes()[node_id as usize];
        let children = node_children(node, self.hir).to_vec();
        if let Some(operation) = node.boolean_operation() {
            let mut result = None;
            for child in children {
                let (scan, value) = self.selected_expression_child(child, bindings, mode)?;
                if !matches!(scan, SelectedPathScan::Normal) {
                    return Ok((scan, None));
                }
                let Some(value) = value.as_ref().and_then(lowered_truthiness) else {
                    result = None;
                    if mode == SelectedExpressionMode::CompileValue {
                        break;
                    }
                    continue;
                };
                result = Some(value);
                if matches!(
                    (operation, value),
                    (BooleanOperation::And, false) | (BooleanOperation::Or, true)
                ) {
                    break;
                }
            }
            let value = (mode == SelectedExpressionMode::CompileValue)
                .then(|| result.map(|value| LoweredValue::Scalar(ScalarValue::Bool(value))))
                .flatten();
            return Ok((SelectedPathScan::Normal, value));
        }
        if node.kind() == &SourceHirKind::Compare {
            if node.comparison_operations().len() + 1 != children.len() {
                return Err(lowering_error(node, "invalid comparison operand shape"));
            }
            let Some(first) = children.first() else {
                return Ok((SelectedPathScan::Normal, None));
            };
            let (scan, mut left) = self.selected_expression_child(*first, bindings, mode)?;
            let mut left_node = *first;
            if !matches!(scan, SelectedPathScan::Normal) {
                return Ok((scan, None));
            }
            if mode == SelectedExpressionMode::CompileValue && left.is_none() {
                return Ok((SelectedPathScan::Normal, None));
            }
            for (operation, right_node) in node
                .comparison_operations()
                .iter()
                .zip(children.iter().skip(1))
            {
                let (scan, right) = self.selected_expression_child(*right_node, bindings, mode)?;
                if !matches!(scan, SelectedPathScan::Normal) {
                    return Ok((scan, None));
                }
                let comparison = match left.as_ref().zip(right.as_ref()) {
                    Some((left, right)) => match self.compare_selected_values(
                        *operation,
                        left_node,
                        *right_node,
                        left,
                        right,
                    ) {
                        Some(comparison) => Some(comparison),
                        None if mode == SelectedExpressionMode::CompileValue => {
                            return Err(lowering_error(
                                node,
                                "comparison is not compile-time evaluable",
                            ));
                        }
                        None => None,
                    },
                    None => None,
                };
                if comparison == Some(false) {
                    let value = (mode == SelectedExpressionMode::CompileValue)
                        .then_some(LoweredValue::Scalar(ScalarValue::Bool(false)));
                    return Ok((SelectedPathScan::Normal, value));
                }
                if mode == SelectedExpressionMode::CompileValue && comparison.is_none() {
                    return Ok((SelectedPathScan::Normal, None));
                }
                left = right;
                left_node = *right_node;
            }
            let value = (mode == SelectedExpressionMode::CompileValue)
                .then_some(LoweredValue::Scalar(ScalarValue::Bool(true)));
            return Ok((SelectedPathScan::Normal, value));
        }
        if node.kind() == &SourceHirKind::ConditionalExpression {
            let Some(condition) = children.first() else {
                return Ok((SelectedPathScan::Normal, None));
            };
            let (scan, condition) = self.selected_expression_child(*condition, bindings, mode)?;
            if !matches!(scan, SelectedPathScan::Normal) {
                return Ok((scan, None));
            }
            let selected = match condition.as_ref().and_then(lowered_truthiness) {
                Some(true) => children.get(1),
                Some(false) => children.get(2),
                None => None,
            };
            let Some(selected) = selected else {
                return Ok((SelectedPathScan::Normal, None));
            };
            return if mode == SelectedExpressionMode::ScanSelectedPath {
                Ok((self.scan_node(*selected, bindings)?, None))
            } else {
                Ok((
                    SelectedPathScan::Normal,
                    self.compile_value(*selected, bindings)?,
                ))
            };
        }
        unreachable!("selected expression evaluator requires a control expression")
    }

    fn compare_selected_values(
        &self,
        operation: ComparisonOperation,
        left_node: u32,
        right_node: u32,
        left: &LoweredValue,
        right: &LoweredValue,
    ) -> Option<bool> {
        let identical = || match (left, right) {
            (LoweredValue::Null, LoweredValue::Null) => true,
            (LoweredValue::Instance(left), LoweredValue::Instance(right)) => left == right,
            (
                LoweredValue::Scalar(ScalarValue::Bool(left)),
                LoweredValue::Scalar(ScalarValue::Bool(right)),
            ) => left == right,
            (LoweredValue::Null, _)
            | (_, LoweredValue::Null)
            | (LoweredValue::Instance(_), _)
            | (_, LoweredValue::Instance(_)) => false,
            _ => self.resolved_value_node(left_node) == self.resolved_value_node(right_node),
        };
        match operation {
            ComparisonOperation::Is => Some(identical()),
            ComparisonOperation::IsNot => Some(!identical()),
            _ => compare_lowered_values(operation, left, right),
        }
    }

    fn resolved_value_node(&self, node_id: u32) -> u32 {
        let mut current = node_id;
        let mut visited = HashSet::new();
        while visited.insert(current) {
            let Some(resolved) = self.hir.facts()[current as usize].resolved_node() else {
                break;
            };
            current = resolved;
        }
        current
    }

    fn selected_expression_child(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
        mode: SelectedExpressionMode,
    ) -> Result<(SelectedPathScan, Option<LoweredValue>), MorphismLoweringError> {
        if mode == SelectedExpressionMode::ScanSelectedPath {
            let scan = self.scan_node(node_id, bindings)?;
            if !matches!(scan, SelectedPathScan::Normal) {
                return Ok((scan, None));
            }
        }
        Ok((
            SelectedPathScan::Normal,
            self.compile_value(node_id, bindings)?,
        ))
    }

    fn evaluate(
        &mut self,
        node_id: u32,
        bindings: &HashMap<String, LoweredValue>,
    ) -> Result<Option<LoweredValue>, MorphismLoweringError> {
        eval_compile_expression(
            node_id,
            self.hir,
            self.values,
            bindings,
            &mut self.evaluator_values,
        )
    }
}

fn lowered_truthiness(value: &LoweredValue) -> Option<bool> {
    match value {
        LoweredValue::Null => Some(false),
        LoweredValue::Instance(_) | LoweredValue::Morphism(_) | LoweredValue::Template(_) => {
            Some(true)
        }
        LoweredValue::ChannelBindings(bindings) => Some(!bindings.is_empty()),
        LoweredValue::Aggregate(values) => Some(!values.is_empty()),
        LoweredValue::Json(value) => match value {
            serde_json::Value::Null => Some(false),
            serde_json::Value::Bool(value) => Some(*value),
            serde_json::Value::Number(value) => value
                .as_i64()
                .map(|value| value != 0)
                .or_else(|| value.as_u64().map(|value| value != 0))
                .or_else(|| value.as_f64().map(|value| value != 0.0)),
            serde_json::Value::String(value) => Some(!value.is_empty()),
            serde_json::Value::Array(values) => Some(!values.is_empty()),
            serde_json::Value::Object(values) => Some(!values.is_empty()),
        },
        LoweredValue::Scalar(ScalarValue::Bool(value)) => Some(*value),
        LoweredValue::Scalar(ScalarValue::Int(value)) => Some(*value != 0),
        LoweredValue::Scalar(ScalarValue::Float(value))
        | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => {
            Some(*value != ExactDecimal::from_i64(0))
        }
        LoweredValue::Scalar(ScalarValue::String(value)) => Some(!value.is_empty()),
        LoweredValue::Scalar(ScalarValue::Expr(_)) => None,
    }
}

fn source_for_specialization_error(node: &SourceHirNode) -> MorphismLoweringError {
    lowering_error(node, "ordinary for specialization is not implemented yet")
}

fn bind_assignment(
    statement: u32,
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    local_bindings: &mut HashMap<String, LoweredValue>,
) {
    let node = &hir.nodes()[statement as usize];
    let children = node_children(node, hir);
    let Some(value) = children
        .last()
        .and_then(|child| values[*child as usize].clone())
    else {
        return;
    };
    for target in &children[..children.len().saturating_sub(1)] {
        let target_node = &hir.nodes()[*target as usize];
        if target_node.kind() == &SourceHirKind::Name
            && let Some(symbol) = target_node.symbol()
        {
            local_bindings.insert(symbol.to_owned(), value.clone());
        }
    }
}

fn node_children<'a>(node: &SourceHirNode, hir: &'a TypedSourceHir) -> &'a [u32] {
    let start = node.edge_start() as usize;
    &hir.edges()[start..start + node.edge_count() as usize]
}

fn native_channel_key(hir: &TypedSourceHir, node_id: u32) -> String {
    let node = &hir.nodes()[node_id as usize];
    if let Some(definition) = hir.facts()[node_id as usize].resolved_definition() {
        return definition.to_owned();
    }
    format!(
        "{}::{}",
        node.anchor().module(),
        node.symbol().unwrap_or("channel")
    )
}

fn default_instance_identity(definition: &TypedDefinition) -> String {
    let owner = definition
        .qualified_name()
        .rsplit_once('.')
        .map_or(definition.qualified_name(), |(owner, _)| owner);
    qualify_source_identity(definition.module(), owner)
}

fn call_instance_identity(
    call: &SourceHirNode,
    current_instance: &str,
    callee: &TypedDefinition,
) -> String {
    let Some((receiver, _method)) = call.symbol().and_then(|path| path.rsplit_once('.')) else {
        return default_instance_identity(callee);
    };
    if receiver == "self" {
        return current_instance.to_owned();
    }
    qualify_source_identity(call.anchor().module(), receiver)
}

fn environment_slot_name(node: &SourceHirNode, instance_identity: &str) -> String {
    let field = node
        .symbol()
        .and_then(|symbol| symbol.strip_prefix("self."))
        .unwrap_or("environment_value");
    format!("{instance_identity}.{field}")
}

fn qualify_source_identity(module: &str, identity: &str) -> String {
    if identity == module
        || identity
            .strip_prefix(module)
            .is_some_and(|suffix| suffix.starts_with('.'))
    {
        identity.to_owned()
    } else {
        format!("{module}.{identity}")
    }
}

fn is_repeat_morphism(resolved: &str) -> bool {
    resolved == "catseq.morphism.repeat_morphism"
}

fn lower_repeat_call(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
    builder: &mut MorphismArenaBuilder,
    value_builder: &mut ValueExprArenaBuilder,
    provenance: ProvenanceId,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let body = children
        .iter()
        .skip(1)
        .find_map(|child| match values[*child as usize].clone() {
            Some(LoweredValue::Morphism(body)) => Some(body),
            _ => None,
        });
    let count = children
        .iter()
        .skip(1)
        .find_map(|child| match values[*child as usize].clone() {
            Some(LoweredValue::Scalar(value)) => Some(value),
            _ => None,
        });
    match (body, count) {
        (Some(body), Some(ScalarValue::Int(count))) if count > 0 => {
            let count = scalar_to_expr(ScalarValue::Int(count), value_builder, node)?;
            Ok(Some(LoweredValue::Morphism(
                builder.loop_region(body, count, provenance),
            )))
        }
        _ => Err(lowering_error(
            node,
            "repeat_morphism requires a native body and compile-time positive integer count",
        )),
    }
}

fn lowering_error(node: &SourceHirNode, message: impl Display) -> MorphismLoweringError {
    MorphismLoweringError::new(format!(
        "{}:{}:{}: {message}",
        node.anchor().module(),
        node.anchor().line(),
        node.anchor().column()
    ))
}
