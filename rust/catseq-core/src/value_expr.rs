//! Python-free scalar and duration expression DAG.

use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ValueExprId(u32);

impl ValueExprId {
    pub const fn from_index(index: u32) -> Self {
        Self(index)
    }

    pub const fn index(self) -> usize {
        self.0 as usize
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueExprType {
    Bool,
    Int64,
    Float64,
    Duration,
    String,
    Json,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueExprKind {
    Constant,
    RuntimeSlot,
    EnvironmentSlot,
    Intrinsic,
    Add,
    Subtract,
    Multiply,
    Divide,
    Modulo,
    Maximum,
    Negate,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RwgWaveformDerivation {
    Static,
    Linear,
    RampEndpoint,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum ValueExprPayload {
    Bool(bool),
    Int64(i64),
    Float64(f64),
    DurationCycles(u64),
    String(String),
    Json(serde_json::Value),
    RuntimeSlot(String),
    EnvironmentSlot(String),
    RwgWaveforms(RwgWaveformDerivation),
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ValueExprNode {
    kind: ValueExprKind,
    value_type: ValueExprType,
    edge_start: u32,
    edge_count: u32,
    payload: Option<u32>,
}

impl ValueExprNode {
    pub const fn kind(&self) -> ValueExprKind {
        self.kind
    }

    pub const fn value_type(&self) -> ValueExprType {
        self.value_type
    }

    pub const fn edge_start(&self) -> u32 {
        self.edge_start
    }

    pub const fn edge_count(&self) -> u32 {
        self.edge_count
    }

    pub const fn payload(&self) -> Option<u32> {
        self.payload
    }
}

#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct ValueExprArena {
    nodes: Vec<ValueExprNode>,
    edges: Vec<ValueExprId>,
    payloads: Vec<ValueExprPayload>,
}

impl ValueExprArena {
    pub fn nodes(&self) -> &[ValueExprNode] {
        &self.nodes
    }

    pub fn edges(&self) -> &[ValueExprId] {
        &self.edges
    }

    pub fn payloads(&self) -> &[ValueExprPayload] {
        &self.payloads
    }

    pub fn node(&self, id: ValueExprId) -> Result<&ValueExprNode, ValueExprError> {
        self.nodes
            .get(id.index())
            .ok_or_else(|| ValueExprError::new(format!("unknown Value Expression {}", id.0)))
    }

    pub fn children(&self, id: ValueExprId) -> Result<&[ValueExprId], ValueExprError> {
        let node = self.node(id)?;
        let start = node.edge_start as usize;
        self.edges
            .get(start..start + node.edge_count as usize)
            .ok_or_else(|| {
                ValueExprError::new(format!("invalid edge range on expression {}", id.0))
            })
    }

    pub fn payload(&self, id: ValueExprId) -> Result<Option<&ValueExprPayload>, ValueExprError> {
        let node = self.node(id)?;
        node.payload
            .map(|payload| {
                self.payloads.get(payload as usize).ok_or_else(|| {
                    ValueExprError::new(format!("invalid payload on expression {}", id.0))
                })
            })
            .transpose()
    }

    pub fn validate(&self) -> Result<(), ValueExprError> {
        for (index, node) in self.nodes.iter().enumerate() {
            let id = ValueExprId(index as u32);
            let children = self.children(id)?;
            if children
                .iter()
                .any(|child| child.index() >= self.nodes.len())
            {
                return Err(ValueExprError::new(format!(
                    "expression {index} references an unknown child"
                )));
            }
            let payload = self.payload(id)?;
            let payload_type = payload.and_then(|payload| match payload {
                ValueExprPayload::Bool(_) => Some(ValueExprType::Bool),
                ValueExprPayload::Int64(_) => Some(ValueExprType::Int64),
                ValueExprPayload::Float64(_) => Some(ValueExprType::Float64),
                ValueExprPayload::DurationCycles(_) => Some(ValueExprType::Duration),
                ValueExprPayload::String(_) => Some(ValueExprType::String),
                ValueExprPayload::Json(_) => Some(ValueExprType::Json),
                ValueExprPayload::RuntimeSlot(_)
                | ValueExprPayload::EnvironmentSlot(_)
                | ValueExprPayload::RwgWaveforms(_) => None,
            });
            match node.kind {
                ValueExprKind::Constant
                    if !children.is_empty() || payload_type != Some(node.value_type) =>
                {
                    return Err(ValueExprError::new(format!(
                        "leaf expression {index} has an invalid shape"
                    )));
                }
                ValueExprKind::RuntimeSlot
                    if !children.is_empty()
                        || !matches!(payload, Some(ValueExprPayload::RuntimeSlot(_))) =>
                {
                    return Err(ValueExprError::new(format!(
                        "runtime expression {index} has an invalid shape"
                    )));
                }
                ValueExprKind::EnvironmentSlot
                    if !children.is_empty()
                        || !matches!(payload, Some(ValueExprPayload::EnvironmentSlot(_))) =>
                {
                    return Err(ValueExprError::new(format!(
                        "environment expression {index} has an invalid shape"
                    )));
                }
                ValueExprKind::Intrinsic
                    if !matches!(payload, Some(ValueExprPayload::RwgWaveforms(_))) =>
                {
                    return Err(ValueExprError::new(format!(
                        "intrinsic expression {index} has an invalid shape"
                    )));
                }
                ValueExprKind::Negate if children.len() != 1 || payload.is_some() => {
                    return Err(ValueExprError::new(format!(
                        "unary expression {index} has an invalid shape"
                    )));
                }
                ValueExprKind::Add
                | ValueExprKind::Subtract
                | ValueExprKind::Multiply
                | ValueExprKind::Divide
                | ValueExprKind::Modulo
                | ValueExprKind::Maximum
                    if children.len() != 2 || payload.is_some() =>
                {
                    return Err(ValueExprError::new(format!(
                        "binary expression {index} has an invalid shape"
                    )));
                }
                _ => {}
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValueExprError(String);

impl ValueExprError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for ValueExprError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for ValueExprError {}

#[derive(Default)]
pub struct ValueExprArenaBuilder {
    nodes: Vec<ValueExprNode>,
    edges: Vec<ValueExprId>,
    payloads: Vec<ValueExprPayload>,
}

impl ValueExprArenaBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn constant(&mut self, payload: ValueExprPayload) -> ValueExprId {
        let value_type = match &payload {
            ValueExprPayload::Bool(_) => ValueExprType::Bool,
            ValueExprPayload::Int64(_) => ValueExprType::Int64,
            ValueExprPayload::Float64(_) => ValueExprType::Float64,
            ValueExprPayload::DurationCycles(_) => ValueExprType::Duration,
            ValueExprPayload::String(_) => ValueExprType::String,
            ValueExprPayload::Json(_) => ValueExprType::Json,
            ValueExprPayload::RuntimeSlot(_)
            | ValueExprPayload::EnvironmentSlot(_)
            | ValueExprPayload::RwgWaveforms(_) => {
                panic!("non-constant payload requires a declared type")
            }
        };
        self.leaf(ValueExprKind::Constant, value_type, payload)
    }

    pub fn runtime_slot(
        &mut self,
        name: impl Into<String>,
        value_type: ValueExprType,
    ) -> ValueExprId {
        self.leaf(
            ValueExprKind::RuntimeSlot,
            value_type,
            ValueExprPayload::RuntimeSlot(name.into()),
        )
    }

    pub fn environment_slot(
        &mut self,
        name: impl Into<String>,
        value_type: ValueExprType,
    ) -> ValueExprId {
        self.leaf(
            ValueExprKind::EnvironmentSlot,
            value_type,
            ValueExprPayload::EnvironmentSlot(name.into()),
        )
    }

    pub fn operation(
        &mut self,
        kind: ValueExprKind,
        value_type: ValueExprType,
        children: &[ValueExprId],
    ) -> ValueExprId {
        let edge_start = self.edges.len() as u32;
        self.edges.extend_from_slice(children);
        self.push(ValueExprNode {
            kind,
            value_type,
            edge_start,
            edge_count: children.len() as u32,
            payload: None,
        })
    }

    pub fn rwg_waveforms(
        &mut self,
        derivation: RwgWaveformDerivation,
        children: &[ValueExprId],
    ) -> ValueExprId {
        let edge_start = self.edges.len() as u32;
        self.edges.extend_from_slice(children);
        let payload = self.payloads.len() as u32;
        self.payloads
            .push(ValueExprPayload::RwgWaveforms(derivation));
        self.push(ValueExprNode {
            kind: ValueExprKind::Intrinsic,
            value_type: ValueExprType::Json,
            edge_start,
            edge_count: children.len() as u32,
            payload: Some(payload),
        })
    }

    pub fn finish(self) -> Result<ValueExprArena, ValueExprError> {
        let arena = ValueExprArena {
            nodes: self.nodes,
            edges: self.edges,
            payloads: self.payloads,
        };
        arena.validate()?;
        Ok(arena)
    }

    fn leaf(
        &mut self,
        kind: ValueExprKind,
        value_type: ValueExprType,
        payload: ValueExprPayload,
    ) -> ValueExprId {
        let payload_id = self.payloads.len() as u32;
        self.payloads.push(payload);
        self.push(ValueExprNode {
            kind,
            value_type,
            edge_start: self.edges.len() as u32,
            edge_count: 0,
            payload: Some(payload_id),
        })
    }

    fn push(&mut self, node: ValueExprNode) -> ValueExprId {
        let id = ValueExprId(self.nodes.len() as u32);
        self.nodes.push(node);
        id
    }
}
