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
use catseq_core::value_expr::{ValueExprArenaBuilder, ValueExprId, ValueExprPayload};

use crate::{
    MorphismComposition, SourceHirKind, SourceHirNode, SourceType, TypedCheckReport,
    TypedDefinition, TypedSourceHir, ValueAvailability,
};

mod normalized_value;
mod value_lowering;

use normalized_value::{
    lower_normalized_default, normalized_has_duration_unit, normalized_to_json,
};
use value_lowering::{
    call_arguments, is_numeric_intrinsic, lower_aggregate_intrinsic, lower_aggregate_operation,
    lower_compile_compare, lower_compile_value, lower_duration_unit, lower_literal,
    lower_numeric_intrinsic, lower_static_subscript, lower_value_operation, lowered_to_json,
    scalar_to_expr, source_type_to_value_type,
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
