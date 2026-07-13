//! Shared segmented storage for program and service-template DAGs.

use std::any::Any;
use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock, RwLockReadGuard, RwLockWriteGuard};

static NEXT_STORE_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct SegmentId {
    store: u64,
    index: u32,
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct NodeRef {
    store: u64,
    segment: u32,
    index: u32,
}

impl NodeRef {
    pub fn segment(self) -> SegmentId {
        SegmentId {
            store: self.store,
            index: self.segment,
        }
    }

    pub fn local_index(self) -> u32 {
        self.index
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TemplateId {
    store: u64,
    index: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SegmentKind {
    Template,
    Program,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum NodeKind {
    Atomic = 0,
    Wait = 1,
    AutoSerial = 2,
    StrictSerial = 3,
    Parallel = 4,
    Annotate = 5,
    Reference = 6,
    DeferredApply = 7,
    DeferredChannel = 8,
    DeferredBatch = 9,
    Repeat = 10,
    Instantiate = 11,
    /// A restricted-Python call retained for source-HIR specialization.
    SourceCall = 12,
}

impl TryFrom<u8> for NodeKind {
    type Error = ArenaError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Atomic),
            1 => Ok(Self::Wait),
            2 => Ok(Self::AutoSerial),
            3 => Ok(Self::StrictSerial),
            4 => Ok(Self::Parallel),
            5 => Ok(Self::Annotate),
            6 => Ok(Self::Reference),
            7 => Ok(Self::DeferredApply),
            8 => Ok(Self::DeferredChannel),
            9 => Ok(Self::DeferredBatch),
            10 => Ok(Self::Repeat),
            11 => Ok(Self::Instantiate),
            12 => Ok(Self::SourceCall),
            _ => Err(ArenaError::new(format!("unknown node kind {value}"))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Node {
    kind: NodeKind,
    left: Option<NodeRef>,
    right: Option<NodeRef>,
    payload_id: u32,
    channel_mask: u128,
    provenance_id: u32,
}

impl Node {
    pub fn kind(&self) -> NodeKind {
        self.kind
    }

    pub fn children(&self) -> (Option<NodeRef>, Option<NodeRef>) {
        (self.left, self.right)
    }

    pub fn payload_id(&self) -> u32 {
        self.payload_id
    }

    pub fn channel_mask(&self) -> u128 {
        self.channel_mask
    }

    pub fn provenance_id(&self) -> u32 {
        self.provenance_id
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NodeColumns {
    pub kinds: Vec<NodeKind>,
    pub left: Vec<Option<NodeRef>>,
    pub right: Vec<Option<NodeRef>>,
    pub payload_ids: Vec<u32>,
    pub channel_masks: Vec<u128>,
    pub provenance_ids: Vec<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArenaError(String);

impl ArenaError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for ArenaError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for ArenaError {}

#[derive(Clone)]
struct PinnedOwner(Arc<dyn Any + Send + Sync>);

impl PinnedOwner {
    fn new<T: Any + Send + Sync>(owner: Arc<T>) -> Self {
        Self(owner)
    }

    fn downcast<T: Any + Send + Sync>(&self) -> Option<Arc<T>> {
        Arc::clone(&self.0).downcast().ok()
    }
}

impl std::fmt::Debug for PinnedOwner {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("PinnedOwner(..)")
    }
}

#[derive(Clone, Debug)]
struct Template {
    root: NodeRef,
    #[allow(dead_code)]
    schema_id: u32,
    owner: PinnedOwner,
}

#[derive(Clone, Debug)]
struct TemplateInstance {
    template: TemplateId,
    #[allow(dead_code)]
    binding_environment_id: u32,
}

#[derive(Debug)]
struct Segment {
    kind: SegmentKind,
    frozen: bool,
    nodes: Vec<Node>,
}

#[derive(Debug, Default)]
struct StoreInner {
    segments: Vec<Segment>,
    templates: Vec<Template>,
    instances: Vec<TemplateInstance>,
}

#[derive(Clone, Debug)]
pub struct ArenaStore {
    id: u64,
    inner: Arc<RwLock<StoreInner>>,
}

impl Default for ArenaStore {
    fn default() -> Self {
        Self::new()
    }
}

impl ArenaStore {
    pub fn new() -> Self {
        Self {
            id: NEXT_STORE_ID.fetch_add(1, Ordering::Relaxed),
            inner: Arc::new(RwLock::new(StoreInner::default())),
        }
    }

    fn read(&self) -> RwLockReadGuard<'_, StoreInner> {
        self.inner.read().unwrap_or_else(|error| error.into_inner())
    }

    fn write(&self) -> RwLockWriteGuard<'_, StoreInner> {
        self.inner
            .write()
            .unwrap_or_else(|error| error.into_inner())
    }

    pub fn create_segment(&self, kind: SegmentKind) -> SegmentId {
        let mut inner = self.write();
        let index = inner.segments.len() as u32;
        inner.segments.push(Segment {
            kind,
            frozen: false,
            nodes: Vec::new(),
        });
        SegmentId {
            store: self.id,
            index,
        }
    }

    pub fn atomic(
        &self,
        segment: SegmentId,
        payload_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        self.append(
            segment,
            Node {
                kind: NodeKind::Atomic,
                left: None,
                right: None,
                payload_id,
                channel_mask,
                provenance_id,
            },
        )
    }

    pub fn wait(
        &self,
        segment: SegmentId,
        expression_id: u32,
        provenance_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        self.append(
            segment,
            Node {
                kind: NodeKind::Wait,
                left: None,
                right: None,
                payload_id: expression_id,
                channel_mask: 0,
                provenance_id,
            },
        )
    }

    /// Append an unresolved Morphism-producing call from source HIR.
    ///
    /// The payload and provenance IDs both refer to the owning `SequenceHir`.
    /// A zero channel mask means that service resolution has not run yet.
    pub fn source_call(
        &self,
        segment: SegmentId,
        expression_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        self.append(
            segment,
            Node {
                kind: NodeKind::SourceCall,
                left: None,
                right: None,
                payload_id: expression_id,
                channel_mask: 0,
                provenance_id: expression_id,
            },
        )
    }

    pub fn compose(
        &self,
        segment: SegmentId,
        kind: NodeKind,
        left: NodeRef,
        right: NodeRef,
        provenance_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        if !matches!(
            kind,
            NodeKind::AutoSerial | NodeKind::StrictSerial | NodeKind::Parallel
        ) {
            return Err(ArenaError::new(format!(
                "{kind:?} is not a composition node kind"
            )));
        }
        let channel_mask = {
            let inner = self.read();
            let left_node = self.node_from(&inner, left)?;
            let right_node = self.node_from(&inner, right)?;
            self.validate_template_children(&inner, segment, [left, right])?;
            left_node.channel_mask | right_node.channel_mask
        };
        self.append(
            segment,
            Node {
                kind,
                left: Some(left),
                right: Some(right),
                payload_id: 0,
                channel_mask,
                provenance_id,
            },
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn append_raw(
        &self,
        segment: SegmentId,
        kind: NodeKind,
        left: Option<NodeRef>,
        right: Option<NodeRef>,
        payload_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        if kind == NodeKind::Instantiate {
            return Err(ArenaError::new(
                "instantiate nodes require a registered template",
            ));
        }
        Self::validate_node_shape(kind, left, right)?;
        {
            let inner = self.read();
            for child in [left, right].into_iter().flatten() {
                self.node_from(&inner, child)?;
            }
            if let (Some(left), Some(right)) = (left, right) {
                self.validate_template_children(&inner, segment, [left, right])?;
            } else if self.segment_from(&inner, segment)?.kind == SegmentKind::Template {
                for child in [left, right].into_iter().flatten() {
                    if self.segment_from(&inner, child.segment())?.kind != SegmentKind::Template {
                        return Err(ArenaError::new(
                            "template nodes cannot depend on program segments",
                        ));
                    }
                }
            }
        }
        self.append(
            segment,
            Node {
                kind,
                left,
                right,
                payload_id,
                channel_mask,
                provenance_id,
            },
        )
    }

    pub fn publish_template(
        &self,
        root: NodeRef,
        schema_id: u32,
    ) -> Result<TemplateId, ArenaError> {
        self.publish_template_with_owner(root, schema_id, Arc::new(()))
    }

    /// Publish a template while pinning the typed IR that interprets its
    /// payload IDs for as long as the template remains in this store.
    pub fn publish_template_with_owner<T: Any + Send + Sync>(
        &self,
        root: NodeRef,
        schema_id: u32,
        owner: Arc<T>,
    ) -> Result<TemplateId, ArenaError> {
        let mut inner = self.write();
        self.node_from(&inner, root)?;
        let segment = self.segment_mut_from(&mut inner, root.segment())?;
        if segment.kind != SegmentKind::Template {
            return Err(ArenaError::new(
                "only template segments can be published as templates",
            ));
        }
        segment.frozen = true;
        let template = TemplateId {
            store: self.id,
            index: inner.templates.len() as u32,
        };
        inner.templates.push(Template {
            root,
            schema_id,
            owner: PinnedOwner::new(owner),
        });
        Ok(template)
    }

    pub fn template_owner<T: Any + Send + Sync>(
        &self,
        template: TemplateId,
    ) -> Result<Option<Arc<T>>, ArenaError> {
        let inner = self.read();
        Ok(self.template_from(&inner, template)?.owner.downcast())
    }

    pub fn instantiate(
        &self,
        segment: SegmentId,
        template: TemplateId,
        binding_environment_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> Result<NodeRef, ArenaError> {
        let mut inner = self.write();
        self.template_from(&inner, template)?;
        let node_index = self.mutable_segment_from(&inner, segment)?.nodes.len() as u32;
        let payload_id = inner.instances.len() as u32;
        inner.instances.push(TemplateInstance {
            template,
            binding_environment_id,
        });
        let node_ref = NodeRef {
            store: self.id,
            segment: segment.index,
            index: node_index,
        };
        self.segment_mut_from(&mut inner, segment)?
            .nodes
            .push(Node {
                kind: NodeKind::Instantiate,
                left: None,
                right: None,
                payload_id,
                channel_mask,
                provenance_id,
            });
        Ok(node_ref)
    }

    pub fn freeze(&self, root: NodeRef) -> Result<FrozenProgram, ArenaError> {
        self.freeze_with_owner(root, Arc::new(()))
    }

    /// Freeze a root while pinning the typed IR that interprets its payloads.
    pub fn freeze_with_owner<T: Any + Send + Sync>(
        &self,
        root: NodeRef,
        owner: Arc<T>,
    ) -> Result<FrozenProgram, ArenaError> {
        self.node(root)?;
        Ok(FrozenProgram {
            store: self.clone(),
            root,
            owner: PinnedOwner::new(owner),
        })
    }

    pub fn node(&self, node_ref: NodeRef) -> Result<Node, ArenaError> {
        Ok(self.node_from(&self.read(), node_ref)?.clone())
    }

    pub fn segment_node_count(&self, segment: SegmentId) -> Result<usize, ArenaError> {
        Ok(self.segment_from(&self.read(), segment)?.nodes.len())
    }

    pub fn total_node_count(&self) -> usize {
        self.read()
            .segments
            .iter()
            .map(|segment| segment.nodes.len())
            .sum()
    }

    pub fn export_segment(&self, segment: SegmentId) -> Result<NodeColumns, ArenaError> {
        let inner = self.read();
        let nodes = &self.segment_from(&inner, segment)?.nodes;
        Ok(NodeColumns {
            kinds: nodes.iter().map(|node| node.kind).collect(),
            left: nodes.iter().map(|node| node.left).collect(),
            right: nodes.iter().map(|node| node.right).collect(),
            payload_ids: nodes.iter().map(|node| node.payload_id).collect(),
            channel_masks: nodes.iter().map(|node| node.channel_mask).collect(),
            provenance_ids: nodes.iter().map(|node| node.provenance_id).collect(),
        })
    }

    pub fn node_channel_mask(&self, node_ref: NodeRef) -> Result<u128, ArenaError> {
        Ok(self.node(node_ref)?.channel_mask)
    }

    pub fn local_node_ref(
        &self,
        segment: SegmentId,
        local_index: u32,
    ) -> Result<NodeRef, ArenaError> {
        let node_ref = NodeRef {
            store: self.id,
            segment: segment.index,
            index: local_index,
        };
        self.node(node_ref)?;
        Ok(node_ref)
    }

    fn append(&self, segment: SegmentId, node: Node) -> Result<NodeRef, ArenaError> {
        let mut inner = self.write();
        let target = self.segment_mut_from(&mut inner, segment)?;
        if target.frozen {
            return Err(ArenaError::new("cannot append to a frozen segment"));
        }
        let node_ref = NodeRef {
            store: self.id,
            segment: segment.index,
            index: target.nodes.len() as u32,
        };
        target.nodes.push(node);
        Ok(node_ref)
    }

    fn segment_from<'a>(
        &self,
        inner: &'a StoreInner,
        segment: SegmentId,
    ) -> Result<&'a Segment, ArenaError> {
        if segment.store != self.id {
            return Err(ArenaError::new("segment belongs to another arena store"));
        }
        inner
            .segments
            .get(segment.index as usize)
            .ok_or_else(|| ArenaError::new("unknown arena segment"))
    }

    fn segment_mut_from<'a>(
        &self,
        inner: &'a mut StoreInner,
        segment: SegmentId,
    ) -> Result<&'a mut Segment, ArenaError> {
        if segment.store != self.id {
            return Err(ArenaError::new("segment belongs to another arena store"));
        }
        inner
            .segments
            .get_mut(segment.index as usize)
            .ok_or_else(|| ArenaError::new("unknown arena segment"))
    }

    fn mutable_segment_from<'a>(
        &self,
        inner: &'a StoreInner,
        segment: SegmentId,
    ) -> Result<&'a Segment, ArenaError> {
        let segment = self.segment_from(inner, segment)?;
        if segment.frozen {
            return Err(ArenaError::new("cannot append to a frozen segment"));
        }
        Ok(segment)
    }

    fn node_from<'a>(
        &self,
        inner: &'a StoreInner,
        node_ref: NodeRef,
    ) -> Result<&'a Node, ArenaError> {
        let segment = self.segment_from(inner, node_ref.segment())?;
        segment
            .nodes
            .get(node_ref.index as usize)
            .ok_or_else(|| ArenaError::new("unknown arena node"))
    }

    fn template_from<'a>(
        &self,
        inner: &'a StoreInner,
        template: TemplateId,
    ) -> Result<&'a Template, ArenaError> {
        if template.store != self.id {
            return Err(ArenaError::new("template belongs to another arena store"));
        }
        inner
            .templates
            .get(template.index as usize)
            .ok_or_else(|| ArenaError::new("unknown template"))
    }

    fn validate_template_children(
        &self,
        inner: &StoreInner,
        target: SegmentId,
        children: [NodeRef; 2],
    ) -> Result<(), ArenaError> {
        if self.segment_from(inner, target)?.kind != SegmentKind::Template {
            return Ok(());
        }
        for child in children {
            if self.segment_from(inner, child.segment())?.kind != SegmentKind::Template {
                return Err(ArenaError::new(
                    "template nodes cannot depend on program segments",
                ));
            }
        }
        Ok(())
    }

    fn validate_node_shape(
        kind: NodeKind,
        left: Option<NodeRef>,
        right: Option<NodeRef>,
    ) -> Result<(), ArenaError> {
        let valid = match kind {
            NodeKind::Atomic
            | NodeKind::Wait
            | NodeKind::Reference
            | NodeKind::DeferredChannel
            | NodeKind::SourceCall => left.is_none() && right.is_none(),
            NodeKind::AutoSerial | NodeKind::StrictSerial | NodeKind::Parallel => {
                left.is_some() && right.is_some()
            }
            NodeKind::Annotate
            | NodeKind::DeferredApply
            | NodeKind::DeferredBatch
            | NodeKind::Repeat => left.is_some() && right.is_none(),
            NodeKind::Instantiate => false,
        };
        if valid {
            Ok(())
        } else {
            Err(ArenaError::new(format!(
                "invalid children for {kind:?}: left={left:?}, right={right:?}"
            )))
        }
    }
}

#[derive(Clone, Debug)]
pub struct FrozenProgram {
    store: ArenaStore,
    root: NodeRef,
    owner: PinnedOwner,
}

impl FrozenProgram {
    pub fn root(&self) -> NodeRef {
        self.root
    }

    pub fn owner<T: Any + Send + Sync>(&self) -> Option<Arc<T>> {
        self.owner.downcast()
    }

    pub fn reachable_storage_node_count(&self) -> Result<usize, ArenaError> {
        Ok(self.reachable_stats()?.0)
    }

    pub fn template_instance_count(&self) -> Result<usize, ArenaError> {
        Ok(self.reachable_stats()?.1)
    }

    fn reachable_stats(&self) -> Result<(usize, usize), ArenaError> {
        let inner = self.store.read();
        let mut seen = HashSet::new();
        let mut stack = vec![self.root];
        let mut template_instances = 0;
        while let Some(node_ref) = stack.pop() {
            if !seen.insert(node_ref) {
                continue;
            }
            let node = self.store.node_from(&inner, node_ref)?;
            if let Some(left) = node.left {
                stack.push(left);
            }
            if let Some(right) = node.right {
                stack.push(right);
            }
            if node.kind == NodeKind::Instantiate {
                template_instances += 1;
                let instance = inner
                    .instances
                    .get(node.payload_id as usize)
                    .ok_or_else(|| ArenaError::new("template instance payload is missing"))?;
                let template = self.store.template_from(&inner, instance.template)?;
                stack.push(template.root);
            }
        }
        Ok((seen.len(), template_instances))
    }
}
