//! Canonical, backend-independent Morphism DAG storage.
//!
//! Unlike the compatibility arena in [`crate::arena`], this is the durable
//! compiler representation. Nodes contain only native integer references;
//! source spelling and Python objects never become node payloads.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};

macro_rules! arena_id {
    ($name:ident) => {
        #[derive(
            Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
        )]
        #[serde(transparent)]
        pub struct $name(u32);

        impl $name {
            pub const fn index(self) -> usize {
                self.0 as usize
            }
        }
    };
}

arena_id!(MorphismNodeId);
arena_id!(MorphismPayloadId);
arena_id!(DefinitionId);
arena_id!(OperationId);
arena_id!(ChannelId);
arena_id!(ProvenanceId);
arena_id!(MorphismTemplateId);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BoundaryPolicy {
    Auto,
    Strict,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MorphismNodeKind {
    Atomic,
    Wait,
    Instantiate,
    DefinitionRef,
    Serial,
    Parallel,
    Loop,
    SyncPhi,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum MorphismPayload {
    Wait,
    Atomic {
        operation: OperationId,
    },
    Instantiate {
        template: MorphismTemplateId,
        channel: ChannelId,
    },
    DefinitionRef {
        definition: DefinitionId,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct NativeProvenance {
    owner: String,
    line: u32,
    column: u32,
}

impl NativeProvenance {
    pub fn new(owner: impl Into<String>, line: u32, column: u32) -> Self {
        Self {
            owner: owner.into(),
            line,
            column,
        }
    }

    pub fn owner(&self) -> &str {
        &self.owner
    }

    pub const fn line(&self) -> u32 {
        self.line
    }

    pub const fn column(&self) -> u32 {
        self.column
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MorphismNode {
    kind: MorphismNodeKind,
    edge_start: u32,
    edge_count: u32,
    boundary_start: u32,
    payload: Option<MorphismPayloadId>,
    provenance: ProvenanceId,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MorphismTemplate {
    root: MorphismNodeId,
}

impl MorphismTemplate {
    pub const fn root(&self) -> MorphismNodeId {
        self.root
    }
}

impl MorphismNode {
    pub const fn kind(&self) -> MorphismNodeKind {
        self.kind
    }

    pub const fn edge_start(&self) -> u32 {
        self.edge_start
    }

    pub const fn edge_count(&self) -> u32 {
        self.edge_count
    }

    pub const fn boundary_start(&self) -> u32 {
        self.boundary_start
    }

    pub const fn payload(&self) -> Option<MorphismPayloadId> {
        self.payload
    }

    pub const fn provenance(&self) -> ProvenanceId {
        self.provenance
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MorphismArena {
    root: MorphismNodeId,
    nodes: Vec<MorphismNode>,
    edges: Vec<MorphismNodeId>,
    boundaries: Vec<BoundaryPolicy>,
    payloads: Vec<MorphismPayload>,
    templates: Vec<MorphismTemplate>,
    definitions: Vec<String>,
    operations: Vec<String>,
    channels: Vec<String>,
    provenance: Vec<NativeProvenance>,
}

impl MorphismArena {
    pub const fn root(&self) -> MorphismNodeId {
        self.root
    }

    pub fn nodes(&self) -> &[MorphismNode] {
        &self.nodes
    }

    pub fn edges(&self) -> &[MorphismNodeId] {
        &self.edges
    }

    pub fn serial_boundaries(&self) -> &[BoundaryPolicy] {
        &self.boundaries
    }

    pub fn payloads(&self) -> &[MorphismPayload] {
        &self.payloads
    }

    pub fn templates(&self) -> &[MorphismTemplate] {
        &self.templates
    }

    pub fn definitions(&self) -> &[String] {
        &self.definitions
    }

    pub fn operations(&self) -> &[String] {
        &self.operations
    }

    pub fn channels(&self) -> &[String] {
        &self.channels
    }

    pub fn provenance(&self) -> &[NativeProvenance] {
        &self.provenance
    }

    pub fn node(&self, id: MorphismNodeId) -> Result<&MorphismNode, MorphismArenaError> {
        self.nodes
            .get(id.index())
            .ok_or_else(|| MorphismArenaError::new(format!("unknown Morphism node {}", id.0)))
    }

    pub fn children(&self, id: MorphismNodeId) -> Result<&[MorphismNodeId], MorphismArenaError> {
        let node = self.node(id)?;
        let start = node.edge_start as usize;
        let end = start + node.edge_count as usize;
        self.edges
            .get(start..end)
            .ok_or_else(|| MorphismArenaError::new(format!("invalid edge range on node {}", id.0)))
    }

    pub fn boundaries(&self, id: MorphismNodeId) -> Result<&[BoundaryPolicy], MorphismArenaError> {
        let node = self.node(id)?;
        if node.kind != MorphismNodeKind::Serial {
            return Ok(&[]);
        }
        let start = node.boundary_start as usize;
        let count = node.edge_count.saturating_sub(1) as usize;
        self.boundaries.get(start..start + count).ok_or_else(|| {
            MorphismArenaError::new(format!("invalid boundary range on node {}", id.0))
        })
    }

    pub fn validate(&self) -> Result<(), MorphismArenaError> {
        self.node(self.root)?;
        for (index, template) in self.templates.iter().enumerate() {
            self.node(template.root).map_err(|_| {
                MorphismArenaError::new(format!("template {index} has an unknown root"))
            })?;
        }
        for (index, node) in self.nodes.iter().enumerate() {
            let id = MorphismNodeId(index as u32);
            let children = self.children(id)?;
            if children
                .iter()
                .any(|child| child.index() >= self.nodes.len())
            {
                return Err(MorphismArenaError::new(format!(
                    "node {index} references an unknown child"
                )));
            }
            match node.kind {
                MorphismNodeKind::Serial => {
                    if children.len() < 2 {
                        return Err(MorphismArenaError::new(format!(
                            "Serial node {index} has fewer than two children"
                        )));
                    }
                    self.boundaries(id)?;
                }
                MorphismNodeKind::Parallel if children.len() < 2 => {
                    return Err(MorphismArenaError::new(format!(
                        "Parallel node {index} has fewer than two children"
                    )));
                }
                MorphismNodeKind::Parallel => {}
                _ if !children.is_empty() => {
                    return Err(MorphismArenaError::new(format!(
                        "leaf node {index} unexpectedly has children"
                    )));
                }
                _ => {}
            }
            if let Some(payload) = node.payload {
                if payload.index() >= self.payloads.len() {
                    return Err(MorphismArenaError::new(format!(
                        "node {index} references an unknown payload"
                    )));
                }
            }
            let payload = node.payload.map(|payload| &self.payloads[payload.index()]);
            let payload_matches_kind = matches!(
                (node.kind, payload),
                (
                    MorphismNodeKind::Atomic,
                    Some(MorphismPayload::Atomic { .. })
                ) | (MorphismNodeKind::Wait, Some(MorphismPayload::Wait))
                    | (
                        MorphismNodeKind::Instantiate,
                        Some(MorphismPayload::Instantiate { .. })
                    )
                    | (
                        MorphismNodeKind::DefinitionRef,
                        Some(MorphismPayload::DefinitionRef { .. })
                    )
                    | (
                        MorphismNodeKind::Serial
                            | MorphismNodeKind::Parallel
                            | MorphismNodeKind::Loop
                            | MorphismNodeKind::SyncPhi,
                        None
                    )
            );
            if !payload_matches_kind {
                return Err(MorphismArenaError::new(format!(
                    "node {index} has a payload inconsistent with its kind"
                )));
            }
            match payload {
                Some(MorphismPayload::Atomic { operation })
                    if operation.index() >= self.operations.len() =>
                {
                    return Err(MorphismArenaError::new(format!(
                        "node {index} references an unknown operation"
                    )));
                }
                Some(MorphismPayload::Instantiate { template, channel })
                    if template.index() >= self.templates.len()
                        || channel.index() >= self.channels.len() =>
                {
                    return Err(MorphismArenaError::new(format!(
                        "node {index} references an unknown template or channel"
                    )));
                }
                Some(MorphismPayload::DefinitionRef { definition })
                    if definition.index() >= self.definitions.len() =>
                {
                    return Err(MorphismArenaError::new(format!(
                        "node {index} references an unknown definition"
                    )));
                }
                _ => {}
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MorphismArenaError(String);

impl MorphismArenaError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for MorphismArenaError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for MorphismArenaError {}

#[derive(Default)]
pub struct MorphismArenaBuilder {
    nodes: Vec<MorphismNode>,
    edges: Vec<MorphismNodeId>,
    boundaries: Vec<BoundaryPolicy>,
    payloads: Vec<MorphismPayload>,
    templates: Vec<MorphismTemplate>,
    definitions: Vec<String>,
    definition_ids: HashMap<String, DefinitionId>,
    operations: Vec<String>,
    operation_ids: HashMap<String, OperationId>,
    channels: Vec<String>,
    channel_ids: HashMap<String, ChannelId>,
    provenance: Vec<NativeProvenance>,
}

impl MorphismArenaBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn intern_provenance(&mut self, provenance: NativeProvenance) -> ProvenanceId {
        let id = ProvenanceId(self.provenance.len() as u32);
        self.provenance.push(provenance);
        id
    }

    pub fn definition_ref(&mut self, definition: &str, provenance: ProvenanceId) -> MorphismNodeId {
        let definition = self.intern_definition(definition);
        let payload = self.push_payload(MorphismPayload::DefinitionRef { definition });
        self.push_leaf(MorphismNodeKind::DefinitionRef, Some(payload), provenance)
    }

    pub fn atomic(&mut self, operation: &str, provenance: ProvenanceId) -> MorphismNodeId {
        let operation = self.intern_operation(operation);
        let payload = self.push_payload(MorphismPayload::Atomic { operation });
        self.push_leaf(MorphismNodeKind::Atomic, Some(payload), provenance)
    }

    pub fn wait(&mut self, provenance: ProvenanceId) -> MorphismNodeId {
        let payload = self.push_payload(MorphismPayload::Wait);
        self.push_leaf(MorphismNodeKind::Wait, Some(payload), provenance)
    }

    pub fn publish_template(&mut self, root: MorphismNodeId) -> MorphismTemplateId {
        assert!(
            root.index() < self.nodes.len(),
            "template root must belong to the builder"
        );
        let id = MorphismTemplateId(self.templates.len() as u32);
        self.templates.push(MorphismTemplate { root });
        id
    }

    pub fn instantiate(
        &mut self,
        template: MorphismTemplateId,
        channel: &str,
        provenance: ProvenanceId,
    ) -> MorphismNodeId {
        assert!(
            template.index() < self.templates.len(),
            "Instantiate template must be published"
        );
        let channel = self.intern_channel(channel);
        let payload = self.push_payload(MorphismPayload::Instantiate { template, channel });
        self.push_leaf(MorphismNodeKind::Instantiate, Some(payload), provenance)
    }

    pub fn serial(
        &mut self,
        children: &[MorphismNodeId],
        boundaries: &[BoundaryPolicy],
        provenance: ProvenanceId,
    ) -> MorphismNodeId {
        assert!(children.len() >= 2, "Serial requires at least two children");
        assert_eq!(boundaries.len() + 1, children.len());
        let mut flattened_children = Vec::new();
        let mut flattened_boundaries = Vec::new();
        for (index, child) in children.iter().copied().enumerate() {
            if index > 0 {
                flattened_boundaries.push(boundaries[index - 1]);
            }
            let node = &self.nodes[child.index()];
            if node.kind == MorphismNodeKind::Serial {
                let start = node.edge_start as usize;
                let end = start + node.edge_count as usize;
                flattened_children.extend_from_slice(&self.edges[start..end]);
                let boundary_start = node.boundary_start as usize;
                flattened_boundaries.extend_from_slice(
                    &self.boundaries[boundary_start..boundary_start + node.edge_count as usize - 1],
                );
            } else {
                flattened_children.push(child);
            }
        }
        self.push_composition(
            MorphismNodeKind::Serial,
            &flattened_children,
            &flattened_boundaries,
            provenance,
        )
    }

    pub fn parallel(
        &mut self,
        children: &[MorphismNodeId],
        provenance: ProvenanceId,
    ) -> MorphismNodeId {
        assert!(
            children.len() >= 2,
            "Parallel requires at least two children"
        );
        let mut flattened = Vec::new();
        for child in children.iter().copied() {
            let node = &self.nodes[child.index()];
            if node.kind == MorphismNodeKind::Parallel {
                let start = node.edge_start as usize;
                let end = start + node.edge_count as usize;
                flattened.extend_from_slice(&self.edges[start..end]);
            } else {
                flattened.push(child);
            }
        }
        self.push_composition(MorphismNodeKind::Parallel, &flattened, &[], provenance)
    }

    pub fn finish(self, root: MorphismNodeId) -> Result<MorphismArena, MorphismArenaError> {
        if root.index() >= self.nodes.len() {
            return Err(MorphismArenaError::new(
                "root does not belong to the builder",
            ));
        }
        let mut reachable = vec![false; self.nodes.len()];
        let mut pending = vec![root];
        pending.extend(self.templates.iter().map(MorphismTemplate::root));
        while let Some(node_id) = pending.pop() {
            if std::mem::replace(&mut reachable[node_id.index()], true) {
                continue;
            }
            let node = &self.nodes[node_id.index()];
            let start = node.edge_start as usize;
            let end = start + node.edge_count as usize;
            pending.extend_from_slice(&self.edges[start..end]);
        }

        let mut remap = vec![None; self.nodes.len()];
        let mut nodes = Vec::new();
        for (old, is_reachable) in reachable.iter().copied().enumerate() {
            if is_reachable {
                remap[old] = Some(MorphismNodeId(nodes.len() as u32));
                nodes.push(self.nodes[old].clone());
            }
        }
        let mut edges = Vec::new();
        let mut boundaries = Vec::new();
        for (old, is_reachable) in reachable.iter().copied().enumerate() {
            if !is_reachable {
                continue;
            }
            let source = &self.nodes[old];
            let edge_start = source.edge_start as usize;
            let edge_end = edge_start + source.edge_count as usize;
            let node = &mut nodes[remap[old].expect("reachable node is remapped").index()];
            node.edge_start = edges.len() as u32;
            edges.extend(
                self.edges[edge_start..edge_end].iter().map(|child| {
                    remap[child.index()].expect("reachable parent has reachable child")
                }),
            );
            node.boundary_start = boundaries.len() as u32;
            if source.kind == MorphismNodeKind::Serial {
                let start = source.boundary_start as usize;
                boundaries.extend_from_slice(
                    &self.boundaries[start..start + source.edge_count as usize - 1],
                );
            }
        }
        let templates = self
            .templates
            .into_iter()
            .map(|template| MorphismTemplate {
                root: remap[template.root.index()].expect("template root is reachable"),
            })
            .collect();
        let arena = MorphismArena {
            root: remap[root.index()].expect("root is reachable"),
            nodes,
            edges,
            boundaries,
            payloads: self.payloads,
            templates,
            definitions: self.definitions,
            operations: self.operations,
            channels: self.channels,
            provenance: self.provenance,
        };
        arena.validate()?;
        Ok(arena)
    }

    fn push_leaf(
        &mut self,
        kind: MorphismNodeKind,
        payload: Option<MorphismPayloadId>,
        provenance: ProvenanceId,
    ) -> MorphismNodeId {
        self.push_node(MorphismNode {
            kind,
            edge_start: self.edges.len() as u32,
            edge_count: 0,
            boundary_start: self.boundaries.len() as u32,
            payload,
            provenance,
        })
    }

    fn push_composition(
        &mut self,
        kind: MorphismNodeKind,
        children: &[MorphismNodeId],
        node_boundaries: &[BoundaryPolicy],
        provenance: ProvenanceId,
    ) -> MorphismNodeId {
        let edge_start = self.edges.len() as u32;
        self.edges.extend_from_slice(children);
        let boundary_start = self.boundaries.len() as u32;
        self.boundaries.extend_from_slice(node_boundaries);
        self.push_node(MorphismNode {
            kind,
            edge_start,
            edge_count: children.len() as u32,
            boundary_start,
            payload: None,
            provenance,
        })
    }

    fn push_node(&mut self, node: MorphismNode) -> MorphismNodeId {
        let id = MorphismNodeId(self.nodes.len() as u32);
        self.nodes.push(node);
        id
    }

    fn push_payload(&mut self, payload: MorphismPayload) -> MorphismPayloadId {
        let id = MorphismPayloadId(self.payloads.len() as u32);
        self.payloads.push(payload);
        id
    }

    fn intern_definition(&mut self, value: &str) -> DefinitionId {
        if let Some(id) = self.definition_ids.get(value) {
            return *id;
        }
        let id = DefinitionId(self.definitions.len() as u32);
        self.definitions.push(value.to_owned());
        self.definition_ids.insert(value.to_owned(), id);
        id
    }

    fn intern_operation(&mut self, value: &str) -> OperationId {
        if let Some(id) = self.operation_ids.get(value) {
            return *id;
        }
        let id = OperationId(self.operations.len() as u32);
        self.operations.push(value.to_owned());
        self.operation_ids.insert(value.to_owned(), id);
        id
    }

    fn intern_channel(&mut self, value: &str) -> ChannelId {
        if let Some(id) = self.channel_ids.get(value) {
            return *id;
        }
        let id = ChannelId(self.channels.len() as u32);
        self.channels.push(value.to_owned());
        self.channel_ids.insert(value.to_owned(), id);
        id
    }
}
