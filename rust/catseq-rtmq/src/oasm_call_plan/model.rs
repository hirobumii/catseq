//! Input schemas, intermediate events, and the public OASM call-plan model.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::value_expr::ValueExprType;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CompileEnvironment {
    pub(super) schema_version: u32,
    pub(super) channels: BTreeMap<String, ChannelBinding>,
    #[serde(default)]
    pub(super) opaque_calls: BTreeMap<String, OpaqueCallBinding>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct OpaqueCallBinding {
    pub(super) callable: String,
    #[serde(default)]
    pub(super) args: Vec<serde_json::Value>,
    #[serde(default)]
    pub(super) kwargs: serde_json::Map<String, serde_json::Value>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LinkBindings {
    pub(super) schema_version: u32,
    #[serde(default)]
    pub(super) runtime_values: BTreeMap<String, LinkValue>,
    #[serde(default)]
    pub(super) environment_values: BTreeMap<String, LinkValue>,
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
    pub(super) schema_version: u32,
    pub(super) rtmq_abi_version: u32,
    pub(super) clock_hz: u64,
    #[serde(default)]
    pub(super) duration_quantization: DurationQuantization,
    #[serde(default)]
    pub(super) loop_timing: LoopTiming,
    pub(super) boards: BTreeMap<String, TargetBoard>,
    pub(super) operations: BTreeMap<String, AtomicTargetSchema>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct LoopTiming {
    pub(super) fixed_overhead_cycles: u64,
    pub(super) per_iteration_overhead_cycles: u64,
    pub(super) large_count_threshold: u64,
    pub(super) large_count_iteration_overhead_cycles: u64,
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
    pub(super) const fn iteration_overhead(self, count: u64) -> u64 {
        if count >= self.large_count_threshold {
            self.large_count_iteration_overhead_cycles
        } else {
            self.per_iteration_overhead_cycles
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(super) enum DurationQuantization {
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
pub(super) struct TargetBoard {
    pub(super) kind: TargetBoardKind,
    pub(super) ttl_width: u8,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(super) enum TargetBoardKind {
    Main,
    Rwg,
    Rsp,
}

impl TargetBoardKind {
    pub(super) const fn oasm_argument(self) -> &'static str {
        match self {
            Self::Main => "main",
            Self::Rwg => "rwg",
            Self::Rsp => "rsp",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct AtomicTargetSchema {
    pub(super) lowering: AtomicLowering,
    pub(super) duration_argument: Option<usize>,
    #[serde(default)]
    pub(super) fixed_duration_cycles: Option<u64>,
    #[serde(default)]
    pub(super) board: Option<String>,
    pub(super) instruction_cost_cycles: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(super) enum AtomicLowering {
    TtlInitialize,
    TtlSetHigh,
    TtlSetLow,
    RwgInitialize,
    RwgLoad,
    RwgPlay,
    RwgRfOn,
    RwgRfOff,
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
    pub(super) board: String,
    pub(super) local_id: u8,
    pub(super) kind: ChannelKind,
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
pub(super) enum LinkValue {
    Unsigned(u64),
    Signed(i64),
    Float(f64),
    Bool(bool),
    String(String),
}

impl LinkValue {
    pub(super) fn into_numeric_for(self, value_type: ValueExprType) -> Option<ExactDecimal> {
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

    pub(super) const fn matches_type(&self, value_type: ValueExprType) -> bool {
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
    pub(super) schema_version: u32,
    pub(super) epochs: Vec<OasmEpochPlan>,
    #[serde(skip)]
    pub(super) logical_duration_cycles: u64,
}

impl OasmCallPlan {
    pub fn epochs(&self) -> &[OasmEpochPlan] {
        &self.epochs
    }

    /// Duration of the root Morphism under its algebraic timing semantics.
    ///
    /// This deliberately excludes OASM instruction occupancy and hardware-loop
    /// scheduling overhead added while lowering the Morphism into a call plan.
    pub const fn logical_duration_cycles(&self) -> u64 {
        self.logical_duration_cycles
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmEpochPlan {
    pub(super) id: u32,
    pub(super) origin_cycles: u64,
    pub(super) boards: Vec<OasmBoardPlan>,
}

impl OasmEpochPlan {
    pub fn boards(&self) -> &[OasmBoardPlan] {
        &self.boards
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct OasmBoardPlan {
    pub(super) address: String,
    pub(super) calls: Vec<OasmCall>,
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
    pub(super) offset_cycles: u64,
    pub(super) function: OasmFunction,
    pub(super) args: Vec<OasmArgument>,
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
    pub(super) fn new(message: impl Into<String>) -> Self {
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
pub(super) struct TtlEvent {
    pub(super) epoch: u32,
    pub(super) offset_cycles: u64,
    pub(super) board: String,
    pub(super) local_id: u8,
    pub(super) high: bool,
    pub(super) instruction_cost_cycles: u64,
    pub(super) order: EventOrder,
    pub(super) loop_scope: Option<u64>,
}

#[derive(Clone)]
pub(super) struct DirectEvent {
    pub(super) epoch: u32,
    pub(super) offset_cycles: u64,
    pub(super) board: String,
    pub(super) function: OasmFunction,
    pub(super) args: Vec<OasmArgument>,
    pub(super) instruction_cost_cycles: u64,
    pub(super) order: EventOrder,
    pub(super) group_id: u64,
    pub(super) preload: bool,
    pub(super) loop_scope: Option<u64>,
}

#[derive(Clone, Copy)]
pub(super) struct LoopRegion {
    pub(super) epoch: u32,
    pub(super) start: u64,
    pub(super) body_duration: u64,
    pub(super) count: u64,
    pub(super) marker_group_id: u64,
}

pub(super) struct BoardEpochInput {
    pub(super) epoch: u32,
    pub(super) origin_cycles: u64,
    pub(super) address: String,
    pub(super) board_kind: TargetBoardKind,
    pub(super) duration_cycles: u64,
    pub(super) initial_cursor: u64,
    pub(super) ttl_events: Vec<TtlEvent>,
    pub(super) direct_events: Vec<DirectEvent>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub(super) struct EventOrder {
    pub(super) channel_kind: u8,
    pub(super) local_id: u8,
    pub(super) sequence: u64,
}

impl EventOrder {
    pub(super) const BOARD: Self = Self {
        channel_kind: 0,
        local_id: 0,
        sequence: 0,
    };

    pub(super) const fn channel(kind: ChannelKind, local_id: u8, sequence: u64) -> Self {
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
pub(super) enum RwgChannelState {
    Ready,
    Active {
        rf_on: bool,
        snapshot: Vec<serde_json::Value>,
    },
    ActiveUnknown {
        rf_on: bool,
    },
    WaveformsLoaded {
        rf_on: bool,
        transition: RwgPlayTransition,
        preload_group_id: u64,
    },
    Ramping {
        rf_on: bool,
        static_stop: Vec<serde_json::Value>,
        end_snapshot: Vec<serde_json::Value>,
    },
}

#[derive(Clone)]
pub(super) enum RwgPlayTransition {
    Activate {
        snapshot: Vec<serde_json::Value>,
    },
    ActivateUnknown,
    StartRamp {
        static_stop: Vec<serde_json::Value>,
        end_snapshot: Vec<serde_json::Value>,
    },
    FinishRamp {
        end_snapshot: Vec<serde_json::Value>,
    },
}
