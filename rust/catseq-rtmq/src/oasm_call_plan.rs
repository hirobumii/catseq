//! Native Morphism DAG lowering and linking to Python OASM calls.

use std::collections::{BTreeMap, HashMap};
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{ValueExprId, ValueExprKind, ValueExprPayload, ValueExprType};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CompileEnvironment {
    schema_version: u32,
    channels: BTreeMap<String, ChannelBinding>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LinkBindings {
    schema_version: u32,
    #[serde(default)]
    runtime_values: BTreeMap<String, LinkValue>,
    #[serde(default)]
    environment_values: BTreeMap<String, LinkValue>,
}

impl LinkBindings {
    pub fn empty() -> Self {
        Self {
            schema_version: 1,
            runtime_values: BTreeMap::new(),
            environment_values: BTreeMap::new(),
        }
    }
}

impl CompileEnvironment {
    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TargetProfile {
    schema_version: u32,
    rtmq_abi_version: u32,
    clock_hz: u64,
    boards: BTreeMap<String, TargetBoard>,
    operations: BTreeMap<String, AtomicTargetSchema>,
}

impl TargetProfile {
    pub const fn clock_hz(&self) -> u64 {
        self.clock_hz
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct TargetBoard {
    kind: TargetBoardKind,
    ttl_width: u8,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum TargetBoardKind {
    Main,
    Rwg,
}

impl TargetBoardKind {
    const fn oasm_argument(self) -> &'static str {
        match self {
            Self::Main => "main",
            Self::Rwg => "rwg",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct AtomicTargetSchema {
    lowering: AtomicLowering,
    duration_argument: Option<usize>,
    instruction_cost_cycles: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum AtomicLowering {
    TtlPulse,
    Hold,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
pub struct ChannelBinding {
    board: String,
    local_id: u8,
    kind: ChannelKind,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ChannelKind {
    Ttl,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(untagged)]
enum LinkValue {
    Unsigned(u64),
    Signed(i64),
    Float(f64),
    Bool(bool),
    String(String),
}

impl LinkValue {
    fn into_numeric_for(self, value_type: ValueExprType) -> Option<ExactDecimal> {
        match (value_type, self) {
            (ValueExprType::Duration, Self::Unsigned(value)) => Some(ExactDecimal::from_u64(value)),
            (ValueExprType::Int64, Self::Unsigned(value)) => {
                i64::try_from(value).ok().map(ExactDecimal::from_i64)
            }
            (ValueExprType::Int64, Self::Signed(value)) => Some(ExactDecimal::from_i64(value)),
            (ValueExprType::Float64, Self::Unsigned(value)) => Some(ExactDecimal::from_u64(value)),
            (ValueExprType::Float64, Self::Signed(value)) => Some(ExactDecimal::from_i64(value)),
            (ValueExprType::Float64, Self::Float(value)) => ExactDecimal::from_f64_shortest(value),
            _ => None,
        }
    }

    const fn matches_type(&self, value_type: ValueExprType) -> bool {
        matches!(
            (value_type, self),
            (ValueExprType::Duration, Self::Unsigned(_))
                | (ValueExprType::Int64, Self::Unsigned(_) | Self::Signed(_))
                | (
                    ValueExprType::Float64,
                    Self::Unsigned(_) | Self::Signed(_) | Self::Float(_)
                )
                | (ValueExprType::Bool, Self::Bool(_))
                | (ValueExprType::String, Self::String(_))
        )
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmCallPlan {
    schema_version: u32,
    epochs: Vec<OasmEpochPlan>,
}

impl OasmCallPlan {
    pub fn epochs(&self) -> &[OasmEpochPlan] {
        &self.epochs
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmEpochPlan {
    id: u32,
    origin_cycles: u64,
    boards: Vec<OasmBoardPlan>,
}

impl OasmEpochPlan {
    pub fn boards(&self) -> &[OasmBoardPlan] {
        &self.boards
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmBoardPlan {
    address: String,
    calls: Vec<OasmCall>,
}

impl OasmBoardPlan {
    pub fn address(&self) -> &str {
        &self.address
    }

    pub fn calls(&self) -> &[OasmCall] {
        &self.calls
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmCall {
    offset_cycles: u64,
    function: OasmFunction,
    args: Vec<OasmArgument>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OasmFunction {
    TtlSet,
    Wait,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum OasmArgument {
    Unsigned(u64),
    Signed(i64),
    Float(f64),
    Bool(bool),
    String(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OasmCompileError(String);

impl OasmCompileError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for OasmCompileError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for OasmCompileError {}

#[derive(Clone)]
struct TtlEvent {
    offset_cycles: u64,
    board: String,
    local_id: u8,
    high: bool,
    instruction_cost_cycles: u64,
}

/// Lower, schedule and link native arenas into calls understood by the
/// existing Python OASM adapter. No Python object participates in this pass.
pub fn compile_oasm_call_plan(
    program: &NativeArenas,
    environment: &CompileEnvironment,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<OasmCallPlan, OasmCompileError> {
    if environment.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported compile environment schema {}",
            environment.schema_version
        )));
    }
    if target.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported target profile schema {}",
            target.schema_version
        )));
    }
    if target.rtmq_abi_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported RTMQ ABI version {}",
            target.rtmq_abi_version
        )));
    }
    if target.clock_hz == 0 {
        return Err(OasmCompileError::new("clock_hz must be nonzero"));
    }
    if link_bindings.schema_version != 1 {
        return Err(OasmCompileError::new(format!(
            "unsupported link bindings schema {}",
            link_bindings.schema_version
        )));
    }
    let arena = program.morphisms();
    let evaluated_values = evaluate_numeric_values(program, link_bindings);
    let mut durations = vec![0_u64; arena.nodes().len()];
    for (index, node) in arena.nodes().iter().enumerate() {
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        durations[index] = match node.kind() {
            MorphismNodeKind::Wait => match payload {
                Some(MorphismPayload::Wait { duration }) => {
                    eval_cycles(&evaluated_values, *duration)?
                }
                _ => unreachable!("validated arena has a Wait payload"),
            },
            MorphismNodeKind::Atomic => match payload {
                Some(payload @ MorphismPayload::Atomic { operation, .. }) => {
                    let operation = &arena.operations()[operation.index()];
                    let schema = target.operations.get(operation).ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "Target Profile has no Atomic Schema for {operation}"
                        ))
                    })?;
                    if let Some(duration_argument) = schema.duration_argument {
                        let duration = arena
                            .payload_arguments(payload)
                            .map_err(|error| OasmCompileError::new(error.to_string()))?
                            .get(duration_argument)
                            .copied()
                            .ok_or_else(|| {
                                OasmCompileError::new(format!(
                                    "timed operation {operation} requires a duration"
                                ))
                            })?;
                        eval_cycles(&evaluated_values, duration)?
                    } else {
                        0
                    }
                }
                _ => unreachable!("validated arena has an Atomic payload"),
            },
            MorphismNodeKind::Instantiate => match payload {
                Some(MorphismPayload::Instantiate { template, .. }) => {
                    durations[arena.templates()[template.index()].root().index()]
                }
                _ => unreachable!("validated arena has an Instantiate payload"),
            },
            MorphismNodeKind::Serial => {
                arena
                    .children_by_node(node)
                    .iter()
                    .try_fold(0_u64, |duration, child| {
                        duration
                            .checked_add(durations[child.index()])
                            .ok_or_else(|| {
                                OasmCompileError::new("serial duration overflows u64 cycles")
                            })
                    })?
            }
            MorphismNodeKind::Parallel => arena
                .children_by_node(node)
                .iter()
                .map(|child| durations[child.index()])
                .max()
                .unwrap_or(0),
            MorphismNodeKind::DefinitionRef => {
                let definition = match payload {
                    Some(MorphismPayload::DefinitionRef { definition, .. }) => {
                        &arena.definitions()[definition.index()]
                    }
                    _ => "<unknown>",
                };
                return Err(OasmCompileError::new(format!(
                    "unresolved Morphism definition {definition}; specialization is required before RTMQ lowering"
                )));
            }
            MorphismNodeKind::Loop | MorphismNodeKind::SyncPhi => {
                return Err(OasmCompileError::new(format!(
                    "{:?} is not implemented by the 0.3 OASM backend",
                    node.kind()
                )));
            }
        };
    }

    let mut events = Vec::new();
    let mut pending = vec![(arena.root().index(), 0_u64, None::<usize>)];
    while let Some((node_id, start, channel)) = pending.pop() {
        let node = &arena.nodes()[node_id];
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        match node.kind() {
            MorphismNodeKind::Wait => {}
            MorphismNodeKind::Atomic => {
                let Some(MorphismPayload::Atomic { operation, .. }) = payload else {
                    unreachable!("validated arena has an Atomic payload")
                };
                let operation = &arena.operations()[operation.index()];
                let schema = target.operations.get(operation).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no Atomic Schema for {operation}"
                    ))
                })?;
                if schema.lowering == AtomicLowering::TtlPulse {
                    let channel = channel.ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "TTL operation {operation} is not instantiated on a channel"
                        ))
                    })?;
                    let channel_key = &arena.channels()[channel];
                    let binding = environment.channels.get(channel_key).ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "compile environment has no binding for channel {channel_key}"
                        ))
                    })?;
                    let board = target.boards.get(&binding.board).ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "Target Profile has no board capabilities for {}",
                            binding.board
                        ))
                    })?;
                    if binding.kind != ChannelKind::Ttl
                        || binding.local_id >= board.ttl_width
                        || board.ttl_width > 64
                        || schema.instruction_cost_cycles == 0
                    {
                        return Err(OasmCompileError::new(format!(
                            "channel {channel_key} is not a valid TTL channel"
                        )));
                    }
                    events.push(TtlEvent {
                        offset_cycles: start,
                        board: binding.board.clone(),
                        local_id: binding.local_id,
                        high: true,
                        instruction_cost_cycles: schema.instruction_cost_cycles,
                    });
                    events.push(TtlEvent {
                        offset_cycles: start.checked_add(durations[node_id]).ok_or_else(|| {
                            OasmCompileError::new("TTL pulse timestamp overflows u64 cycles")
                        })?,
                        board: binding.board.clone(),
                        local_id: binding.local_id,
                        high: false,
                        instruction_cost_cycles: schema.instruction_cost_cycles,
                    });
                }
            }
            MorphismNodeKind::Instantiate => {
                let Some(MorphismPayload::Instantiate { template, channel }) = payload else {
                    unreachable!("validated arena has an Instantiate payload")
                };
                pending.push((
                    arena.templates()[template.index()].root().index(),
                    start,
                    Some(channel.index()),
                ));
            }
            MorphismNodeKind::Serial => {
                let mut child_start = start;
                let mut children = Vec::new();
                for child in arena.children_by_node(node) {
                    children.push((child.index(), child_start, channel));
                    child_start = child_start
                        .checked_add(durations[child.index()])
                        .ok_or_else(|| OasmCompileError::new("serial timestamp overflows u64"))?;
                }
                pending.extend(children.into_iter().rev());
            }
            MorphismNodeKind::Parallel => {
                pending.extend(
                    arena
                        .children_by_node(node)
                        .iter()
                        .rev()
                        .map(|child| (child.index(), start, channel)),
                );
            }
            MorphismNodeKind::DefinitionRef
            | MorphismNodeKind::Loop
            | MorphismNodeKind::SyncPhi => {
                unreachable!("unsupported nodes were rejected during duration analysis")
            }
        }
    }

    let mut board_events = BTreeMap::<String, Vec<TtlEvent>>::new();
    for event in events {
        board_events
            .entry(event.board.clone())
            .or_default()
            .push(event);
    }
    let boards = board_events
        .into_iter()
        .map(|(address, events)| {
            let board = target.boards.get(&address).ok_or_else(|| {
                OasmCompileError::new(format!(
                    "Target Profile has no board capabilities for {address}"
                ))
            })?;
            compile_board(address, board.kind, events)
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(OasmCallPlan {
        schema_version: 1,
        epochs: vec![OasmEpochPlan {
            id: 0,
            origin_cycles: 0,
            boards,
        }],
    })
}

fn compile_board(
    address: String,
    board_kind: TargetBoardKind,
    mut events: Vec<TtlEvent>,
) -> Result<OasmBoardPlan, OasmCompileError> {
    events.sort_by_key(|event| (event.offset_cycles, event.local_id));
    let mut states = HashMap::<u8, bool>::new();
    let mut calls = Vec::new();
    let mut cursor = 0;
    let mut index = 0;
    while index < events.len() {
        let offset = events[index].offset_cycles;
        if offset < cursor {
            return Err(OasmCompileError::new(format!(
                "board {address} needs an event at cycle {offset}, before OASM is ready at {cursor}"
            )));
        }
        if offset > cursor {
            calls.push(OasmCall {
                offset_cycles: cursor,
                function: OasmFunction::Wait,
                args: vec![OasmArgument::Unsigned(offset - cursor)],
            });
        }
        let mut mask = 0_u64;
        let mut instruction_cost_cycles = 0_u64;
        while index < events.len() && events[index].offset_cycles == offset {
            let event = &events[index];
            mask |= 1_u64 << event.local_id;
            states.insert(event.local_id, event.high);
            instruction_cost_cycles = instruction_cost_cycles.max(event.instruction_cost_cycles);
            index += 1;
        }
        let state = states.iter().fold(0_u64, |bits, (local_id, high)| {
            if *high {
                bits | (1_u64 << local_id)
            } else {
                bits
            }
        });
        calls.push(OasmCall {
            offset_cycles: offset,
            function: OasmFunction::TtlSet,
            args: vec![
                OasmArgument::Unsigned(mask),
                OasmArgument::Unsigned(state),
                OasmArgument::String(board_kind.oasm_argument().to_owned()),
            ],
        });
        cursor = offset
            .checked_add(instruction_cost_cycles)
            .ok_or_else(|| OasmCompileError::new("OASM cursor overflows u64"))?;
    }
    Ok(OasmBoardPlan { address, calls })
}

fn evaluate_numeric_values(
    program: &NativeArenas,
    link_bindings: &LinkBindings,
) -> Vec<Result<ExactDecimal, OasmCompileError>> {
    let arena = program.values();
    let mut values =
        Vec::<Result<ExactDecimal, OasmCompileError>>::with_capacity(arena.nodes().len());
    for (index, node) in arena.nodes().iter().enumerate() {
        let children = &arena.edges()
            [node.edge_start() as usize..node.edge_start() as usize + node.edge_count() as usize];
        let value = match node.kind() {
            ValueExprKind::Constant => match arena.payload(ValueExprId::from_index(index as u32)) {
                Ok(Some(ValueExprPayload::DurationCycles(value))) => {
                    Ok(ExactDecimal::from_u64(*value))
                }
                Ok(Some(ValueExprPayload::Int64(value))) => Ok(ExactDecimal::from_i64(*value)),
                Ok(Some(ValueExprPayload::Float64(value))) => {
                    ExactDecimal::from_f64_shortest(*value).ok_or_else(|| {
                        OasmCompileError::new(format!("expression {index} is not finite"))
                    })
                }
                _ => Err(OasmCompileError::new(format!(
                    "expression {index} is not an integer duration"
                ))),
            },
            ValueExprKind::Add => numeric_binary(&values, children, ExactDecimal::checked_add),
            ValueExprKind::Subtract => numeric_binary(&values, children, ExactDecimal::checked_sub),
            ValueExprKind::Multiply => numeric_binary(&values, children, ExactDecimal::checked_mul),
            ValueExprKind::Divide => match numeric_operand(&values, children[1]) {
                Ok(denominator) => numeric_operand(&values, children[0]).and_then(|numerator| {
                    numerator
                        .checked_div(denominator)
                        .ok_or_else(|| OasmCompileError::new("duration division is invalid"))
                }),
                Err(error) => Err(error),
            },
            ValueExprKind::Maximum => numeric_binary(&values, children, ExactDecimal::maximum),
            ValueExprKind::Negate => numeric_operand(&values, children[0]).and_then(|value| {
                value
                    .checked_neg()
                    .ok_or_else(|| OasmCompileError::new("numeric negation overflows"))
            }),
            ValueExprKind::RuntimeSlot => {
                match arena.payload(ValueExprId::from_index(index as u32)) {
                    Ok(Some(ValueExprPayload::RuntimeSlot(name))) => link_bindings
                        .runtime_values
                        .get(name)
                        .filter(|value| value.matches_type(node.value_type()))
                        .cloned()
                        .and_then(|value| value.into_numeric_for(node.value_type()))
                        .ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Runtime Slot {name:?} is absent or has the wrong type in Link Bindings"
                            ))
                        }),
                    _ => Err(OasmCompileError::new(format!(
                        "RuntimeSlot expression {index} has no slot payload"
                    ))),
                }
            }
            ValueExprKind::EnvironmentSlot => {
                match arena.payload(ValueExprId::from_index(index as u32)) {
                    Ok(Some(ValueExprPayload::EnvironmentSlot(name))) => link_bindings
                        .environment_values
                        .get(name)
                        .filter(|value| value.matches_type(node.value_type()))
                        .cloned()
                        .and_then(|value| value.into_numeric_for(node.value_type()))
                        .ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Environment Slot {name:?} is absent or has the wrong type in Link Bindings"
                            ))
                        }),
                    _ => Err(OasmCompileError::new(format!(
                        "EnvironmentSlot expression {index} has no slot payload"
                    ))),
                }
            }
        };
        values.push(value);
    }
    values
}

fn numeric_binary(
    values: &[Result<ExactDecimal, OasmCompileError>],
    children: &[ValueExprId],
    operation: impl FnOnce(ExactDecimal, ExactDecimal) -> Option<ExactDecimal>,
) -> Result<ExactDecimal, OasmCompileError> {
    let left = numeric_operand(values, children[0])?;
    let right = numeric_operand(values, children[1])?;
    operation(left, right).ok_or_else(|| OasmCompileError::new("exact numeric operation failed"))
}

fn numeric_operand(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<ExactDecimal, OasmCompileError> {
    values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "expression {} is not topological",
            id.index()
        )))
    })
}

fn eval_cycles(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<u64, OasmCompileError> {
    let value = values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "cannot evaluate expression {}",
            id.index()
        )))
    })?;
    value.to_cycle_count().ok_or_else(|| {
        OasmCompileError::new("duration is not an exact non-negative target Cycle Count")
    })
}

trait MorphismArenaNodeExt {
    fn children_by_node<'a>(
        &'a self,
        node: &catseq_core::morphism_arena::MorphismNode,
    ) -> &'a [catseq_core::morphism_arena::MorphismNodeId];
}

impl MorphismArenaNodeExt for catseq_core::morphism_arena::MorphismArena {
    fn children_by_node<'a>(
        &'a self,
        node: &catseq_core::morphism_arena::MorphismNode,
    ) -> &'a [catseq_core::morphism_arena::MorphismNodeId] {
        let start = node.edge_start() as usize;
        &self.edges()[start..start + node.edge_count() as usize]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use catseq_core::morphism_arena::{MorphismArenaBuilder, NativeProvenance};
    use catseq_core::value_expr::{ValueExprArenaBuilder, ValueExprType};

    fn duration_program(environment_slot: bool) -> NativeArenas {
        let mut values = ValueExprArenaBuilder::new();
        let duration = if environment_slot {
            values.environment_slot("delay", ValueExprType::Duration)
        } else {
            values.runtime_slot("delay", ValueExprType::Duration)
        };
        let values = values.finish().unwrap();
        let mut morphisms = MorphismArenaBuilder::new();
        let provenance = morphisms.intern_provenance(NativeProvenance::new("test.sequence", 1, 1));
        let root = morphisms.wait(duration, provenance);
        NativeArenas::new(morphisms.finish(root).unwrap(), values).unwrap()
    }

    fn empty_environment() -> CompileEnvironment {
        CompileEnvironment {
            schema_version: 1,
            channels: BTreeMap::new(),
        }
    }

    fn target() -> TargetProfile {
        TargetProfile {
            schema_version: 1,
            rtmq_abi_version: 1,
            clock_hz: 250_000_000,
            boards: BTreeMap::new(),
            operations: BTreeMap::new(),
        }
    }

    #[test]
    fn duration_runtime_slots_require_integer_cycle_bindings() {
        let program = duration_program(false);
        let bindings = LinkBindings {
            schema_version: 1,
            runtime_values: BTreeMap::from([("delay".to_owned(), LinkValue::Float(5.0))]),
            environment_values: BTreeMap::new(),
        };

        let error = compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings)
            .unwrap_err();

        assert!(error.to_string().contains("wrong type"));
    }

    #[test]
    fn link_bindings_supply_environment_slots() {
        let program = duration_program(true);
        let bindings = LinkBindings {
            schema_version: 1,
            runtime_values: BTreeMap::new(),
            environment_values: BTreeMap::from([("delay".to_owned(), LinkValue::Unsigned(5))]),
        };

        let plan =
            compile_oasm_call_plan(&program, &empty_environment(), &target(), &bindings).unwrap();

        assert!(plan.epochs()[0].boards().is_empty());
    }

    #[test]
    fn link_values_cover_the_closed_scalar_type_set() {
        assert!(LinkValue::Bool(true).matches_type(ValueExprType::Bool));
        assert!(LinkValue::String("state".to_owned()).matches_type(ValueExprType::String));
        assert!(!LinkValue::Float(5.0).matches_type(ValueExprType::Duration));
    }
}
