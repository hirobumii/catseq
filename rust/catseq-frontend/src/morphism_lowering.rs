//! Direct Typed Source HIR to canonical Morphism arena lowering.

use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::morphism_arena::{
    BoundaryPolicy, MorphismArenaBuilder, MorphismNodeId, MorphismTemplateId, NativeProvenance,
    ProvenanceId,
};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{
    ValueExprArenaBuilder, ValueExprId, ValueExprKind, ValueExprPayload, ValueExprType,
};

use crate::{
    ComparisonOperation, MorphismComposition, SourceHirKind, SourceHirNode, SourceLiteral,
    SourceType, TypedCheckReport, TypedDefinition, TypedSourceHir, ValueAvailability,
    ValueOperation,
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

#[derive(Clone)]
enum LoweredValue {
    Null,
    Morphism(MorphismNodeId),
    Template(TemplatePlanId),
    ChannelBindings(Vec<ChannelBinding>),
    Aggregate(Vec<LoweredValue>),
    Json(serde_json::Value),
    Scalar(ScalarValue),
}

#[derive(Clone)]
enum ScalarValue {
    Bool(bool),
    Int(i64),
    Float(ExactDecimal),
    DurationCycles(ExactDecimal),
    String(String),
    Expr(ValueExprId),
}

#[derive(Clone)]
struct ChannelBinding {
    channel: String,
    template: TemplatePlanId,
}

#[derive(Clone)]
struct SpecializationArgument {
    name: Option<String>,
    value: LoweredValue,
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
    let root = match lowerer.lower_definition(entry, &[])? {
        LoweredValue::Morphism(root) => root,
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

struct SpecializationLowerer<'a> {
    definitions: HashMap<&'a str, &'a TypedDefinition>,
    clock_hz: u64,
    builder: MorphismArenaBuilder,
    value_builder: ValueExprArenaBuilder,
    template_plans: Vec<TemplatePlan>,
    published_templates: Vec<Option<MorphismTemplateId>>,
    active_definitions: Vec<&'a str>,
    compile_fields: HashMap<String, String>,
}

impl<'a> SpecializationLowerer<'a> {
    fn new(definitions: HashMap<&'a str, &'a TypedDefinition>, clock_hz: u64) -> Self {
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
        }
    }

    fn lower_definition(
        &mut self,
        definition: &'a TypedDefinition,
        arguments: &[SpecializationArgument],
    ) -> Result<LoweredValue, MorphismLoweringError> {
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
        let result = self.lower_definition_body(definition, arguments);
        self.active_definitions.pop();
        result
    }

    fn lower_definition_body(
        &mut self,
        definition: &'a TypedDefinition,
        arguments: &[SpecializationArgument],
    ) -> Result<LoweredValue, MorphismLoweringError> {
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
        let positional = arguments
            .iter()
            .filter(|argument| argument.name.is_none())
            .collect::<Vec<_>>();
        for (index, parameter) in parameters.into_iter().enumerate() {
            let value = positional
                .get(index)
                .map(|argument| argument.value.clone())
                .or_else(|| {
                    arguments
                        .iter()
                        .find(|argument| argument.name.as_deref() == Some(parameter.name()))
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
        let mut values = vec![None::<LoweredValue>; hir.nodes().len()];
        let nested_statements = nested_control_statements(hir);
        let mut local_bindings = HashMap::<String, LoweredValue>::new();
        for node_id in 0..hir.nodes().len() {
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
            let lowered = match node.kind() {
                SourceHirKind::Constant => lower_literal(node)?,
                SourceHirKind::Name if source_type == Some(&SourceType::Duration) => {
                    lower_duration_unit(node, self.clock_hz)
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
                    )?
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
                    )?
                }
                SourceHirKind::Attribute
                    if matches!(source_type, Some(SourceType::NativeRecord(_)))
                        && fact.compile_value().is_some() =>
                {
                    Some(LoweredValue::Json(normalized_to_json(
                        fact.compile_value().expect("checked above"),
                        &self.compile_fields,
                    )?))
                }
                SourceHirKind::Attribute if node.symbol() == Some("np.pi") => {
                    Some(LoweredValue::Scalar(ScalarValue::Float(
                        ExactDecimal::from_f64_shortest(std::f64::consts::PI)
                            .expect("PI is finite"),
                    )))
                }
                SourceHirKind::Subscript if fact.availability() == ValueAvailability::Link => {
                    let slot = children
                        .get(1)
                        .and_then(|child| hir.nodes()[*child as usize].symbol())
                        .unwrap_or("scan_value");
                    let value_type = source_type_to_value_type(source_type).ok_or_else(|| {
                        lowering_error(node, "link-time value has no native scalar type")
                    })?;
                    Some(LoweredValue::Scalar(ScalarValue::Expr(
                        self.value_builder.runtime_slot(slot, value_type),
                    )))
                }
                SourceHirKind::Binary | SourceHirKind::Unary
                    if node.value_operation().is_some() =>
                {
                    lower_aggregate_operation(node, children, &values).or(lower_value_operation(
                        node,
                        children,
                        &values,
                        source_type,
                        &mut self.value_builder,
                    )?)
                }
                SourceHirKind::Call
                    if fact
                        .resolved_definitions()
                        .iter()
                        .any(|resolved| self.definitions.contains_key(resolved.as_str())) =>
                {
                    let arguments = children
                        .iter()
                        .skip(1)
                        .enumerate()
                        .filter_map(|(index, child)| {
                            let value = values[*child as usize].clone()?;
                            let name =
                                (index >= node.call_positional_count() as usize).then(|| {
                                    node.call_keyword_names()
                                        [index - node.call_positional_count() as usize]
                                        .clone()
                                });
                            Some(SpecializationArgument { name, value })
                        })
                        .collect::<Vec<_>>();
                    let mut specializations = Vec::new();
                    for resolved in fact.resolved_definitions() {
                        if let Some(callee) = self.definitions.get(resolved.as_str()).copied() {
                            specializations.push(self.lower_definition(callee, &arguments)?);
                        }
                    }
                    match specializations.len() {
                        0 => None,
                        1 => specializations.pop(),
                        _ => Some(LoweredValue::Aggregate(specializations)),
                    }
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
                        .transpose()?
                }
                SourceHirKind::Call
                    if fact.resolved_definition() == Some("catseq.control.repeat_morphism") =>
                {
                    let body = children.iter().skip(1).find_map(|child| {
                        match values[*child as usize].clone() {
                            Some(LoweredValue::Morphism(body)) => Some(body),
                            _ => None,
                        }
                    });
                    let count = children.iter().skip(1).find_map(|child| {
                        match values[*child as usize].clone() {
                            Some(LoweredValue::Scalar(value)) => Some(value),
                            _ => None,
                        }
                    });
                    match (body, count) {
                        (Some(body), Some(count)) => {
                            let count = scalar_to_expr(count, &mut self.value_builder, node)?;
                            Some(LoweredValue::Morphism(self.builder.loop_region(
                                body,
                                count,
                                provenance[node_id],
                            )))
                        }
                        _ => {
                            return Err(lowering_error(
                                node,
                                "repeat_morphism requires a native body and compile-time count",
                            ));
                        }
                    }
                }
                SourceHirKind::Call if matches!(source_type, Some(SourceType::NativeRecord(_))) => {
                    lower_native_record_call(node, children, fact, &values)?
                }
                SourceHirKind::Call if source_type == Some(&SourceType::FixedAggregate) => {
                    lower_aggregate_intrinsic(node, children, fact, &values)?
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
                    )?
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
                )?,
                SourceHirKind::Dictionary => lower_dictionary(children, hir, &values)?,
                SourceHirKind::Aggregate => children
                    .iter()
                    .map(|child| values[*child as usize].clone())
                    .collect::<Option<Vec<_>>>()
                    .map(LoweredValue::Aggregate),
                SourceHirKind::Comprehension => {
                    self.lower_comprehension(node, children, hir, &values)?
                }
                SourceHirKind::Compare => lower_compile_compare(node, children, &values)?,
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
                    selected.and_then(|child| values[*child as usize].clone())
                }
                SourceHirKind::If => {
                    lower_compile_if(node, children, hir, &values, &mut local_bindings)?
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
            if node.kind() == &SourceHirKind::Assignment
                && !nested_statements.contains(&(node_id as u32))
            {
                bind_assignment(node_id as u32, hir, &values, &mut local_bindings);
            }
        }
        hir.roots()
            .iter()
            .rev()
            .find_map(|root| values[*root as usize].clone())
            .ok_or_else(|| {
                MorphismLoweringError::new(format!(
                    "{} does not produce a native specialization value",
                    definition.qualified_name()
                ))
            })
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

    fn lower_comprehension(
        &mut self,
        node: &SourceHirNode,
        children: &[u32],
        hir: &TypedSourceHir,
        values: &[Option<LoweredValue>],
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
            return Ok(match values[*element as usize].clone() {
                Some(value @ LoweredValue::Aggregate(_)) => Some(value),
                _ => None,
            });
        };
        let mut result = Vec::with_capacity(items.len());
        for item in items {
            let mut bindings = HashMap::new();
            bind_comprehension_target(*target, item, hir, &mut bindings, node)?;
            let mut accepted = true;
            for filter in filters {
                match self.eval_compile_expression(*filter, hir, values, &bindings)? {
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
                let value = self
                    .eval_compile_expression(*element, hir, values, &bindings)?
                    .ok_or_else(|| {
                        lowering_error(node, "comprehension element is not compile-time evaluable")
                    })?;
                result.push(value);
            }
        }
        Ok(Some(LoweredValue::Aggregate(result)))
    }

    fn eval_compile_expression(
        &mut self,
        node_id: u32,
        hir: &TypedSourceHir,
        values: &[Option<LoweredValue>],
        bindings: &HashMap<String, LoweredValue>,
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
                self.eval_compile_expression(*child, hir, values, bindings)?;
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
                    lower_value_operation(
                        node,
                        children,
                        &evaluated,
                        source_type,
                        &mut self.value_builder,
                    )?,
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
            SourceHirKind::Call if matches!(source_type, Some(SourceType::NativeRecord(_))) => {
                lower_native_record_call(node, children, fact, &evaluated)?
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
                )?
            }
            SourceHirKind::Subscript => lower_static_subscript(children, &evaluated),
            SourceHirKind::Compare => lower_compile_compare(node, children, &evaluated)?,
            SourceHirKind::Comprehension => {
                self.lower_comprehension(node, children, hir, &evaluated)?
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
            SourceHirKind::Name if source_type == Some(&SourceType::Duration) => {
                lower_duration_unit(node, clock_hz)
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
            SourceHirKind::Dictionary => lower_dictionary(children, hir, &values)?,
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
            let id = TemplatePlanId(template_plans.len());
            template_plans.push(TemplatePlan {
                kind: TemplatePlanKind::Operation {
                    operation: resolved.to_owned(),
                    arguments,
                },
                provenance,
            });
            Ok(Some(LoweredValue::Template(id)))
        }
        SourceType::Morphism if is_identity(resolved) => {
            let duration = call_arguments(children, values, value_builder, node)?
                .first()
                .copied()
                .ok_or_else(|| lowering_error(node, "identity requires a duration"))?;
            Ok(Some(LoweredValue::Morphism(
                builder.wait(duration, provenance),
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
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let half = children.len() / 2;
    let mut bindings = Vec::with_capacity(half);
    for (channel, template) in children[..half].iter().zip(&children[half..]) {
        let template = match values[*template as usize].clone() {
            Some(LoweredValue::Template(template)) => template,
            _ => {
                return Err(lowering_error(
                    &hir.nodes()[*template as usize],
                    "channel binding value is not a MorphismTemplate",
                ));
            }
        };
        bindings.push(ChannelBinding {
            channel: native_channel_key(hir, *channel),
            template,
        });
    }
    Ok(Some(LoweredValue::ChannelBindings(bindings)))
}

fn lower_native_record_call(
    node: &SourceHirNode,
    children: &[u32],
    fact: &crate::SemanticFact,
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let resolved = fact.resolved_definition().unwrap_or_default();
    if resolved == "numpy.load" || resolved.ends_with(".np.load") {
        return Ok(Some(LoweredValue::Json(serde_json::Value::Null)));
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
    if resolved == "dataclasses.replace" {
        let Some((_, LoweredValue::Json(serde_json::Value::Object(mut record)))) =
            arguments.first().cloned()
        else {
            return Ok(None);
        };
        for (name, value) in arguments.into_iter().skip(1) {
            let Some(name) = name else {
                return Err(lowering_error(node, "replace fields must be named"));
            };
            record.insert(name, lowered_to_json(&value)?);
        }
        return Ok(Some(LoweredValue::Json(serde_json::Value::Object(record))));
    }
    let schema = match fact.source_type() {
        Some(SourceType::NativeRecord(schema)) => schema.as_str(),
        _ => resolved.rsplit('.').next().unwrap_or("NativeRecord"),
    };
    let field_names: &[&str] = match schema {
        "StaticWaveform" => &["freq", "amp", "sbg_id", "phase", "fct"],
        "RSPPIDConfig" => &[
            "adc_in",
            "rf_out",
            "dgt_source",
            "setpoint",
            "kp",
            "ki",
            "kd",
            "output_max",
        ],
        "RSPWaveformParams" => &["rf_out", "amp", "output_max"],
        _ => return Ok(None),
    };
    let mut record = serde_json::Map::new();
    record.insert(
        "$type".to_owned(),
        serde_json::Value::String(schema.to_owned()),
    );
    for (position, (name, value)) in arguments.into_iter().enumerate() {
        let name = name.unwrap_or_else(|| {
            field_names
                .get(position)
                .copied()
                .unwrap_or("value")
                .to_owned()
        });
        record.insert(name, lowered_to_json(&value)?);
    }
    match schema {
        "StaticWaveform" => {
            record.entry("freq").or_insert(serde_json::Value::Null);
            record.entry("amp").or_insert(serde_json::Value::Null);
            record.entry("sbg_id").or_insert(serde_json::Value::Null);
            record
                .entry("phase")
                .or_insert(serde_json::Value::from(0.0));
            record.entry("fct").or_insert(serde_json::Value::Null);
        }
        "RSPWaveformParams" => {
            record
                .entry("output_max")
                .or_insert(serde_json::Value::from(0.01));
        }
        _ => {}
    }
    Ok(Some(LoweredValue::Json(serde_json::Value::Object(record))))
}

fn lower_aggregate_operation(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Option<LoweredValue> {
    let [left, right] = children else {
        return None;
    };
    match (
        node.value_operation(),
        values[*left as usize].clone(),
        values[*right as usize].clone(),
    ) {
        (
            Some(ValueOperation::Add),
            Some(LoweredValue::Aggregate(mut left)),
            Some(LoweredValue::Aggregate(right)),
        ) => {
            left.extend(right);
            Some(LoweredValue::Aggregate(left))
        }
        _ => None,
    }
}

fn lower_compile_compare(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    if node.comparison_operations().len() + 1 != children.len() {
        return Err(lowering_error(node, "invalid comparison operand shape"));
    }
    let operands = children
        .iter()
        .map(|child| values[*child as usize].as_ref())
        .collect::<Option<Vec<_>>>();
    let Some(operands) = operands else {
        return Ok(None);
    };
    let mut result = true;
    for (index, operation) in node.comparison_operations().iter().enumerate() {
        result &= compare_lowered_values(*operation, operands[index], operands[index + 1])
            .ok_or_else(|| lowering_error(node, "comparison is not compile-time evaluable"))?;
        if !result {
            break;
        }
    }
    Ok(Some(LoweredValue::Scalar(ScalarValue::Bool(result))))
}

fn compare_lowered_values(
    operation: ComparisonOperation,
    left: &LoweredValue,
    right: &LoweredValue,
) -> Option<bool> {
    use std::cmp::Ordering;

    let equality = || lowered_values_equal(left, right);
    match operation {
        ComparisonOperation::Equal | ComparisonOperation::Is => equality(),
        ComparisonOperation::NotEqual | ComparisonOperation::IsNot => equality().map(|v| !v),
        ComparisonOperation::Less
        | ComparisonOperation::LessEqual
        | ComparisonOperation::Greater
        | ComparisonOperation::GreaterEqual => {
            let ordering = numeric_scalar(left)?.checked_cmp(numeric_scalar(right)?)?;
            Some(match operation {
                ComparisonOperation::Less => ordering == Ordering::Less,
                ComparisonOperation::LessEqual => ordering != Ordering::Greater,
                ComparisonOperation::Greater => ordering == Ordering::Greater,
                ComparisonOperation::GreaterEqual => ordering != Ordering::Less,
                _ => unreachable!(),
            })
        }
        ComparisonOperation::In | ComparisonOperation::NotIn => {
            let contains = match right {
                LoweredValue::Aggregate(values) => values
                    .iter()
                    .map(|value| lowered_values_equal(left, value))
                    .collect::<Option<Vec<_>>>()?
                    .into_iter()
                    .any(|equal| equal),
                LoweredValue::Scalar(ScalarValue::String(haystack)) => match left {
                    LoweredValue::Scalar(ScalarValue::String(needle)) => haystack.contains(needle),
                    _ => return None,
                },
                _ => return None,
            };
            Some(if operation == ComparisonOperation::In {
                contains
            } else {
                !contains
            })
        }
    }
}

fn lowered_values_equal(left: &LoweredValue, right: &LoweredValue) -> Option<bool> {
    match (left, right) {
        (LoweredValue::Null, LoweredValue::Null) => Some(true),
        (LoweredValue::Null, _) | (_, LoweredValue::Null) => Some(false),
        (
            LoweredValue::Scalar(ScalarValue::Bool(left)),
            LoweredValue::Scalar(ScalarValue::Bool(right)),
        ) => Some(left == right),
        (
            LoweredValue::Scalar(ScalarValue::String(left)),
            LoweredValue::Scalar(ScalarValue::String(right)),
        ) => Some(left == right),
        (LoweredValue::Scalar(_), LoweredValue::Scalar(_)) => Some(
            numeric_scalar(left)?
                .checked_cmp(numeric_scalar(right)?)?
                .is_eq(),
        ),
        (LoweredValue::Json(left), LoweredValue::Json(right)) => Some(left == right),
        (LoweredValue::Aggregate(left), LoweredValue::Aggregate(right)) => {
            if left.len() != right.len() {
                return Some(false);
            }
            for (left, right) in left.iter().zip(right) {
                if !lowered_values_equal(left, right)? {
                    return Some(false);
                }
            }
            Some(true)
        }
        _ => Some(false),
    }
}

fn numeric_scalar(value: &LoweredValue) -> Option<ExactDecimal> {
    match value {
        LoweredValue::Scalar(ScalarValue::Int(value)) => Some(ExactDecimal::from_i64(*value)),
        LoweredValue::Scalar(ScalarValue::Float(value))
        | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => Some(*value),
        _ => None,
    }
}

fn lower_aggregate_intrinsic(
    node: &SourceHirNode,
    children: &[u32],
    fact: &crate::SemanticFact,
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let leaf = fact
        .resolved_definition()
        .or(node.symbol())
        .unwrap_or_default()
        .rsplit('.')
        .next()
        .unwrap_or_default();
    let arguments = children
        .iter()
        .skip(1)
        .map(|child| values[*child as usize].clone())
        .collect::<Option<Vec<_>>>();
    let Some(arguments) = arguments else {
        return Ok(None);
    };
    let result = match leaf {
        "range" => {
            let integers = arguments
                .iter()
                .map(|value| match value {
                    LoweredValue::Scalar(ScalarValue::Int(value)) => Some(*value),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>();
            let Some(integers) = integers else {
                return Ok(None);
            };
            let (start, stop, step) = match integers.as_slice() {
                [stop] => (0, *stop, 1),
                [start, stop] => (*start, *stop, 1),
                [start, stop, step] if *step != 0 => (*start, *stop, *step),
                _ => {
                    return Err(lowering_error(
                        node,
                        "range requires one to three integer arguments and a nonzero step",
                    ));
                }
            };
            let mut values = Vec::new();
            let mut current = start;
            while if step > 0 {
                current < stop
            } else {
                current > stop
            } {
                values.push(LoweredValue::Scalar(ScalarValue::Int(current)));
                current = current
                    .checked_add(step)
                    .ok_or_else(|| lowering_error(node, "range overflows Int64"))?;
            }
            LoweredValue::Aggregate(values)
        }
        "zip" => {
            let aggregates = arguments
                .into_iter()
                .map(|value| match value {
                    LoweredValue::Aggregate(values) => Some(values),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>();
            let Some(aggregates) = aggregates else {
                return Ok(None);
            };
            let length = aggregates.iter().map(Vec::len).min().unwrap_or(0);
            LoweredValue::Aggregate(
                (0..length)
                    .map(|index| {
                        LoweredValue::Aggregate(
                            aggregates
                                .iter()
                                .map(|values| values[index].clone())
                                .collect(),
                        )
                    })
                    .collect(),
            )
        }
        "enumerate" => {
            let Some(LoweredValue::Aggregate(values)) = arguments.first().cloned() else {
                return Ok(None);
            };
            let start = match arguments.get(1) {
                None => 0,
                Some(LoweredValue::Scalar(ScalarValue::Int(value))) => *value,
                Some(_) => return Ok(None),
            };
            LoweredValue::Aggregate(
                values
                    .into_iter()
                    .enumerate()
                    .map(|(index, value)| {
                        LoweredValue::Aggregate(vec![
                            LoweredValue::Scalar(ScalarValue::Int(start + index as i64)),
                            value,
                        ])
                    })
                    .collect(),
            )
        }
        "tuple" | "list" => match arguments.as_slice() {
            [LoweredValue::Aggregate(values)] => LoweredValue::Aggregate(values.clone()),
            _ => LoweredValue::Aggregate(arguments),
        },
        "ones_like" => {
            let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
                return Ok(None);
            };
            LoweredValue::Aggregate(
                (0..values.len())
                    .map(|_| LoweredValue::Scalar(ScalarValue::Float(ExactDecimal::from_i64(1))))
                    .collect(),
            )
        }
        _ => return Ok(None),
    };
    Ok(Some(result))
}

fn lower_static_subscript(
    children: &[u32],
    values: &[Option<LoweredValue>],
) -> Option<LoweredValue> {
    let [aggregate, index] = children else {
        return None;
    };
    let Some(LoweredValue::Aggregate(aggregate)) = values[*aggregate as usize].as_ref() else {
        return None;
    };
    let Some(LoweredValue::Scalar(ScalarValue::Int(index))) = values[*index as usize].as_ref()
    else {
        return None;
    };
    let index = if *index < 0 {
        aggregate.len().checked_sub(index.unsigned_abs() as usize)?
    } else {
        *index as usize
    };
    aggregate.get(index).cloned()
}

fn is_numeric_intrinsic(resolved: &str) -> bool {
    matches!(
        resolved.rsplit('.').next().unwrap_or(resolved),
        "sqrt" | "arccos" | "cos" | "sin" | "mod" | "round" | "len" | "sum"
    )
}

fn lower_numeric_intrinsic(
    node: &SourceHirNode,
    children: &[u32],
    resolved: &str,
    values: &[Option<LoweredValue>],
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let resolved = resolved.rsplit('.').next().unwrap_or(resolved);
    let arguments = children
        .iter()
        .skip(1)
        .filter_map(|child| values[*child as usize].clone())
        .collect::<Vec<_>>();
    if resolved == "len" {
        let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
            return Ok(None);
        };
        return Ok(Some(LoweredValue::Scalar(ScalarValue::Int(
            values.len() as i64
        ))));
    }
    if resolved == "sum" {
        let Some(LoweredValue::Aggregate(values)) = arguments.first() else {
            return Ok(None);
        };
        let operands = values
            .iter()
            .map(|value| match value {
                LoweredValue::Scalar(value) => Some(value.clone()),
                _ => None,
            })
            .collect::<Option<Vec<_>>>();
        let Some(mut operands) = operands else {
            return Ok(None);
        };
        let Some(mut total) = operands.drain(..1).next() else {
            return Ok(Some(LoweredValue::Scalar(ScalarValue::Int(0))));
        };
        for operand in operands {
            let Some(next) = fold_scalar_operation(ValueOperation::Add, &[total, operand]) else {
                return Ok(None);
            };
            total = next;
        }
        return Ok(Some(LoweredValue::Scalar(total)));
    }
    let numeric = arguments
        .iter()
        .map(|argument| match argument {
            LoweredValue::Scalar(ScalarValue::Int(value)) => Some(*value as f64),
            LoweredValue::Scalar(ScalarValue::Float(value))
            | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => Some(value.to_f64()),
            _ => None,
        })
        .collect::<Option<Vec<_>>>();
    let Some(numeric) = numeric else {
        return Ok(None);
    };
    let value = match (resolved, numeric.as_slice()) {
        ("sqrt", [value]) => value.sqrt(),
        ("arccos", [value]) => value.acos(),
        ("cos", [value]) => value.cos(),
        ("sin", [value]) => value.sin(),
        ("mod", [left, right]) => left.rem_euclid(*right),
        ("round", [value]) => value.round_ties_even(),
        _ => return Ok(None),
    };
    let value = ExactDecimal::from_f64_shortest(value)
        .ok_or_else(|| lowering_error(node, format!("{resolved} produced a non-finite value")))?;
    Ok(Some(LoweredValue::Scalar(ScalarValue::Float(value))))
}

fn lowered_to_json(value: &LoweredValue) -> Result<serde_json::Value, MorphismLoweringError> {
    match value {
        LoweredValue::Null => Ok(serde_json::Value::Null),
        LoweredValue::Json(value) => Ok(value.clone()),
        LoweredValue::Aggregate(values) => values
            .iter()
            .map(lowered_to_json)
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array),
        LoweredValue::Scalar(ScalarValue::Bool(value)) => Ok((*value).into()),
        LoweredValue::Scalar(ScalarValue::Int(value)) => Ok((*value).into()),
        LoweredValue::Scalar(ScalarValue::Float(value))
        | LoweredValue::Scalar(ScalarValue::DurationCycles(value)) => {
            serde_json::Number::from_f64(value.to_f64())
                .map(serde_json::Value::Number)
                .ok_or_else(|| MorphismLoweringError::new("native record contains non-finite data"))
        }
        LoweredValue::Scalar(ScalarValue::String(value)) => Ok(value.clone().into()),
        LoweredValue::Scalar(ScalarValue::Expr(id)) => Ok(serde_json::json!({
            "$value_expr": id.index()
        })),
        LoweredValue::Morphism(_)
        | LoweredValue::Template(_)
        | LoweredValue::ChannelBindings(_) => Err(MorphismLoweringError::new(
            "Morphism value cannot be embedded in a native record",
        )),
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
            TemplatePlanKind::Operation { .. } => {}
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

fn lower_literal(node: &SourceHirNode) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let value = match node.literal() {
        Some(SourceLiteral::Bool(value)) => ScalarValue::Bool(*value),
        Some(SourceLiteral::Int(value)) => ScalarValue::Int(value.parse().map_err(|_| {
            lowering_error(
                node,
                format!("integer literal {value:?} does not fit Int64"),
            )
        })?),
        Some(SourceLiteral::FloatBits(value)) => ScalarValue::Float(
            ExactDecimal::from_f64_shortest(f64::from_bits(*value))
                .ok_or_else(|| lowering_error(node, "invalid Float64 literal"))?,
        ),
        Some(SourceLiteral::String(value)) => ScalarValue::String(value.clone()),
        Some(SourceLiteral::None) => return Ok(Some(LoweredValue::Null)),
        None => return Ok(None),
    };
    Ok(Some(LoweredValue::Scalar(value)))
}

fn lower_compile_value(
    node: &SourceHirNode,
    value: &str,
    source_type: Option<&SourceType>,
    clock_hz: u64,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let scalar = match value {
        "True" | "true" => ScalarValue::Bool(true),
        "False" | "false" => ScalarValue::Bool(false),
        "constant:Bool(true)" => ScalarValue::Bool(true),
        "constant:Bool(false)" => ScalarValue::Bool(false),
        quoted
            if quoted.len() >= 2
                && ((quoted.starts_with('"') && quoted.ends_with('"'))
                    || (quoted.starts_with('\'') && quoted.ends_with('\''))) =>
        {
            ScalarValue::String(quoted[1..quoted.len() - 1].to_owned())
        }
        integer if integer.parse::<i64>().is_ok() => {
            ScalarValue::Int(integer.parse().expect("checked above"))
        }
        numeric => {
            let numeric = parse_normalized_numeric(numeric).ok_or_else(|| {
                lowering_error(node, format!("unsupported compile-time value {value:?}"))
            })?;
            if source_type == Some(&SourceType::Int64) {
                let integer = numeric
                    .to_cycle_count()
                    .and_then(|value| i64::try_from(value).ok())
                    .ok_or_else(|| lowering_error(node, "Int64 compile value is not integral"))?;
                ScalarValue::Int(integer)
            } else if source_type == Some(&SourceType::Duration)
                || normalized_has_duration_unit(value)
            {
                ScalarValue::DurationCycles(
                    numeric
                        .checked_mul(ExactDecimal::from_u64(clock_hz))
                        .ok_or_else(|| lowering_error(node, "duration conversion overflows"))?,
                )
            } else {
                ScalarValue::Float(numeric)
            }
        }
    };
    Ok(Some(LoweredValue::Scalar(scalar)))
}

fn normalized_has_duration_unit(value: &str) -> bool {
    value
        .split(|character: char| {
            !(character.is_ascii_alphanumeric() || character == '_' || character == ':')
        })
        .any(|token| matches!(token, "name:s" | "name:ms" | "name:us" | "name:ns"))
}

fn lower_normalized_default(value: &str, clock_hz: u64) -> Option<LoweredValue> {
    let scalar = match value {
        "constant:None" => return Some(LoweredValue::Null),
        "constant:Bool(true)" => ScalarValue::Bool(true),
        "constant:Bool(false)" => ScalarValue::Bool(false),
        value if value.starts_with("constant:Int(") => {
            let value = value
                .strip_prefix("constant:Int(")?
                .strip_suffix(')')?
                .parse()
                .ok()?;
            ScalarValue::Int(value)
        }
        value if normalized_has_duration_unit(value) =>
        {
            ScalarValue::DurationCycles(
                parse_normalized_numeric(value)?.checked_mul(ExactDecimal::from_u64(clock_hz))?,
            )
        }
        value => ScalarValue::Float(parse_normalized_numeric(value)?),
    };
    Some(LoweredValue::Scalar(scalar))
}

fn parse_normalized_numeric(value: &str) -> Option<ExactDecimal> {
    if let Some(value) = value
        .strip_prefix("constant:Float(")
        .and_then(|value| value.strip_suffix(')'))
        .or_else(|| {
            value
                .strip_prefix("constant:Int(")
                .and_then(|value| value.strip_suffix(')'))
        })
    {
        return ExactDecimal::parse(value);
    }
    if let Some(unit) = value.strip_prefix("name:") {
        return match unit {
            "s" => Some(ExactDecimal::from_u64(1)),
            "ms" => ExactDecimal::parse("0.001"),
            "us" => ExactDecimal::parse("0.000001"),
            "ns" => ExactDecimal::parse("0.000000001"),
            _ => None,
        };
    }
    if let Some(operand) = value
        .strip_prefix("unary:USub(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric(operand)?.checked_neg();
    }
    if let Some(operand) = value
        .strip_prefix("unary:UAdd(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric(operand);
    }
    for (prefix, operation) in [
        (
            "bin:Add(",
            ExactDecimal::checked_add as fn(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
        ),
        ("bin:Sub(", ExactDecimal::checked_sub),
        ("bin:Mult(", ExactDecimal::checked_mul),
        ("bin:Div(", ExactDecimal::checked_div),
    ] {
        if let Some(operands) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        {
            let (left, right) = split_normalized_operands(operands)?;
            return operation(
                parse_normalized_numeric(left)?,
                parse_normalized_numeric(right)?,
            );
        }
    }
    ExactDecimal::parse(value)
}

fn split_normalized_operands(operands: &str) -> Option<(&str, &str)> {
    let mut depth = 0_u32;
    for (index, character) in operands.char_indices() {
        match character {
            '(' => depth = depth.checked_add(1)?,
            ')' => depth = depth.checked_sub(1)?,
            ',' if depth == 0 => return Some((&operands[..index], &operands[index + 1..])),
            _ => {}
        }
    }
    None
}

fn normalized_to_json(
    value: &str,
    fields: &HashMap<String, String>,
) -> Result<serde_json::Value, MorphismLoweringError> {
    if value == "constant:None" {
        return Ok(serde_json::Value::Null);
    }
    if value == "constant:Bool(true)" {
        return Ok(true.into());
    }
    if value == "constant:Bool(false)" {
        return Ok(false.into());
    }
    if let Some(string) = value
        .strip_prefix("constant:Str(\"")
        .and_then(|value| value.strip_suffix("\")"))
    {
        return Ok(string.to_owned().into());
    }
    if let Some(number) = parse_normalized_numeric_with_fields(value, fields) {
        return serde_json::Number::from_f64(number.to_f64())
            .map(serde_json::Value::Number)
            .ok_or_else(|| MorphismLoweringError::new("non-finite normalized number"));
    }
    if let Some(name) = value.strip_prefix("name:")
        && let Some(value) = fields.get(name)
    {
        return normalized_to_json(value, fields);
    }
    if value.starts_with("path:") {
        return Ok(serde_json::Value::String(value.to_owned()));
    }
    if let Some(elements) = value
        .strip_prefix("aggregate:[")
        .and_then(|value| value.strip_suffix(']'))
    {
        return split_normalized_list(elements, ',')
            .into_iter()
            .filter(|value| !value.is_empty())
            .map(|value| normalized_to_json(value, fields))
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array);
    }
    if let Some(call) = value.strip_prefix("call:")
        && let Some(open) = call.find('(')
        && let Some(arguments) = call.strip_suffix(')')
    {
        let schema = &call[..open];
        let arguments = &arguments[open + 1..];
        let (positional, keywords) =
            split_normalized_once(arguments, ';').unwrap_or((arguments, ""));
        let field_names: &[&str] = match schema.rsplit('.').next().unwrap_or(schema) {
            "StaticWaveform" => &["freq", "amp", "sbg_id", "phase", "fct"],
            "RSPPIDConfig" => &[
                "adc_in",
                "rf_out",
                "dgt_source",
                "setpoint",
                "kp",
                "ki",
                "kd",
                "output_max",
            ],
            "RSPWaveformParams" => &["rf_out", "amp", "output_max"],
            other => {
                let _ = other;
                return Ok(serde_json::Value::String(value.to_owned()));
            }
        };
        let mut record = serde_json::Map::new();
        record.insert(
            "$type".to_owned(),
            schema
                .rsplit('.')
                .next()
                .unwrap_or(schema)
                .to_owned()
                .into(),
        );
        for (index, argument) in split_normalized_list(positional, ',')
            .into_iter()
            .filter(|value| !value.is_empty())
            .enumerate()
        {
            record.insert(
                field_names[index].to_owned(),
                normalized_to_json(argument, fields)?,
            );
        }
        for keyword in split_normalized_list(keywords, ',') {
            if keyword.is_empty() {
                continue;
            }
            let Some((name, value)) = split_normalized_once(keyword, '=') else {
                continue;
            };
            record.insert(name.to_owned(), normalized_to_json(value, fields)?);
        }
        return Ok(serde_json::Value::Object(record));
    }
    Ok(serde_json::Value::String(value.to_owned()))
}

fn parse_normalized_numeric_with_fields(
    value: &str,
    fields: &HashMap<String, String>,
) -> Option<ExactDecimal> {
    if let Some(value) = parse_normalized_numeric(value) {
        return Some(value);
    }
    if let Some(name) = value.strip_prefix("name:") {
        return parse_normalized_numeric_with_fields(fields.get(name)?, fields);
    }
    if let Some(operand) = value
        .strip_prefix("unary:USub(")
        .and_then(|value| value.strip_suffix(')'))
    {
        return parse_normalized_numeric_with_fields(operand, fields)?.checked_neg();
    }
    if let Some(operands) = value
        .strip_prefix("bin:LShift(")
        .and_then(|value| value.strip_suffix(')'))
    {
        let (left, right) = split_normalized_operands(operands)?;
        let left = parse_normalized_numeric_with_fields(left, fields)?.to_cycle_count()?;
        let right = parse_normalized_numeric_with_fields(right, fields)?.to_cycle_count()?;
        return left
            .checked_shl(u32::try_from(right).ok()?)
            .map(ExactDecimal::from_u64);
    }
    for (prefix, operation) in [
        (
            "bin:Add(",
            ExactDecimal::checked_add as fn(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
        ),
        ("bin:Sub(", ExactDecimal::checked_sub),
        ("bin:Mult(", ExactDecimal::checked_mul),
        ("bin:Div(", ExactDecimal::checked_div),
    ] {
        if let Some(operands) = value
            .strip_prefix(prefix)
            .and_then(|value| value.strip_suffix(')'))
        {
            let (left, right) = split_normalized_operands(operands)?;
            return operation(
                parse_normalized_numeric_with_fields(left, fields)?,
                parse_normalized_numeric_with_fields(right, fields)?,
            );
        }
    }
    None
}

fn split_normalized_once(value: &str, separator: char) -> Option<(&str, &str)> {
    let mut depth = 0_u32;
    for (index, character) in value.char_indices() {
        match character {
            '(' | '[' => depth = depth.checked_add(1)?,
            ')' | ']' => depth = depth.checked_sub(1)?,
            character if character == separator && depth == 0 => {
                return Some((&value[..index], &value[index + character.len_utf8()..]));
            }
            _ => {}
        }
    }
    None
}

fn split_normalized_list(mut value: &str, separator: char) -> Vec<&str> {
    let mut values = Vec::new();
    while let Some((left, right)) = split_normalized_once(value, separator) {
        values.push(left);
        value = right;
    }
    values.push(value);
    values
}

fn lower_duration_unit(node: &SourceHirNode, clock_hz: u64) -> Option<LoweredValue> {
    let denominator = match node.symbol()? {
        "s" => 1_u64,
        "ms" => 1_000,
        "us" => 1_000_000,
        "ns" => 1_000_000_000,
        _ => return None,
    };
    Some(LoweredValue::Scalar(ScalarValue::DurationCycles(
        ExactDecimal::from_u64(clock_hz).checked_div(ExactDecimal::from_u64(denominator))?,
    )))
}

fn lower_value_operation(
    node: &SourceHirNode,
    children: &[u32],
    values: &[Option<LoweredValue>],
    source_type: Option<&SourceType>,
    builder: &mut ValueExprArenaBuilder,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let operands = children
        .iter()
        .filter_map(|child| match values[*child as usize].clone() {
            Some(LoweredValue::Scalar(value)) => Some(value),
            _ => None,
        })
        .collect::<Vec<_>>();
    let operation = node
        .value_operation()
        .ok_or_else(|| lowering_error(node, "value operation is absent"))?;
    if operands.len() != children.len() {
        return Ok(None);
    }
    if let Some(value) = fold_scalar_operation(operation, &operands) {
        return Ok(Some(LoweredValue::Scalar(value)));
    }
    let Some(value_type) = source_type_to_value_type(source_type) else {
        return Ok(None);
    };
    let children = operands
        .iter()
        .cloned()
        .map(|value| scalar_to_expr(value, builder, node))
        .collect::<Result<Vec<_>, _>>()?;
    let kind = match operation {
        ValueOperation::Add => ValueExprKind::Add,
        ValueOperation::Subtract => ValueExprKind::Subtract,
        ValueOperation::Multiply => ValueExprKind::Multiply,
        ValueOperation::Divide => ValueExprKind::Divide,
        ValueOperation::Modulo => ValueExprKind::Modulo,
        ValueOperation::Negate => ValueExprKind::Negate,
        ValueOperation::Positive => return Ok(Some(LoweredValue::Scalar(operands[0].clone()))),
        ValueOperation::LogicalNot => {
            return Err(lowering_error(
                node,
                "link-time boolean negation cannot control Morphism structure",
            ));
        }
        ValueOperation::FloorDivide | ValueOperation::Power => {
            return Err(lowering_error(
                node,
                format!("{} is not supported in ValueExpr yet", operation.as_str()),
            ));
        }
        ValueOperation::LeftShift => {
            return Err(lowering_error(
                node,
                "link-time integer shifting is not supported",
            ));
        }
    };
    Ok(Some(LoweredValue::Scalar(ScalarValue::Expr(
        builder.operation(kind, value_type, &children),
    ))))
}

fn fold_scalar_operation(
    operation: ValueOperation,
    operands: &[ScalarValue],
) -> Option<ScalarValue> {
    use ScalarValue::{Bool, DurationCycles, Float, Int};
    match (operation, operands) {
        (ValueOperation::Add, [Int(left), Int(right)]) => left.checked_add(*right).map(Int),
        (ValueOperation::Subtract, [Int(left), Int(right)]) => left.checked_sub(*right).map(Int),
        (ValueOperation::Multiply, [Int(left), Int(right)]) => left.checked_mul(*right).map(Int),
        (ValueOperation::Divide, [Int(left), Int(right)]) => ExactDecimal::from_i64(*left)
            .checked_div(ExactDecimal::from_i64(*right))
            .map(Float),
        (ValueOperation::Add, [Float(left), Float(right)]) => left.checked_add(*right).map(Float),
        (ValueOperation::Subtract, [Float(left), Float(right)]) => {
            left.checked_sub(*right).map(Float)
        }
        (ValueOperation::Multiply, [Float(left), Float(right)]) => {
            left.checked_mul(*right).map(Float)
        }
        (ValueOperation::Divide, [Float(left), Float(right)]) => {
            left.checked_div(*right).map(Float)
        }
        (ValueOperation::Add, [Float(left), Int(right)])
        | (ValueOperation::Add, [Int(right), Float(left)]) => {
            left.checked_add(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Subtract, [Float(left), Int(right)]) => {
            left.checked_sub(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Subtract, [Int(left), Float(right)]) => {
            ExactDecimal::from_i64(*left).checked_sub(*right).map(Float)
        }
        (ValueOperation::Multiply, [Float(left), Int(right)])
        | (ValueOperation::Multiply, [Int(right), Float(left)]) => {
            left.checked_mul(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Divide, [Float(left), Int(right)]) => {
            left.checked_div(ExactDecimal::from_i64(*right)).map(Float)
        }
        (ValueOperation::Divide, [Int(left), Float(right)]) => {
            ExactDecimal::from_i64(*left).checked_div(*right).map(Float)
        }
        (ValueOperation::Power, [Int(base), Int(exponent)]) if *exponent >= 0 => {
            base.checked_pow(*exponent as u32).map(Int)
        }
        (ValueOperation::Power, [Float(base), Int(exponent)]) => {
            ExactDecimal::from_f64_shortest(base.to_f64().powi(*exponent as i32)).map(Float)
        }
        (ValueOperation::Power, [Float(base), Float(exponent)]) => {
            ExactDecimal::from_f64_shortest(base.to_f64().powf(exponent.to_f64())).map(Float)
        }
        (ValueOperation::LeftShift, [Int(value), Int(shift)]) if (0..64).contains(shift) => {
            value.checked_shl(*shift as u32).map(Int)
        }
        (ValueOperation::FloorDivide, [Int(left), Int(right)]) if *right != 0 => {
            Some(Int(left.div_euclid(*right)))
        }
        (ValueOperation::Modulo, [Int(left), Int(right)]) if *right != 0 => {
            Some(Int(left.rem_euclid(*right)))
        }
        (ValueOperation::Multiply, [DurationCycles(value), Int(scale)])
        | (ValueOperation::Multiply, [Int(scale), DurationCycles(value)]) => value
            .checked_mul(ExactDecimal::from_i64(*scale))
            .map(DurationCycles),
        (ValueOperation::Multiply, [DurationCycles(value), Float(scale)])
        | (ValueOperation::Multiply, [Float(scale), DurationCycles(value)]) => {
            value.checked_mul(*scale).map(DurationCycles)
        }
        (ValueOperation::Divide, [DurationCycles(value), Int(scale)]) => value
            .checked_div(ExactDecimal::from_i64(*scale))
            .map(DurationCycles),
        (ValueOperation::Divide, [DurationCycles(value), Float(scale)]) => {
            value.checked_div(*scale).map(DurationCycles)
        }
        (ValueOperation::Divide, [Float(value), DurationCycles(scale)]) => {
            value.checked_div(*scale).map(Float)
        }
        (ValueOperation::Divide, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_div(*right).map(Float)
        }
        (ValueOperation::Add, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_add(*right).map(DurationCycles)
        }
        (ValueOperation::Subtract, [DurationCycles(left), DurationCycles(right)]) => {
            left.checked_sub(*right).map(DurationCycles)
        }
        (ValueOperation::Negate, [Int(value)]) => value.checked_neg().map(Int),
        (ValueOperation::Negate, [Float(value)]) => value.checked_neg().map(Float),
        (ValueOperation::Negate, [DurationCycles(value)]) => value.checked_neg().map(Float),
        (ValueOperation::Positive, [value]) => Some(value.clone()),
        (ValueOperation::LogicalNot, [Bool(value)]) => Some(Bool(!value)),
        _ => None,
    }
}

fn call_arguments(
    children: &[u32],
    values: &[Option<LoweredValue>],
    builder: &mut ValueExprArenaBuilder,
    node: &SourceHirNode,
) -> Result<Vec<ValueExprId>, MorphismLoweringError> {
    let mut arguments = Vec::new();
    for child in children.iter().skip(1) {
        let Some(value) = values[*child as usize].clone() else {
            continue;
        };
        match value {
            LoweredValue::Scalar(value) => arguments.push(scalar_to_expr(value, builder, node)?),
            LoweredValue::Json(value) => {
                arguments.push(builder.constant(ValueExprPayload::Json(value)))
            }
            LoweredValue::Aggregate(values) => {
                arguments.push(builder.constant(ValueExprPayload::Json(
                    serde_json::Value::Array(values.iter().map(lowered_to_json).collect::<Result<
                        Vec<_>,
                        _,
                    >>(
                    )?),
                )))
            }
            LoweredValue::Null => {
                arguments.push(builder.constant(ValueExprPayload::Json(serde_json::Value::Null)))
            }
            LoweredValue::Morphism(_)
            | LoweredValue::Template(_)
            | LoweredValue::ChannelBindings(_) => {}
        }
    }
    Ok(arguments)
}

fn scalar_to_expr(
    value: ScalarValue,
    builder: &mut ValueExprArenaBuilder,
    node: &SourceHirNode,
) -> Result<ValueExprId, MorphismLoweringError> {
    let payload = match value {
        ScalarValue::Bool(value) => ValueExprPayload::Bool(value),
        ScalarValue::Int(value) => ValueExprPayload::Int64(value),
        ScalarValue::Float(value) => ValueExprPayload::Float64(value.to_f64()),
        ScalarValue::DurationCycles(value) => {
            let cycles = value.to_cycle_count_rounded().ok_or_else(|| {
                lowering_error(
                    node,
                    format!(
                        "duration {} is not an exact non-negative target Cycle Count",
                        value.to_f64()
                    ),
                )
            })?;
            ValueExprPayload::DurationCycles(cycles)
        }
        ScalarValue::String(value) => ValueExprPayload::String(value),
        ScalarValue::Expr(id) => return Ok(id),
    };
    Ok(builder.constant(payload))
}

fn source_type_to_value_type(source_type: Option<&SourceType>) -> Option<ValueExprType> {
    match source_type? {
        SourceType::Bool => Some(ValueExprType::Bool),
        SourceType::Int64 => Some(ValueExprType::Int64),
        SourceType::Float64 => Some(ValueExprType::Float64),
        SourceType::Duration => Some(ValueExprType::Duration),
        SourceType::String => Some(ValueExprType::String),
        _ => None,
    }
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

fn lower_compile_if(
    node: &SourceHirNode,
    children: &[u32],
    hir: &TypedSourceHir,
    values: &[Option<LoweredValue>],
    local_bindings: &mut HashMap<String, LoweredValue>,
) -> Result<Option<LoweredValue>, MorphismLoweringError> {
    let Some(condition) = children
        .first()
        .and_then(|child| values[*child as usize].as_ref())
    else {
        return Err(lowering_error(
            node,
            "source if condition is not compile-time evaluable; hardware branches are not supported",
        ));
    };
    let take_body = match condition {
        LoweredValue::Scalar(ScalarValue::Bool(value)) => *value,
        LoweredValue::Null => false,
        _ => {
            return Err(lowering_error(
                node,
                "source if condition is not a compile-time bool; hardware branches are not supported",
            ));
        }
    };
    let body_start = 1;
    let body_end = body_start + node.control_body_count() as usize;
    let else_end = body_end + node.control_else_count() as usize;
    if else_end > children.len() {
        return Err(lowering_error(
            node,
            "invalid Source HIR control-flow shape",
        ));
    }
    let selected = if take_body {
        &children[body_start..body_end]
    } else {
        &children[body_end..else_end]
    };
    for statement in selected {
        apply_selected_statement(*statement, hir, values, local_bindings)?;
    }
    Ok(selected
        .iter()
        .rev()
        .find_map(|statement| values[*statement as usize].clone()))
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

fn is_identity(resolved: &str) -> bool {
    resolved == "catseq.morphism.identity" || resolved.rsplit('.').next() == Some("identity")
}

fn lowering_error(node: &SourceHirNode, message: impl Display) -> MorphismLoweringError {
    MorphismLoweringError::new(format!(
        "{}:{}:{}: {message}",
        node.anchor().module(),
        node.anchor().line(),
        node.anchor().column()
    ))
}

#[cfg(test)]
mod tests {
    use super::normalized_has_duration_unit;

    #[test]
    fn normalized_duration_units_are_matched_as_complete_name_tokens() {
        assert!(normalized_has_duration_unit(
            "bin:Mult(constant:Int(80),name:ns)"
        ));
        assert!(!normalized_has_duration_unit("name:start"));
        assert!(!normalized_has_duration_unit("name:usage"));
    }
}
