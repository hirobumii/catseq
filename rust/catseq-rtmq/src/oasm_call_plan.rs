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
}

#[derive(Clone)]
struct DirectEvent {
    epoch: u32,
    offset_cycles: u64,
    board: String,
    function: OasmFunction,
    args: Vec<OasmArgument>,
    instruction_cost_cycles: u64,
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
                        if let Some(duration) = schema.fixed_duration_cycles {
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
            for board in boards {
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: start,
                    board: board.clone(),
                    function: OasmFunction::LoopBegin,
                    args: vec![OasmArgument::Unsigned(1), OasmArgument::Unsigned(count)],
                    instruction_cost_cycles: 0,
                });
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: end,
                    board,
                    function: OasmFunction::LoopEnd,
                    args: Vec::new(),
                    instruction_cost_cycles: cursor_advance,
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
    let mut epochs = Vec::new();
    for id in 0..=sync_counts[arena.root().index()] {
        let origin_cycles = *epoch_origins.get(&id).ok_or_else(|| {
            OasmCompileError::new(format!("epoch {id} has no global sync origin"))
        })?;
        let addresses = board_ttl_events
            .keys()
            .chain(board_direct_events.keys())
            .filter(|(event_epoch, _)| *event_epoch == id)
            .map(|(_, address)| address.clone())
            .collect::<std::collections::BTreeSet<_>>();
        let boards = addresses
            .into_iter()
            .map(|address| {
                let board = target.boards.get(&address).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no board capabilities for {address}"
                    ))
                })?;
                compile_board(
                    id,
                    origin_cycles,
                    address.clone(),
                    board.kind,
                    board_ttl_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                    board_direct_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
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

#[allow(clippy::too_many_arguments)]
fn lower_atomic_events(
    schema: &AtomicTargetSchema,
    channel_key: &str,
    binding: &ChannelBinding,
    board: &TargetBoard,
    start: u64,
    epoch: u32,
    duration: u64,
    arguments: &[ValueExprId],
    program: &NativeArenas,
    evaluated_values: &[Result<ExactDecimal, OasmCompileError>],
    clock_hz: u64,
    rwg_states: &mut HashMap<String, RwgChannelState>,
    rsp_pid_configs: &mut HashMap<String, serde_json::Value>,
    ttl_events: &mut Vec<TtlEvent>,
    direct_events: &mut Vec<DirectEvent>,
) -> Result<(), OasmCompileError> {
    let argument = |index: usize| -> Result<OasmArgument, OasmCompileError> {
        let id = arguments
            .get(index)
            .copied()
            .ok_or_else(|| OasmCompileError::new(format!("Atomic argument {index} is absent")))?;
        value_to_oasm_argument(program, evaluated_values, id)
    };
    let direct = |offset_cycles: u64,
                  function: OasmFunction,
                  args: Vec<OasmArgument>,
                  direct_events: &mut Vec<DirectEvent>| {
        direct_events.push(DirectEvent {
            epoch,
            offset_cycles,
            board: binding.board.clone(),
            function,
            args,
            instruction_cost_cycles: schema.instruction_cost_cycles,
        });
    };
    let validate_kind = |expected: ChannelKind| {
        if binding.kind == expected {
            Ok(())
        } else {
            Err(OasmCompileError::new(format!(
                "channel on {} has kind {:?}, expected {:?}",
                binding.board, binding.kind, expected
            )))
        }
    };
    match schema.lowering {
        AtomicLowering::TtlPulse | AtomicLowering::TtlSetHigh | AtomicLowering::TtlSetLow => {
            validate_kind(ChannelKind::Ttl)?;
            if binding.local_id >= board.ttl_width || board.ttl_width > 64 {
                return Err(OasmCompileError::new("invalid TTL local id"));
            }
            let high = schema.lowering != AtomicLowering::TtlSetLow;
            ttl_events.push(TtlEvent {
                epoch,
                offset_cycles: start,
                board: binding.board.clone(),
                local_id: binding.local_id,
                high,
                instruction_cost_cycles: schema.instruction_cost_cycles,
            });
            if schema.lowering == AtomicLowering::TtlPulse {
                ttl_events.push(TtlEvent {
                    epoch,
                    offset_cycles: start.checked_add(duration).ok_or_else(|| {
                        OasmCompileError::new("TTL pulse timestamp overflows u64")
                    })?,
                    board: binding.board.clone(),
                    local_id: binding.local_id,
                    high: false,
                    instruction_cost_cycles: schema.instruction_cost_cycles,
                });
            }
        }
        AtomicLowering::TtlInitialize => {
            validate_kind(ChannelKind::Ttl)?;
            direct(
                start,
                OasmFunction::TtlConfig,
                vec![
                    OasmArgument::Unsigned(1_u64 << binding.local_id),
                    OasmArgument::Unsigned(0),
                ],
                direct_events,
            );
        }
        AtomicLowering::RwgInitialize => {
            validate_kind(ChannelKind::Rwg)?;
            let hard = arguments
                .get(1)
                .copied()
                .and_then(|id| bool_argument(program, id))
                .unwrap_or(false);
            if hard {
                direct(start, OasmFunction::RwgInit, vec![], direct_events);
            }
            direct(
                start,
                OasmFunction::RwgSetCarrier,
                vec![
                    OasmArgument::Unsigned(binding.local_id.into()),
                    argument(0)?,
                ],
                direct_events,
            );
            rwg_states.insert(channel_key.to_owned(), RwgChannelState::Ready);
        }
        AtomicLowering::RwgSetState => {
            validate_kind(ChannelKind::Rwg)?;
            let targets = json_argument(program, arguments, 0, evaluated_values)?;
            let targets = targets
                .as_array()
                .ok_or_else(|| OasmCompileError::new("RWG targets must be a native aggregate"))?;
            let phase_reset = arguments
                .get(1)
                .copied()
                .and_then(|id| bool_argument(program, id))
                .unwrap_or(true);
            let rf_on = match rwg_states.get(channel_key) {
                Some(RwgChannelState::Ready) => false,
                Some(RwgChannelState::Active { rf_on, .. }) => *rf_on,
                None => {
                    return Err(OasmCompileError::new(
                        "RWG set_state requires a preceding initialize operation",
                    ));
                }
            };
            validate_static_waveforms(targets, true)?;
            emit_rwg_waveforms(
                binding,
                start,
                epoch,
                targets,
                phase_reset,
                StaticWaveformMode::Set,
                schema.instruction_cost_cycles,
                direct_events,
            );
            rwg_states.insert(
                channel_key.to_owned(),
                RwgChannelState::Active {
                    rf_on,
                    snapshot: targets.to_vec(),
                },
            );
        }
        AtomicLowering::RwgLinearRamp => {
            validate_kind(ChannelKind::Rwg)?;
            if duration == 0 {
                return Err(OasmCompileError::new(
                    "RWG linear_ramp duration must be positive",
                ));
            }
            let targets = json_argument(program, arguments, 0, evaluated_values)?;
            let targets = targets
                .as_array()
                .ok_or_else(|| OasmCompileError::new("RWG targets must be a native aggregate"))?;
            validate_static_waveforms(targets, false)?;
            let Some(RwgChannelState::Active { rf_on, snapshot }) =
                rwg_states.get(channel_key).cloned()
            else {
                return Err(OasmCompileError::new(
                    "RWG linear_ramp requires an active channel state",
                ));
            };
            if targets.len() != snapshot.len() {
                return Err(OasmCompileError::new(format!(
                    "RWG linear_ramp target count {} does not match active SBG count {}",
                    targets.len(),
                    snapshot.len()
                )));
            }
            let duration_us = duration as f64 * 1_000_000.0 / clock_hz as f64;
            let (ramp, static_stop, end_snapshot) =
                build_linear_ramp_waveforms(&snapshot, targets, duration_us)?;
            emit_prepared_rwg_waveforms(
                binding,
                start,
                epoch,
                ramp,
                schema.instruction_cost_cycles,
                direct_events,
            );
            emit_prepared_rwg_waveforms(
                binding,
                start
                    .checked_add(duration)
                    .ok_or_else(|| OasmCompileError::new("RWG ramp timestamp overflows"))?,
                epoch,
                static_stop,
                schema.instruction_cost_cycles,
                direct_events,
            );
            rwg_states.insert(
                channel_key.to_owned(),
                RwgChannelState::Active {
                    rf_on,
                    snapshot: end_snapshot,
                },
            );
        }
        AtomicLowering::RwgRfOn | AtomicLowering::RwgRfOff | AtomicLowering::RwgRfPulse => {
            validate_kind(ChannelKind::Rwg)?;
            let state = rwg_states.get_mut(channel_key).ok_or_else(|| {
                OasmCompileError::new("RWG RF switch requires a preceding initialize operation")
            })?;
            let mask = 1_u64 << binding.local_id;
            let off = schema.lowering == AtomicLowering::RwgRfOff;
            direct(
                start,
                OasmFunction::RwgRfSwitch,
                vec![
                    OasmArgument::Unsigned(mask),
                    OasmArgument::Unsigned(if off { mask } else { 0 }),
                ],
                direct_events,
            );
            if schema.lowering == AtomicLowering::RwgRfPulse {
                match state {
                    RwgChannelState::Active { rf_on: true, .. } => {
                        return Err(OasmCompileError::new(
                            "RWG rf_pulse requires rf_on=false at its start",
                        ));
                    }
                    RwgChannelState::Ready | RwgChannelState::Active { .. } => {}
                }
                direct(
                    start
                        .checked_add(duration)
                        .ok_or_else(|| OasmCompileError::new("RWG RF pulse timestamp overflows"))?,
                    OasmFunction::RwgRfSwitch,
                    vec![OasmArgument::Unsigned(mask), OasmArgument::Unsigned(mask)],
                    direct_events,
                );
            } else if let RwgChannelState::Active { rf_on, .. } = state {
                *rf_on = !off;
            }
        }
        AtomicLowering::RspInitialize => {
            validate_kind(ChannelKind::Rsp)?;
            let mut args = Vec::new();
            for index in 1..arguments.len() {
                args.push(argument(index)?);
            }
            direct(start, OasmFunction::RspInit, args, direct_events);
            direct(
                start,
                OasmFunction::RspSetCarrier,
                vec![
                    OasmArgument::Unsigned(binding.local_id.into()),
                    argument(0)?,
                ],
                direct_events,
            );
        }
        AtomicLowering::RspPidConfig => {
            validate_kind(ChannelKind::Rsp)?;
            let config = json_argument(program, arguments, 0, evaluated_values)?;
            rsp_pid_configs.insert(channel_key.to_owned(), config.clone());
            direct(
                start,
                OasmFunction::RspPidConfig,
                vec![OasmArgument::Json(config)],
                direct_events,
            );
        }
        AtomicLowering::RspPidStart | AtomicLowering::RspPidHold => {
            validate_kind(ChannelKind::Rsp)?;
            let config = rsp_pid_configs.get(channel_key).ok_or_else(|| {
                OasmCompileError::new("RSP PID operation requires a preceding pid_config")
            })?;
            let dgt_source = config
                .get("dgt_source")
                .and_then(json_u64)
                .ok_or_else(|| OasmCompileError::new("RSP PID config has no dgt_source"))?;
            direct(
                start,
                if schema.lowering == AtomicLowering::RspPidStart {
                    OasmFunction::RspPidStart
                } else {
                    OasmFunction::RspPidHold
                },
                vec![OasmArgument::Unsigned(dgt_source)],
                direct_events,
            );
        }
        AtomicLowering::RspPidRelease | AtomicLowering::RspPidRelink => {
            validate_kind(ChannelKind::Rsp)?;
            let config = rsp_pid_configs.get(channel_key).cloned().ok_or_else(|| {
                OasmCompileError::new("RSP PID operation requires a preceding pid_config")
            })?;
            direct(
                start,
                if schema.lowering == AtomicLowering::RspPidRelease {
                    OasmFunction::RspPidRelease
                } else {
                    OasmFunction::RspPidRelink
                },
                vec![OasmArgument::Json(config)],
                direct_events,
            );
        }
        AtomicLowering::RspRfConfig => direct(
            start,
            OasmFunction::RspRfConfig,
            vec![argument(0)?],
            direct_events,
        ),
        AtomicLowering::Hold | AtomicLowering::GlobalSync | AtomicLowering::Opaque => {
            unreachable!("handled by caller")
        }
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum StaticWaveformMode {
    Set,
}

fn validate_static_waveforms(
    targets: &[serde_json::Value],
    require_sbg_id: bool,
) -> Result<(), OasmCompileError> {
    for target in targets {
        let object = target
            .as_object()
            .ok_or_else(|| OasmCompileError::new("RWG target is not a StaticWaveform record"))?;
        if require_sbg_id && object.get("sbg_id").and_then(json_u64).is_none() {
            return Err(OasmCompileError::new(format!(
                "RWG set_state requires an integer sbg_id for every target; found {target}"
            )));
        }
    }
    Ok(())
}

type RwgRampTransition = (
    Vec<serde_json::Value>,
    Vec<serde_json::Value>,
    Vec<serde_json::Value>,
);

fn build_linear_ramp_waveforms(
    current: &[serde_json::Value],
    targets: &[serde_json::Value],
    duration_us: f64,
) -> Result<RwgRampTransition, OasmCompileError> {
    let mut ramp = Vec::with_capacity(targets.len());
    let mut static_stop = Vec::with_capacity(targets.len());
    let mut end_snapshot = Vec::with_capacity(targets.len());
    for (current, target) in current.iter().zip(targets) {
        let current = current.as_object().ok_or_else(|| {
            OasmCompileError::new("active RWG snapshot is not a StaticWaveform record")
        })?;
        let target = target.as_object().ok_or_else(|| {
            OasmCompileError::new("RWG ramp target is not a StaticWaveform record")
        })?;
        let sbg_id = current
            .get("sbg_id")
            .and_then(json_u64)
            .ok_or_else(|| OasmCompileError::new("active RWG waveform has no integer sbg_id"))?;
        let current_fct = current
            .get("fct")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let target_fct = target
            .get("fct")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        if current_fct != target_fct {
            return Err(OasmCompileError::new(format!(
                "RWG ramp fct mismatch for SBG {sbg_id}"
            )));
        }
        let start_freq = required_json_number(current.get("freq"), "active RWG frequency")?;
        let start_amp = required_json_number(current.get("amp"), "active RWG amplitude")?;
        let target_freq = optional_json_number(target.get("freq"))?.unwrap_or(start_freq);
        let target_amp = optional_json_number(target.get("amp"))?.unwrap_or(start_amp);
        let freq_rate = (target_freq - start_freq) / duration_us;
        let amp_rate = (target_amp - start_amp) / duration_us;
        let ramp_coefficients = |start: f64, rate: f64| {
            if rate == 0.0 {
                serde_json::json!([null, null, null, null])
            } else {
                serde_json::json!([start, rate, null, null])
            }
        };
        ramp.push(serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": ramp_coefficients(start_freq, freq_rate),
            "amp_coeffs": ramp_coefficients(start_amp, amp_rate),
            "initial_phase": 0.0,
            "phase_reset": false,
            "fct": current_fct,
        }));
        static_stop.push(serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": [target_freq, 0.0, null, null],
            "amp_coeffs": [target_amp, 0.0, null, null],
            "initial_phase": 0.0,
            "phase_reset": false,
            "fct": target_fct,
        }));
        end_snapshot.push(serde_json::json!({
            "$type": "StaticWaveform",
            "sbg_id": sbg_id,
            "freq": target_freq,
            "amp": target_amp,
            "phase": 0.0,
            "fct": target_fct,
        }));
    }
    Ok((ramp, static_stop, end_snapshot))
}

fn optional_json_number(
    value: Option<&serde_json::Value>,
) -> Result<Option<f64>, OasmCompileError> {
    match value {
        None | Some(serde_json::Value::Null) => Ok(None),
        Some(value) => value
            .as_f64()
            .map(Some)
            .ok_or_else(|| OasmCompileError::new("RWG waveform value is not numeric")),
    }
}

fn json_u64(value: &serde_json::Value) -> Option<u64> {
    value.as_u64().or_else(|| {
        let value = value.as_f64()?;
        (value.is_finite() && value >= 0.0 && value.fract() == 0.0 && value <= u64::MAX as f64)
            .then_some(value as u64)
    })
}

fn required_json_number(
    value: Option<&serde_json::Value>,
    description: &str,
) -> Result<f64, OasmCompileError> {
    optional_json_number(value)?
        .ok_or_else(|| OasmCompileError::new(format!("{description} is absent")))
}

#[allow(clippy::too_many_arguments)]
fn emit_rwg_waveforms(
    binding: &ChannelBinding,
    offset_cycles: u64,
    epoch: u32,
    targets: &[serde_json::Value],
    phase_reset: bool,
    _mode: StaticWaveformMode,
    instruction_cost_cycles: u64,
    events: &mut Vec<DirectEvent>,
) {
    for target in targets {
        let target = target.as_object().cloned().unwrap_or_default();
        let sbg_id = target
            .get("sbg_id")
            .and_then(json_u64)
            .expect("validated set_state target has an integer sbg_id");
        let waveform = serde_json::json!({
            "$type": "WaveformParams",
            "sbg_id": sbg_id,
            "freq_coeffs": [target.get("freq").cloned().unwrap_or(serde_json::Value::Null), null, null, null],
            "amp_coeffs": [target.get("amp").cloned().unwrap_or(serde_json::Value::Null), null, null, null],
            "initial_phase": target.get("phase").cloned().unwrap_or(serde_json::Value::Null),
            "phase_reset": phase_reset,
            "fct": target.get("fct").cloned().unwrap_or(serde_json::Value::Null)
        });
        events.push(DirectEvent {
            epoch,
            offset_cycles,
            board: binding.board.clone(),
            function: OasmFunction::RwgLoadWaveform,
            args: vec![OasmArgument::Json(waveform)],
            instruction_cost_cycles,
        });
    }
    let mask = 1_u64 << binding.local_id;
    events.push(DirectEvent {
        epoch,
        offset_cycles,
        board: binding.board.clone(),
        function: OasmFunction::RwgPlay,
        args: vec![OasmArgument::Unsigned(mask), OasmArgument::Unsigned(mask)],
        instruction_cost_cycles,
    });
}

fn emit_prepared_rwg_waveforms(
    binding: &ChannelBinding,
    offset_cycles: u64,
    epoch: u32,
    waveforms: Vec<serde_json::Value>,
    instruction_cost_cycles: u64,
    events: &mut Vec<DirectEvent>,
) {
    for waveform in waveforms {
        events.push(DirectEvent {
            epoch,
            offset_cycles,
            board: binding.board.clone(),
            function: OasmFunction::RwgLoadWaveform,
            args: vec![OasmArgument::Json(waveform)],
            instruction_cost_cycles,
        });
    }
    let mask = 1_u64 << binding.local_id;
    events.push(DirectEvent {
        epoch,
        offset_cycles,
        board: binding.board.clone(),
        function: OasmFunction::RwgPlay,
        args: vec![OasmArgument::Unsigned(mask), OasmArgument::Unsigned(mask)],
        instruction_cost_cycles,
    });
}

fn bool_argument(program: &NativeArenas, id: ValueExprId) -> Option<bool> {
    match program.values().payload(id).ok().flatten() {
        Some(ValueExprPayload::Bool(value)) => Some(*value),
        _ => None,
    }
}

fn json_argument(
    program: &NativeArenas,
    arguments: &[ValueExprId],
    index: usize,
    values: &[Result<ExactDecimal, OasmCompileError>],
) -> Result<serde_json::Value, OasmCompileError> {
    let id = arguments
        .get(index)
        .copied()
        .ok_or_else(|| OasmCompileError::new(format!("JSON argument {index} is absent")))?;
    let Some(ValueExprPayload::Json(value)) = program
        .values()
        .payload(id)
        .map_err(|error| OasmCompileError::new(error.to_string()))?
    else {
        return Err(OasmCompileError::new(format!(
            "argument {index} is not structured native data"
        )));
    };
    resolve_json_expressions(value, values)
}

fn resolve_json_expressions(
    value: &serde_json::Value,
    values: &[Result<ExactDecimal, OasmCompileError>],
) -> Result<serde_json::Value, OasmCompileError> {
    match value {
        serde_json::Value::Object(object)
            if object.len() == 1 && object.contains_key("$value_expr") =>
        {
            let index = object["$value_expr"]
                .as_u64()
                .ok_or_else(|| OasmCompileError::new("invalid native value expression reference"))?
                as usize;
            let value = values
                .get(index)
                .cloned()
                .ok_or_else(|| OasmCompileError::new("unknown native value expression"))??;
            serde_json::Number::from_f64(value.to_f64())
                .map(serde_json::Value::Number)
                .ok_or_else(|| OasmCompileError::new("native value expression is non-finite"))
        }
        serde_json::Value::Object(object) => object
            .iter()
            .map(|(key, value)| Ok((key.clone(), resolve_json_expressions(value, values)?)))
            .collect::<Result<serde_json::Map<_, _>, OasmCompileError>>()
            .map(serde_json::Value::Object),
        serde_json::Value::Array(array) => array
            .iter()
            .map(|value| resolve_json_expressions(value, values))
            .collect::<Result<Vec<_>, _>>()
            .map(serde_json::Value::Array),
        value => Ok(value.clone()),
    }
}

fn value_to_oasm_argument(
    program: &NativeArenas,
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
) -> Result<OasmArgument, OasmCompileError> {
    match program
        .values()
        .payload(id)
        .map_err(|error| OasmCompileError::new(error.to_string()))?
    {
        Some(ValueExprPayload::Bool(value)) => Ok(OasmArgument::Bool(*value)),
        Some(ValueExprPayload::Int64(value)) => Ok(OasmArgument::Signed(*value)),
        Some(ValueExprPayload::Float64(value)) => Ok(OasmArgument::Float(*value)),
        Some(ValueExprPayload::DurationCycles(value)) => Ok(OasmArgument::Unsigned(*value)),
        Some(ValueExprPayload::String(value)) => Ok(OasmArgument::String(value.clone())),
        Some(ValueExprPayload::Json(value)) => {
            Ok(OasmArgument::Json(resolve_json_expressions(value, values)?))
        }
        Some(ValueExprPayload::RuntimeSlot(_) | ValueExprPayload::EnvironmentSlot(_)) | None => {
            let value = values.get(id.index()).cloned().ok_or_else(|| {
                OasmCompileError::new(format!("unknown OASM argument expression {}", id.index()))
            })??;
            Ok(OasmArgument::Float(value.to_f64()))
        }
    }
}

fn compile_board(
    epoch: u32,
    origin_cycles: u64,
    address: String,
    board_kind: TargetBoardKind,
    mut events: Vec<TtlEvent>,
    mut direct_events: Vec<DirectEvent>,
) -> Result<OasmBoardPlan, OasmCompileError> {
    for event in &mut events {
        if event.epoch != epoch {
            return Err(OasmCompileError::new(
                "TTL event is assigned to the wrong epoch",
            ));
        }
        event.offset_cycles = event
            .offset_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("TTL event precedes its epoch origin"))?;
    }
    for event in &mut direct_events {
        if event.epoch != epoch {
            return Err(OasmCompileError::new(
                "direct event is assigned to the wrong epoch",
            ));
        }
        event.offset_cycles = event
            .offset_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("direct event precedes its epoch origin"))?;
    }
    events.sort_by_key(|event| (event.offset_cycles, event.local_id));
    let mut states = HashMap::<u8, bool>::new();
    let mut scheduled = coalesce_direct_events(direct_events)?;
    let mut index = 0;
    while index < events.len() {
        let offset = events[index].offset_cycles;
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
        scheduled.push(DirectEvent {
            epoch,
            offset_cycles: offset,
            board: address.clone(),
            function: OasmFunction::TtlSet,
            args: vec![
                OasmArgument::Unsigned(mask),
                OasmArgument::Unsigned(state),
                OasmArgument::String(board_kind.oasm_argument().to_owned()),
            ],
            instruction_cost_cycles,
        });
    }
    scheduled.sort_by_key(|event| (event.offset_cycles, oasm_function_priority(event.function)));
    let mut calls = Vec::with_capacity(scheduled.len());
    let mut cursor = 0_u64;
    for event in scheduled {
        if event.offset_cycles > cursor {
            calls.push(OasmCall {
                offset_cycles: cursor,
                function: OasmFunction::Wait,
                args: vec![OasmArgument::Unsigned(event.offset_cycles - cursor)],
            });
        }
        calls.push(OasmCall {
            offset_cycles: event.offset_cycles,
            function: event.function,
            args: event.args,
        });
        cursor = cursor.max(
            event
                .offset_cycles
                .checked_add(event.instruction_cost_cycles)
                .ok_or_else(|| OasmCompileError::new("OASM cursor overflows u64"))?,
        );
    }
    Ok(OasmBoardPlan { address, calls })
}

fn coalesce_direct_events(
    mut events: Vec<DirectEvent>,
) -> Result<Vec<DirectEvent>, OasmCompileError> {
    events.sort_by_key(|event| (event.offset_cycles, oasm_function_priority(event.function)));
    let mut coalesced = Vec::<DirectEvent>::with_capacity(events.len());
    for event in events {
        let mergeable = matches!(
            event.function,
            OasmFunction::TtlConfig | OasmFunction::RwgInit | OasmFunction::RwgPlay
        );
        let Some(previous) = coalesced.last_mut().filter(|previous| {
            mergeable
                && previous.offset_cycles == event.offset_cycles
                && previous.function == event.function
        }) else {
            coalesced.push(event);
            continue;
        };
        previous.instruction_cost_cycles = previous
            .instruction_cost_cycles
            .max(event.instruction_cost_cycles);
        match event.function {
            OasmFunction::RwgInit => {}
            OasmFunction::TtlConfig | OasmFunction::RwgPlay => {
                if previous.args.len() != 2 || event.args.len() != 2 {
                    return Err(OasmCompileError::new(
                        "mask-coalesced OASM call does not have two arguments",
                    ));
                }
                for index in 0..2 {
                    let left = match previous.args[index] {
                        OasmArgument::Unsigned(value) => value,
                        _ => {
                            return Err(OasmCompileError::new(
                                "mask-coalesced OASM argument is not unsigned",
                            ));
                        }
                    };
                    let right = match event.args[index] {
                        OasmArgument::Unsigned(value) => value,
                        _ => {
                            return Err(OasmCompileError::new(
                                "mask-coalesced OASM argument is not unsigned",
                            ));
                        }
                    };
                    previous.args[index] = OasmArgument::Unsigned(left | right);
                }
            }
            _ => unreachable!("only mergeable functions reach this branch"),
        }
    }
    Ok(coalesced)
}

fn oasm_function_priority(function: OasmFunction) -> u8 {
    match function {
        OasmFunction::LoopBegin => 0,
        OasmFunction::RwgInit | OasmFunction::RspInit | OasmFunction::TtlConfig => 1,
        OasmFunction::RwgLoadWaveform => 2,
        OasmFunction::RwgPlay => 4,
        OasmFunction::WaitMaster | OasmFunction::TrigSlave => 5,
        OasmFunction::LoopEnd => 6,
        _ => 3,
    }
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
                Ok(Some(ValueExprPayload::Json(_))) => Err(OasmCompileError::new(format!(
                    "expression {index} is structured data, not a numeric value"
                ))),
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
            ValueExprKind::Modulo => numeric_binary(&values, children, ExactDecimal::checked_rem),
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

fn eval_duration_cycles(
    values: &[Result<ExactDecimal, OasmCompileError>],
    id: ValueExprId,
    quantization: DurationQuantization,
) -> Result<u64, OasmCompileError> {
    let value = values.get(id.index()).cloned().unwrap_or_else(|| {
        Err(OasmCompileError::new(format!(
            "cannot evaluate expression {}",
            id.index()
        )))
    })?;
    let cycles = match quantization {
        DurationQuantization::Strict => value.to_cycle_count(),
        DurationQuantization::NearestEven => value.to_cycle_count_rounded(),
    };
    let requirement = match quantization {
        DurationQuantization::Strict => "an exact non-negative",
        DurationQuantization::NearestEven => "a non-negative",
    };
    cycles.ok_or_else(|| {
        OasmCompileError::new(format!(
            "duration {} is not {requirement} target Cycle Count (expression {})",
            value.to_f64(),
            id.index()
        ))
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
