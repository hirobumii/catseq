//! Native Morphism DAG lowering and linking to Python OASM calls.

use std::collections::{BTreeMap, HashMap};
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload};
use catseq_core::native_arenas::NativeArenas;
use catseq_core::value_expr::{ValueExprId, ValueExprPayload, ValueExprType};
use serde::{Deserialize, Serialize};

mod abi_cost;
mod atomic_lowering;
mod scheduler;
mod value_eval;

use abi_cost::oasm_call_cost;
use atomic_lowering::lower_atomic_events;
use scheduler::{apply_loop_timing, compile_board};
use value_eval::{eval_cycles, eval_duration_cycles, evaluate_numeric_values};

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CompileEnvironment {
    schema_version: u32,
    channels: BTreeMap<String, ChannelBinding>,
    #[serde(default)]
    opaque_calls: BTreeMap<String, OpaqueCallBinding>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct OpaqueCallBinding {
    callable: String,
    #[serde(default)]
    args: Vec<serde_json::Value>,
    #[serde(default)]
    kwargs: serde_json::Map<String, serde_json::Value>,
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
    #[serde(default)]
    duration_quantization: DurationQuantization,
    #[serde(default)]
    loop_timing: LoopTiming,
    boards: BTreeMap<String, TargetBoard>,
    operations: BTreeMap<String, AtomicTargetSchema>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct LoopTiming {
    fixed_overhead_cycles: u64,
    per_iteration_overhead_cycles: u64,
    large_count_threshold: u64,
    large_count_iteration_overhead_cycles: u64,
}

impl Default for LoopTiming {
    fn default() -> Self {
        Self {
            fixed_overhead_cycles: 15,
            per_iteration_overhead_cycles: 24,
            large_count_threshold: 128,
            large_count_iteration_overhead_cycles: 25,
        }
    }
}

impl LoopTiming {
    const fn iteration_overhead(self, count: u64) -> u64 {
        if count >= self.large_count_threshold {
            self.large_count_iteration_overhead_cycles
        } else {
            self.per_iteration_overhead_cycles
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum DurationQuantization {
    #[default]
    Strict,
    NearestEven,
}

impl TargetProfile {
    pub const fn clock_hz(&self) -> u64 {
        self.clock_hz
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
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
    Rsp,
}

impl TargetBoardKind {
    const fn oasm_argument(self) -> &'static str {
        match self {
            Self::Main => "main",
            Self::Rwg => "rwg",
            Self::Rsp => "rsp",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct AtomicTargetSchema {
    lowering: AtomicLowering,
    duration_argument: Option<usize>,
    #[serde(default)]
    fixed_duration_cycles: Option<u64>,
    #[serde(default)]
    board: Option<String>,
    instruction_cost_cycles: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum AtomicLowering {
    TtlPulse,
    TtlInitialize,
    TtlSetHigh,
    TtlSetLow,
    Hold,
    RwgInitialize,
    RwgSetState,
    RwgLinearRamp,
    RwgRfOn,
    RwgRfOff,
    RwgRfPulse,
    RspInitialize,
    RspPidConfig,
    RspPidStart,
    RspPidHold,
    RspPidRelease,
    RspPidRelink,
    RspRfConfig,
    GlobalSync,
    Opaque,
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
    Rwg,
    Rsp,
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
    LoopBegin,
    LoopEnd,
    TtlConfig,
    TtlSet,
    Wait,
    RwgInit,
    RwgSetCarrier,
    RwgRfSwitch,
    RwgLoadWaveform,
    RwgPlay,
    WaitMaster,
    TrigSlave,
    RspInit,
    RspSetCarrier,
    RspPidConfig,
    RspPidStart,
    RspPidHold,
    RspPidRelease,
    RspPidRelink,
    RspRfConfig,
    UserDefinedFunc,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum OasmArgument {
    Unsigned(u64),
    Signed(i64),
    Float(f64),
    Bool(bool),
    String(String),
    Json(serde_json::Value),
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
    epoch: u32,
    offset_cycles: u64,
    board: String,
    local_id: u8,
    high: bool,
    instruction_cost_cycles: u64,
    order: EventOrder,
    loop_scope: Option<u64>,
}

#[derive(Clone)]
struct DirectEvent {
    epoch: u32,
    offset_cycles: u64,
    board: String,
    function: OasmFunction,
    args: Vec<OasmArgument>,
    instruction_cost_cycles: u64,
    order: EventOrder,
    group_id: u64,
    preload: bool,
    loop_scope: Option<u64>,
}

#[derive(Clone, Copy)]
struct LoopRegion {
    epoch: u32,
    start: u64,
    body_duration: u64,
    count: u64,
    marker_group_id: u64,
}

struct BoardEpochInput {
    epoch: u32,
    origin_cycles: u64,
    address: String,
    board_kind: TargetBoardKind,
    duration_cycles: u64,
    initial_cursor: u64,
    ttl_events: Vec<TtlEvent>,
    direct_events: Vec<DirectEvent>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct EventOrder {
    channel_kind: u8,
    local_id: u8,
    sequence: u64,
}

impl EventOrder {
    const BOARD: Self = Self {
        channel_kind: 0,
        local_id: 0,
        sequence: 0,
    };

    const fn channel(kind: ChannelKind, local_id: u8, sequence: u64) -> Self {
        Self {
            channel_kind: match kind {
                ChannelKind::Rwg | ChannelKind::Rsp => 0,
                ChannelKind::Ttl => 1,
            },
            local_id,
            sequence,
        }
    }
}

#[derive(Clone)]
enum RwgChannelState {
    Ready,
    Active {
        rf_on: bool,
        snapshot: Vec<serde_json::Value>,
    },
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
                    eval_duration_cycles(&evaluated_values, *duration, target.duration_quantization)
                        .map_err(|error| {
                            let source = &arena.provenance()[node.provenance().index()];
                            OasmCompileError::new(format!(
                                "invalid wait at {}:{}:{}: {error}",
                                source.owner(),
                                source.line(),
                                source.column()
                            ))
                        })?
                }
                _ => unreachable!("validated arena has a Wait payload"),
            },
            MorphismNodeKind::Atomic => {
                match payload {
                    Some(payload @ MorphismPayload::Atomic { operation, .. }) => {
                        let operation = &arena.operations()[operation.index()];
                        let schema = target.operations.get(operation).ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Target Profile has no Atomic Schema for {operation}"
                            ))
                        })?;
                        if schema.lowering == AtomicLowering::RwgInitialize
                            && atomic_bool_argument(arena, payload, program, 1)
                        {
                            target.clock_hz.checked_div(1_000_000).ok_or_else(|| {
                                OasmCompileError::new("RWG hard-init delay is invalid")
                            })?
                        } else if let Some(duration) = schema.fixed_duration_cycles {
                            duration
                        } else if let Some(duration_argument) = schema.duration_argument {
                            let duration = arena
                            .payload_arguments(payload)
                            .map_err(|error| OasmCompileError::new(error.to_string()))?
                            .get(duration_argument)
                            .copied()
                            .ok_or_else(|| {
                                let source = &arena.provenance()[node.provenance().index()];
                                OasmCompileError::new(format!(
                                    "timed operation {operation} at {}:{}:{} requires a duration",
                                    source.owner(), source.line(), source.column()
                                ))
                            })?;
                            eval_duration_cycles(
                                &evaluated_values,
                                duration,
                                target.duration_quantization,
                            )
                            .map_err(|error| {
                                OasmCompileError::new(format!(
                                    "invalid duration for {operation}: {error}"
                                ))
                            })?
                        } else {
                            0
                        }
                    }
                    _ => unreachable!("validated arena has an Atomic payload"),
                }
            }
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
            MorphismNodeKind::Loop => {
                let Some(MorphismPayload::Loop { count }) = payload else {
                    unreachable!("validated arena has a Loop payload")
                };
                let count = eval_cycles(&evaluated_values, *count)?;
                let body = arena.children_by_node(node)[0];
                let iteration = durations[body.index()]
                    .checked_add(target.loop_timing.iteration_overhead(count))
                    .ok_or_else(|| {
                        OasmCompileError::new("loop iteration duration overflows u64 cycles")
                    })?;
                target
                    .loop_timing
                    .fixed_overhead_cycles
                    .checked_add(iteration.checked_mul(count).ok_or_else(|| {
                        OasmCompileError::new("loop duration overflows u64 cycles")
                    })?)
                    .ok_or_else(|| OasmCompileError::new("loop duration overflows u64 cycles"))?
            }
            MorphismNodeKind::SyncPhi => {
                return Err(OasmCompileError::new(format!(
                    "{:?} is not implemented by the 0.3 OASM backend",
                    node.kind()
                )));
            }
        };
    }

    // Epochs are a structural property of the Morphism DAG.  Keep them
    // separate from absolute timestamps so zero-duration operations following
    // a sync cannot be reordered to the pre-sync side of the boundary.
    let mut sync_counts = vec![0_u32; arena.nodes().len()];
    for (index, node) in arena.nodes().iter().enumerate() {
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        sync_counts[index] = match node.kind() {
            MorphismNodeKind::Atomic => match payload {
                Some(MorphismPayload::Atomic { operation, .. })
                    if target
                        .operations
                        .get(&arena.operations()[operation.index()])
                        .is_some_and(|schema| schema.lowering == AtomicLowering::GlobalSync) =>
                {
                    1
                }
                _ => 0,
            },
            MorphismNodeKind::Instantiate => match payload {
                Some(MorphismPayload::Instantiate { template, .. }) => {
                    sync_counts[arena.templates()[template.index()].root().index()]
                }
                _ => 0,
            },
            MorphismNodeKind::Serial => {
                arena
                    .children_by_node(node)
                    .iter()
                    .try_fold(0_u32, |count, child| {
                        count
                            .checked_add(sync_counts[child.index()])
                            .ok_or_else(|| OasmCompileError::new("global sync count overflows u32"))
                    })?
            }
            MorphismNodeKind::Parallel => {
                let mut child_counts = arena
                    .children_by_node(node)
                    .iter()
                    .map(|child| sync_counts[child.index()]);
                let first = child_counts.next().unwrap_or(0);
                if child_counts.any(|count| count != first) {
                    return Err(OasmCompileError::new(
                        "parallel branches cross different global sync epochs",
                    ));
                }
                first
            }
            MorphismNodeKind::Loop => {
                let body = arena.children_by_node(node)[0];
                if sync_counts[body.index()] != 0 {
                    return Err(OasmCompileError::new(
                        "hardware loops cannot contain a global sync boundary",
                    ));
                }
                0
            }
            MorphismNodeKind::Wait
            | MorphismNodeKind::DefinitionRef
            | MorphismNodeKind::SyncPhi => 0,
        };
    }

    let mut ttl_events = Vec::<TtlEvent>::new();
    let mut direct_events = Vec::<DirectEvent>::new();
    let mut rwg_states = HashMap::<String, RwgChannelState>::new();
    let mut rsp_pid_configs = HashMap::<String, serde_json::Value>::new();
    let mut loop_regions = Vec::<LoopRegion>::new();
    enum TraversalTask {
        Visit {
            node_id: usize,
            start: u64,
            epoch: u32,
            channel: Option<usize>,
        },
        FinishLoop {
            start: u64,
            epoch: u32,
            body_duration: u64,
            total_duration: u64,
            count: u64,
            ttl_start: usize,
            direct_start: usize,
        },
    }
    let mut pending = vec![TraversalTask::Visit {
        node_id: arena.root().index(),
        start: 0,
        epoch: 0,
        channel: None,
    }];
    let mut epoch_origins = BTreeMap::from([(0_u32, 0_u64)]);
    let mut next_event_id = 0_u64;
    while let Some(task) = pending.pop() {
        let TraversalTask::Visit {
            node_id,
            start,
            epoch,
            channel,
        } = task
        else {
            let TraversalTask::FinishLoop {
                start,
                epoch,
                body_duration,
                total_duration,
                count,
                ttl_start,
                direct_start,
            } = task
            else {
                unreachable!()
            };
            let boards = ttl_events[ttl_start..]
                .iter()
                .map(|event| event.board.clone())
                .chain(
                    direct_events[direct_start..]
                        .iter()
                        .map(|event| event.board.clone()),
                )
                .collect::<std::collections::BTreeSet<_>>();
            let end = start
                .checked_add(body_duration)
                .ok_or_else(|| OasmCompileError::new("loop timestamp overflows u64"))?;
            let cursor_advance = total_duration.checked_sub(body_duration).ok_or_else(|| {
                OasmCompileError::new("hardware loop duration is shorter than its body")
            })?;
            let marker_group_id = next_event_id;
            next_event_id = next_event_id
                .checked_add(1)
                .ok_or_else(|| OasmCompileError::new("OASM event id overflows u64"))?;
            loop_regions.push(LoopRegion {
                epoch,
                start,
                body_duration,
                count,
                marker_group_id,
            });
            for event in &mut ttl_events[ttl_start..] {
                event.loop_scope = Some(marker_group_id);
            }
            for event in &mut direct_events[direct_start..] {
                event.loop_scope = Some(marker_group_id);
            }
            for board in boards {
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: start,
                    board: board.clone(),
                    function: OasmFunction::LoopBegin,
                    args: vec![OasmArgument::Unsigned(1), OasmArgument::Unsigned(count)],
                    instruction_cost_cycles: 0,
                    order: EventOrder::BOARD,
                    group_id: marker_group_id,
                    preload: false,
                    loop_scope: Some(marker_group_id),
                });
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: end,
                    board,
                    function: OasmFunction::LoopEnd,
                    args: Vec::new(),
                    instruction_cost_cycles: cursor_advance,
                    order: EventOrder::BOARD,
                    group_id: marker_group_id,
                    preload: false,
                    loop_scope: Some(marker_group_id),
                });
            }
            continue;
        };
        let node = &arena.nodes()[node_id];
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        match node.kind() {
            MorphismNodeKind::Wait => {}
            MorphismNodeKind::Atomic => {
                let group_id = next_event_id;
                next_event_id = next_event_id
                    .checked_add(1)
                    .ok_or_else(|| OasmCompileError::new("OASM event id overflows u64"))?;
                let Some(MorphismPayload::Atomic { operation, .. }) = payload else {
                    unreachable!("validated arena has an Atomic payload")
                };
                let operation = &arena.operations()[operation.index()];
                let schema = target.operations.get(operation).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no Atomic Schema for {operation}"
                    ))
                })?;
                let arguments = arena
                    .payload_arguments(payload.expect("Atomic has payload"))
                    .map_err(|error| OasmCompileError::new(error.to_string()))?;
                if schema.lowering == AtomicLowering::GlobalSync {
                    if epoch_origins.insert(epoch + 1, start).is_some() {
                        return Err(OasmCompileError::new(format!(
                            "epoch {epoch} contains more than one global sync boundary"
                        )));
                    }
                    let frontier = direct_events
                        .iter()
                        .filter(|event| event.epoch == epoch)
                        .map(|event| {
                            event
                                .offset_cycles
                                .saturating_add(event.instruction_cost_cycles)
                        })
                        .chain(ttl_events.iter().filter(|event| event.epoch == epoch).map(
                            |event| {
                                event
                                    .offset_cycles
                                    .saturating_add(event.instruction_cost_cycles)
                            },
                        ))
                        .max()
                        .unwrap_or(start);
                    let master_wait = frontier.saturating_sub(start).saturating_add(100);
                    for (address, board) in &target.boards {
                        direct_events.push(DirectEvent {
                            epoch,
                            offset_cycles: start,
                            board: address.clone(),
                            function: if board.kind == TargetBoardKind::Main {
                                OasmFunction::TrigSlave
                            } else {
                                OasmFunction::WaitMaster
                            },
                            args: if board.kind == TargetBoardKind::Main {
                                vec![
                                    OasmArgument::Unsigned(master_wait),
                                    OasmArgument::Unsigned(12_345),
                                ]
                            } else {
                                vec![OasmArgument::Unsigned(12_345)]
                            },
                            instruction_cost_cycles: schema.instruction_cost_cycles,
                            order: EventOrder::BOARD,
                            group_id,
                            preload: false,
                            loop_scope: None,
                        });
                    }
                    continue;
                }
                if schema.lowering == AtomicLowering::Opaque {
                    let board = schema.board.as_ref().ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "opaque operation {operation} has no target board"
                        ))
                    })?;
                    let opaque = environment.opaque_calls.get(operation).ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "compile environment has no opaque call binding for {operation}"
                        ))
                    })?;
                    let args = vec![
                        OasmArgument::String(opaque.callable.clone()),
                        OasmArgument::Json(serde_json::Value::Array(opaque.args.clone())),
                        OasmArgument::Json(serde_json::Value::Object(opaque.kwargs.clone())),
                    ];
                    direct_events.push(DirectEvent {
                        epoch,
                        offset_cycles: start,
                        board: board.clone(),
                        function: OasmFunction::UserDefinedFunc,
                        args,
                        instruction_cost_cycles: schema.instruction_cost_cycles,
                        order: EventOrder::BOARD,
                        group_id,
                        preload: false,
                        loop_scope: None,
                    });
                    continue;
                }
                if schema.lowering == AtomicLowering::Hold {
                    continue;
                }
                let channel = channel.ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "hardware operation {operation} is not instantiated on a channel"
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
                lower_atomic_events(
                    schema,
                    channel_key,
                    binding,
                    board,
                    start,
                    epoch,
                    durations[node_id],
                    arguments,
                    program,
                    &evaluated_values,
                    target.clock_hz,
                    group_id,
                    &mut rwg_states,
                    &mut rsp_pid_configs,
                    &mut ttl_events,
                    &mut direct_events,
                )
                .map_err(|error| {
                    let source = &arena.provenance()[node.provenance().index()];
                    OasmCompileError::new(format!(
                        "cannot lower {operation} at {}:{}:{}: {error}",
                        source.owner(),
                        source.line(),
                        source.column()
                    ))
                })?;
            }
            MorphismNodeKind::Instantiate => {
                let Some(MorphismPayload::Instantiate { template, channel }) = payload else {
                    unreachable!("validated arena has an Instantiate payload")
                };
                pending.push(TraversalTask::Visit {
                    node_id: arena.templates()[template.index()].root().index(),
                    start,
                    epoch,
                    channel: Some(channel.index()),
                });
            }
            MorphismNodeKind::Serial => {
                let mut child_start = start;
                let mut child_epoch = epoch;
                let mut children = Vec::new();
                for child in arena.children_by_node(node) {
                    children.push(TraversalTask::Visit {
                        node_id: child.index(),
                        start: child_start,
                        epoch: child_epoch,
                        channel,
                    });
                    child_start = child_start
                        .checked_add(durations[child.index()])
                        .ok_or_else(|| OasmCompileError::new("serial timestamp overflows u64"))?;
                    child_epoch = child_epoch
                        .checked_add(sync_counts[child.index()])
                        .ok_or_else(|| OasmCompileError::new("epoch id overflows u32"))?;
                }
                pending.extend(children.into_iter().rev());
            }
            MorphismNodeKind::Parallel => {
                pending.extend(arena.children_by_node(node).iter().rev().map(|child| {
                    TraversalTask::Visit {
                        node_id: child.index(),
                        start,
                        epoch,
                        channel,
                    }
                }));
            }
            MorphismNodeKind::Loop => {
                let Some(MorphismPayload::Loop { count }) = payload else {
                    unreachable!("validated arena has a Loop payload")
                };
                let count = eval_cycles(&evaluated_values, *count)?;
                let body = arena.children_by_node(node)[0];
                let body_duration = durations[body.index()];
                pending.push(TraversalTask::FinishLoop {
                    start,
                    epoch,
                    body_duration,
                    total_duration: durations[node_id],
                    count,
                    ttl_start: ttl_events.len(),
                    direct_start: direct_events.len(),
                });
                pending.push(TraversalTask::Visit {
                    node_id: body.index(),
                    start,
                    epoch,
                    channel,
                });
            }
            MorphismNodeKind::DefinitionRef | MorphismNodeKind::SyncPhi => {
                unreachable!("unsupported nodes were rejected during duration analysis")
            }
        }
    }

    for event in &mut direct_events {
        event.instruction_cost_cycles = event.instruction_cost_cycles.max(oasm_call_cost(event)?);
    }
    let loop_delta = apply_loop_timing(
        &loop_regions,
        &mut ttl_events,
        &mut direct_events,
        &mut epoch_origins,
    )?;
    let program_duration = durations[arena.root().index()]
        .checked_add(loop_delta)
        .ok_or_else(|| OasmCompileError::new("program duration overflows u64"))?;

    let mut board_ttl_events = BTreeMap::<(u32, String), Vec<TtlEvent>>::new();
    for event in ttl_events {
        board_ttl_events
            .entry((event.epoch, event.board.clone()))
            .or_default()
            .push(event);
    }
    let mut board_direct_events = BTreeMap::<(u32, String), Vec<DirectEvent>>::new();
    for event in direct_events {
        board_direct_events
            .entry((event.epoch, event.board.clone()))
            .or_default()
            .push(event);
    }
    let program_addresses = board_ttl_events
        .keys()
        .chain(board_direct_events.keys())
        .map(|(_, address)| address.clone())
        .collect::<std::collections::BTreeSet<_>>();
    let mut epochs = Vec::new();
    let mut epoch_initial_cursors = BTreeMap::<String, u64>::new();
    for id in 0..=sync_counts[arena.root().index()] {
        let origin_cycles = *epoch_origins.get(&id).ok_or_else(|| {
            OasmCompileError::new(format!("epoch {id} has no global sync origin"))
        })?;
        let end_cycles = epoch_origins
            .get(&(id + 1))
            .copied()
            .unwrap_or(program_duration);
        let duration_cycles = end_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("epoch end precedes its origin"))?;
        let mut boards = program_addresses
            .iter()
            .map(|address| {
                let board = target.boards.get(address).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no board capabilities for {address}"
                    ))
                })?;
                compile_board(BoardEpochInput {
                    epoch: id,
                    origin_cycles,
                    address: address.clone(),
                    board_kind: board.kind,
                    duration_cycles,
                    initial_cursor: epoch_initial_cursors.get(address).copied().unwrap_or(0),
                    ttl_events: board_ttl_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                    direct_events: board_direct_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let sync_frontier = boards
            .iter()
            .flat_map(|board| board.calls.iter())
            .filter(|call| {
                matches!(
                    call.function,
                    OasmFunction::WaitMaster | OasmFunction::TrigSlave
                )
            })
            .map(|call| {
                call.offset_cycles
                    + if call.function == OasmFunction::WaitMaster {
                        8
                    } else {
                        0
                    }
            })
            .max();
        if let Some(sync_frontier) = sync_frontier {
            for board in &mut boards {
                for call in &mut board.calls {
                    if call.function == OasmFunction::TrigSlave {
                        let master_wait = sync_frontier
                            .saturating_sub(call.offset_cycles)
                            .saturating_add(100);
                        if let Some(argument) = call.args.first_mut() {
                            *argument = OasmArgument::Unsigned(master_wait);
                        }
                    }
                }
            }
        }
        epoch_initial_cursors.clear();
        for board in &boards {
            let carry = board
                .calls
                .iter()
                .rev()
                .find_map(|call| match call.function {
                    OasmFunction::WaitMaster => Some(8),
                    OasmFunction::TrigSlave => Some(17),
                    _ => None,
                });
            if let Some(carry) = carry {
                epoch_initial_cursors.insert(board.address.clone(), carry);
            }
        }
        epochs.push(OasmEpochPlan {
            id,
            origin_cycles,
            boards,
        });
    }
    Ok(OasmCallPlan {
        schema_version: 1,
        epochs,
    })
}

fn bool_argument(program: &NativeArenas, id: ValueExprId) -> Option<bool> {
    match program.values().payload(id).ok().flatten() {
        Some(ValueExprPayload::Bool(value)) => Some(*value),
        _ => None,
    }
}

fn atomic_bool_argument(
    arena: &catseq_core::morphism_arena::MorphismArena,
    payload: &MorphismPayload,
    program: &NativeArenas,
    index: usize,
) -> bool {
    arena
        .payload_arguments(payload)
        .ok()
        .and_then(|arguments| arguments.get(index))
        .and_then(|id| bool_argument(program, *id))
        .unwrap_or(false)
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
            opaque_calls: BTreeMap::new(),
        }
    }

    fn target() -> TargetProfile {
        TargetProfile {
            schema_version: 1,
            rtmq_abi_version: 1,
            clock_hz: 250_000_000,
            duration_quantization: DurationQuantization::Strict,
            loop_timing: LoopTiming::default(),
            boards: BTreeMap::new(),
            operations: BTreeMap::new(),
        }
    }

    fn direct_event(function: OasmFunction, args: Vec<OasmArgument>) -> DirectEvent {
        DirectEvent {
            epoch: 0,
            offset_cycles: 0,
            board: "rwg0".to_owned(),
            function,
            args,
            instruction_cost_cycles: 0,
            order: EventOrder::BOARD,
            group_id: 0,
            preload: false,
            loop_scope: None,
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

    #[test]
    fn oasm_instruction_occupancy_is_a_target_lowering_property() {
        let play = direct_event(
            OasmFunction::RwgPlay,
            vec![OasmArgument::Unsigned(1), OasmArgument::Unsigned(1)],
        );
        let zero_carrier = direct_event(
            OasmFunction::RwgSetCarrier,
            vec![OasmArgument::Unsigned(0), OasmArgument::Float(0.0)],
        );
        let ordinary_carrier = direct_event(
            OasmFunction::RwgSetCarrier,
            vec![OasmArgument::Unsigned(0), OasmArgument::Float(100.0)],
        );

        assert_eq!(oasm_call_cost(&play).unwrap(), 15);
        assert_eq!(oasm_call_cost(&zero_carrier).unwrap(), 16);
        assert_eq!(oasm_call_cost(&ordinary_carrier).unwrap(), 18);
    }
}
