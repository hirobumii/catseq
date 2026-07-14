//! Direct Typed Source HIR to canonical Morphism arena lowering.

use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::morphism_arena::{
    BoundaryPolicy, MorphismArena, MorphismArenaBuilder, MorphismNodeId, MorphismTemplateId,
    NativeProvenance, ProvenanceId,
};

use crate::{
    MorphismComposition, SourceHirKind, SourceHirNode, SourceType, TypedCheckReport,
    TypedDefinition, TypedSourceHir,
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
    Morphism(MorphismNodeId),
    Template(TemplatePlanId),
    ChannelBindings(Vec<ChannelBinding>),
}

#[derive(Clone)]
struct ChannelBinding {
    channel: String,
    template: TemplatePlanId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct TemplatePlanId(usize);

struct TemplatePlan {
    kind: TemplatePlanKind,
    provenance: ProvenanceId,
}

enum TemplatePlanKind {
    Operation(String),
    Serial {
        children: Vec<TemplatePlanId>,
        boundaries: Vec<BoundaryPolicy>,
    },
    Parallel(Vec<TemplatePlanId>),
}

/// Lower the checked entry definition to the first durable CatSeq program
/// representation. Resolved source definitions remain shared
/// `DefinitionRef` leaves; no Source HIR owner is retained by the result.
pub fn lower_typed_report_to_morphism_arena(
    report: &TypedCheckReport,
) -> Result<MorphismArena, MorphismLoweringError> {
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
    lower_entry(definition, &definitions)
}

fn lower_entry(
    definition: &TypedDefinition,
    definitions: &HashSet<&str>,
) -> Result<MorphismArena, MorphismLoweringError> {
    let hir = definition.hir();
    let mut builder = MorphismArenaBuilder::new();
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
    builder
        .finish(root)
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
        SourceType::ChannelBindings if definitions.contains(resolved) => Ok(Some(
            LoweredValue::Morphism(builder.definition_ref(resolved, provenance)),
        )),
        SourceType::MorphismTemplate => {
            let id = TemplatePlanId(template_plans.len());
            template_plans.push(TemplatePlan {
                kind: TemplatePlanKind::Operation(resolved.to_owned()),
                provenance,
            });
            Ok(Some(LoweredValue::Template(id)))
        }
        SourceType::Morphism if is_identity(resolved) => {
            Ok(Some(LoweredValue::Morphism(builder.wait(provenance))))
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
        SourceType::Morphism if definitions.contains(resolved) => Ok(Some(LoweredValue::Morphism(
            builder.definition_ref(resolved, provenance),
        ))),
        SourceType::Morphism => Ok(Some(LoweredValue::Morphism(
            builder.atomic(resolved, provenance),
        ))),
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
        _ => Err(lowering_error(
            node,
            "Morphism composition operand did not lower to a native value",
        )),
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
        LoweredValue::Template(_) => Err(MorphismLoweringError::new(
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
            TemplatePlanKind::Operation(_) => {}
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
            TemplatePlanKind::Operation(operation) => builder.atomic(operation, plan.provenance),
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
