//! Elaboration from validated registered source into target-independent frontend IR.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use catseq_core::control::{
    ControlArena, ControlBuildError, ControlBuilder, ControlSummary, MorphismAlgebra, MorphismTerm,
    OriginContribution, OriginId, OriginMap as ControlOriginMap, OriginRole,
};

use crate::registered_modules::RegisteredDefinitionRole;
use crate::source_hir::{
    DependencyRole, DurationUnit, ResolvedCallTarget, SemanticFact, SourceAnchor, SourceBinding,
    SourceHirKind, SourceHirNode, SourceIntrinsic, SourceLiteral, SourceValueOperation,
    TypedSourceHir, ValueAvailability, ValueType,
};
use crate::typed::{ParameterSemantics, TypedCheckReport, TypedDefinition};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct FrontendValueId(u32);

impl FrontendValueId {
    pub const fn index(self) -> usize {
        self.0 as usize
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrontendLiteral {
    None,
    Bool(bool),
    Int32(i32),
    Float64(u64),
    String(String),
}

impl From<&SourceLiteral> for FrontendLiteral {
    fn from(value: &SourceLiteral) -> Self {
        match value {
            SourceLiteral::None => Self::None,
            SourceLiteral::Bool(value) => Self::Bool(*value),
            SourceLiteral::Int32(value) => Self::Int32(*value),
            SourceLiteral::Float64(value) => Self::Float64(*value),
            SourceLiteral::String(value) => Self::String(value.clone()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrontendValueKind {
    Literal(FrontendLiteral),
    SealedExternal {
        name: String,
        value: FrontendLiteral,
    },
    Cycles,
    ScaleDuration(DurationUnit),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrontendValueNode {
    kind: FrontendValueKind,
    value_type: ValueType,
    availability: ValueAvailability,
    dependency_roles: Vec<DependencyRole>,
    children: Vec<FrontendValueId>,
}

impl FrontendValueNode {
    pub const fn kind(&self) -> &FrontendValueKind {
        &self.kind
    }

    pub const fn value_type(&self) -> &ValueType {
        &self.value_type
    }

    pub const fn availability(&self) -> ValueAvailability {
        self.availability
    }

    pub fn dependency_roles(&self) -> &[DependencyRole] {
        &self.dependency_roles
    }

    pub fn children(&self) -> &[FrontendValueId] {
        &self.children
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrontendValueGraph {
    nodes: Vec<FrontendValueNode>,
}

impl FrontendValueGraph {
    pub fn nodes(&self) -> &[FrontendValueNode] {
        &self.nodes
    }

    pub fn node(&self, id: FrontendValueId) -> Option<&FrontendValueNode> {
        self.nodes.get(id.index())
    }

    pub fn exact_cycle_delta(&self, id: FrontendValueId) -> Option<i64> {
        let node = self.node(id)?;
        match &node.kind {
            FrontendValueKind::Cycles => {
                let [count] = node.children.as_slice() else {
                    return None;
                };
                self.exact_int32(*count).map(i64::from)
            }
            FrontendValueKind::ScaleDuration(_) => {
                let [scalar] = node.children.as_slice() else {
                    return None;
                };
                self.is_exact_zero(*scalar).then_some(0)
            }
            _ => None,
        }
    }

    fn exact_int32(&self, id: FrontendValueId) -> Option<i32> {
        let node = self.node(id)?;
        if node.availability != ValueAvailability::Compile {
            return None;
        }
        match &node.kind {
            FrontendValueKind::Literal(FrontendLiteral::Int32(value))
            | FrontendValueKind::SealedExternal {
                value: FrontendLiteral::Int32(value),
                ..
            } => Some(*value),
            _ => None,
        }
    }

    fn is_exact_zero(&self, id: FrontendValueId) -> bool {
        let Some(node) = self.node(id) else {
            return false;
        };
        if node.availability != ValueAvailability::Compile {
            return false;
        }
        match &node.kind {
            FrontendValueKind::Literal(FrontendLiteral::Int32(0))
            | FrontendValueKind::SealedExternal {
                value: FrontendLiteral::Int32(0),
                ..
            } => true,
            FrontendValueKind::Literal(FrontendLiteral::Float64(value))
            | FrontendValueKind::SealedExternal {
                value: FrontendLiteral::Float64(value),
                ..
            } => f64::from_bits(*value) == 0.0,
            _ => false,
        }
    }

    fn validate(&self) -> Result<(), &'static str> {
        for (index, node) in self.nodes.iter().enumerate() {
            if node.children.iter().any(|child| child.index() >= index) {
                return Err("Value Expression graph is not an ordered DAG");
            }
            match &node.kind {
                FrontendValueKind::Literal(_) | FrontendValueKind::SealedExternal { .. }
                    if !node.children.is_empty() =>
                {
                    return Err("Value Expression leaf has children");
                }
                FrontendValueKind::Cycles
                    if node.value_type != ValueType::Duration
                        || node.children.len() != 1
                        || self
                            .node(node.children[0])
                            .map(FrontendValueNode::value_type)
                            != Some(&ValueType::Int32) =>
                {
                    return Err("cycles Value Expression has an invalid shape");
                }
                FrontendValueKind::ScaleDuration(_)
                    if node.value_type != ValueType::Duration
                        || node.children.len() != 1
                        || !matches!(
                            self.node(node.children[0])
                                .map(FrontendValueNode::value_type),
                            Some(ValueType::Int32 | ValueType::Float64)
                        ) =>
                {
                    return Err("physical Duration Value Expression has an invalid shape");
                }
                _ => {}
            }
        }
        Ok(())
    }
}

#[derive(Default)]
struct ValueGraphBuilder {
    nodes: Vec<FrontendValueNode>,
    origins: Vec<Vec<OriginContribution>>,
}

impl ValueGraphBuilder {
    fn push(
        &mut self,
        kind: FrontendValueKind,
        value_type: ValueType,
        availability: ValueAvailability,
        dependency_roles: Vec<DependencyRole>,
        children: Vec<FrontendValueId>,
        origin: OriginContribution,
    ) -> FrontendValueId {
        let id = FrontendValueId(self.nodes.len() as u32);
        self.nodes.push(FrontendValueNode {
            kind,
            value_type,
            availability,
            dependency_roles,
            children,
        });
        self.origins.push(vec![origin]);
        id
    }

    fn record(&mut self, id: FrontendValueId, origin: OriginContribution) {
        self.origins[id.index()].push(origin);
    }

    fn node(&self, id: FrontendValueId) -> &FrontendValueNode {
        &self.nodes[id.index()]
    }

    fn is_exact_zero(&self, id: FrontendValueId) -> bool {
        let node = &self.nodes[id.index()];
        if node.availability != ValueAvailability::Compile {
            return false;
        }
        match &node.kind {
            FrontendValueKind::Literal(FrontendLiteral::Int32(0))
            | FrontendValueKind::SealedExternal {
                value: FrontendLiteral::Int32(0),
                ..
            } => true,
            FrontendValueKind::Literal(FrontendLiteral::Float64(value))
            | FrontendValueKind::SealedExternal {
                value: FrontendLiteral::Float64(value),
                ..
            } => f64::from_bits(*value) == 0.0,
            _ => false,
        }
    }

    fn exact_cycle_delta(&self, id: FrontendValueId) -> Option<i64> {
        let node = self.nodes.get(id.index())?;
        match &node.kind {
            FrontendValueKind::Cycles => {
                let [count] = node.children.as_slice() else {
                    return None;
                };
                let count = self.nodes.get(count.index())?;
                if count.availability != ValueAvailability::Compile {
                    return None;
                }
                match &count.kind {
                    FrontendValueKind::Literal(FrontendLiteral::Int32(value))
                    | FrontendValueKind::SealedExternal {
                        value: FrontendLiteral::Int32(value),
                        ..
                    } => Some(i64::from(*value)),
                    _ => None,
                }
            }
            FrontendValueKind::ScaleDuration(_) => {
                let [scalar] = node.children.as_slice() else {
                    return None;
                };
                self.is_exact_zero(*scalar).then_some(0)
            }
            _ => None,
        }
    }

    fn all_origins(&self, id: FrontendValueId) -> Vec<OriginContribution> {
        let mut output = Vec::new();
        let mut visited = BTreeSet::new();
        let mut pending = vec![id];
        while let Some(value) = pending.pop() {
            if !visited.insert(value) {
                continue;
            }
            output.extend(self.origins[value.index()].iter().copied());
            pending.extend(self.nodes[value.index()].children.iter().rev().copied());
        }
        output
    }

    fn finish_reachable(
        self,
        morphisms: &mut FrontendMorphismGraph,
    ) -> Result<(FrontendValueGraph, Vec<Vec<OriginContribution>>), &'static str> {
        let mut reachable = BTreeSet::new();
        let mut pending = morphisms
            .nodes
            .iter()
            .filter_map(|node| match node {
                FrontendMorphismNode::Wait(duration) => Some(*duration),
                FrontendMorphismNode::Id | FrontendMorphismNode::Serial { .. } => None,
            })
            .collect::<Vec<_>>();
        while let Some(id) = pending.pop() {
            if !reachable.insert(id) {
                continue;
            }
            let node = self
                .nodes
                .get(id.index())
                .ok_or("Morphism references an unknown Value Expression")?;
            pending.extend(node.children.iter().copied());
        }

        let mut remap = BTreeMap::new();
        for old in reachable.iter().copied() {
            remap.insert(old, FrontendValueId(remap.len() as u32));
        }
        let mut nodes = Vec::with_capacity(reachable.len());
        let mut origins = Vec::with_capacity(reachable.len());
        for old in reachable {
            let mut node = self.nodes[old.index()].clone();
            node.children = node.children.iter().map(|child| remap[child]).collect();
            nodes.push(node);
            origins.push(self.origins[old.index()].clone());
        }
        for node in &mut morphisms.nodes {
            if let FrontendMorphismNode::Wait(duration) = node {
                *duration = remap[duration];
            }
        }

        let graph = FrontendValueGraph { nodes };
        graph.validate()?;
        Ok((graph, origins))
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct FrontendMorphismId(u32);

impl FrontendMorphismId {
    pub const fn index(self) -> usize {
        self.0 as usize
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrontendMorphismNode {
    Id,
    Wait(FrontendValueId),
    Serial { edge_start: u32, edge_count: u32 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrontendMorphismGraph {
    root: FrontendMorphismId,
    nodes: Vec<FrontendMorphismNode>,
    edges: Vec<FrontendMorphismId>,
}

impl FrontendMorphismGraph {
    pub const fn root(&self) -> FrontendMorphismId {
        self.root
    }

    pub fn nodes(&self) -> &[FrontendMorphismNode] {
        &self.nodes
    }

    pub fn edges(&self) -> &[FrontendMorphismId] {
        &self.edges
    }

    pub fn node(&self, id: FrontendMorphismId) -> Option<&FrontendMorphismNode> {
        self.nodes.get(id.index())
    }

    pub fn children(&self, id: FrontendMorphismId) -> Option<&[FrontendMorphismId]> {
        let FrontendMorphismNode::Serial {
            edge_start,
            edge_count,
        } = self.node(id)?
        else {
            return Some(&[]);
        };
        let start = *edge_start as usize;
        let end = start.checked_add(*edge_count as usize)?;
        self.edges.get(start..end)
    }

    fn validate(&self, values: &FrontendValueGraph) -> Result<(), &'static str> {
        if self.node(self.root).is_none() {
            return Err("Morphism graph has an unknown root");
        }
        let mut covered_edges = vec![false; self.edges.len()];
        for (index, node) in self.nodes.iter().enumerate() {
            let FrontendMorphismNode::Serial {
                edge_start,
                edge_count,
            } = node
            else {
                continue;
            };
            if *edge_count < 2 {
                return Err("Serial Morphism has fewer than two children");
            }
            let start = *edge_start as usize;
            let end = start
                .checked_add(*edge_count as usize)
                .ok_or("Morphism graph edge range overflows")?;
            let Some(covered) = covered_edges.get_mut(start..end) else {
                return Err("Morphism graph has an invalid edge range");
            };
            if covered.iter().any(|edge| *edge) {
                return Err("Morphism graph edge ranges overlap");
            }
            covered.fill(true);
            if self.children(FrontendMorphismId(index as u32)).is_none() {
                return Err("Morphism graph has an invalid edge range");
            }
        }
        if covered_edges.iter().any(|edge| !*edge) {
            return Err("Morphism graph contains unowned edges");
        }
        let mut reachable = BTreeSet::new();
        let mut pending = vec![self.root];
        while let Some(id) = pending.pop() {
            if !reachable.insert(id) {
                continue;
            }
            match self.node(id).ok_or("Morphism graph has an unknown child")? {
                FrontendMorphismNode::Id => {}
                FrontendMorphismNode::Wait(duration) => {
                    if values.node(*duration).map(FrontendValueNode::value_type)
                        != Some(&ValueType::Duration)
                    {
                        return Err("Wait references a non-Duration value");
                    }
                }
                FrontendMorphismNode::Serial { .. } => {
                    for child in self
                        .children(id)
                        .ok_or("Morphism graph has an invalid edge range")?
                    {
                        match self.node(*child) {
                            Some(
                                FrontendMorphismNode::Id | FrontendMorphismNode::Serial { .. },
                            ) => {
                                return Err("Serial Morphism is not flat and unit-free");
                            }
                            Some(FrontendMorphismNode::Wait(_)) => pending.push(*child),
                            None => return Err("Morphism graph has an unknown child"),
                        }
                    }
                }
            }
        }
        if reachable.len() != self.nodes.len() {
            return Err("Morphism graph contains unreachable nodes");
        }
        Ok(())
    }

    fn exact_cycle_delta(
        &self,
        id: FrontendMorphismId,
        values: &FrontendValueGraph,
    ) -> Option<i64> {
        match self.node(id)? {
            FrontendMorphismNode::Id => Some(0),
            FrontendMorphismNode::Wait(duration) => values.exact_cycle_delta(*duration),
            FrontendMorphismNode::Serial { .. } => {
                self.children(id)?.iter().try_fold(0_i64, |sum, child| {
                    let FrontendMorphismNode::Wait(duration) = self.node(*child)? else {
                        return None;
                    };
                    sum.checked_add(values.exact_cycle_delta(*duration)?)
                })
            }
        }
    }
}

#[derive(Default)]
struct MorphismGraphBuilder {
    nodes: Vec<FrontendMorphismNode>,
    edges: Vec<FrontendMorphismId>,
    origins: Vec<Vec<OriginContribution>>,
    edge_boundaries: Vec<Vec<OriginContribution>>,
}

impl MorphismGraphBuilder {
    fn id(&mut self, origin: OriginContribution) -> FrontendMorphismId {
        self.push_leaf(FrontendMorphismNode::Id, vec![origin])
    }

    fn wait(
        &mut self,
        duration: FrontendValueId,
        origin: OriginContribution,
    ) -> FrontendMorphismId {
        self.push_leaf(FrontendMorphismNode::Wait(duration), vec![origin])
    }

    fn record(&mut self, id: FrontendMorphismId, origin: OriginContribution) {
        self.origins[id.index()].push(origin);
    }

    fn serial(
        &mut self,
        left: FrontendMorphismId,
        right: FrontendMorphismId,
        operator: OriginContribution,
    ) -> FrontendMorphismId {
        let left_is_id = matches!(self.nodes[left.index()], FrontendMorphismNode::Id);
        let right_is_id = matches!(self.nodes[right.index()], FrontendMorphismNode::Id);
        if left_is_id {
            let mut dropped = self.origins[left.index()].clone();
            dropped.push(operator);
            dropped.extend(self.origins[right.index()].iter().copied());
            self.origins[right.index()] = dropped;
            return right;
        }
        if right_is_id {
            let right_origins = self.origins[right.index()].clone();
            self.origins[left.index()].push(operator);
            self.origins[left.index()].extend(right_origins);
            return left;
        }

        let (mut children, mut boundaries, mut origins) = self.serial_parts(left);
        let (right_children, right_boundaries, right_origins) = self.serial_parts(right);
        boundaries.push(vec![operator]);
        boundaries.extend(right_boundaries);
        children.extend(right_children);
        origins.extend(right_origins);
        self.push_serial(children, origins, boundaries)
    }

    fn serial_parts(
        &self,
        id: FrontendMorphismId,
    ) -> (
        Vec<FrontendMorphismId>,
        Vec<Vec<OriginContribution>>,
        Vec<OriginContribution>,
    ) {
        match &self.nodes[id.index()] {
            FrontendMorphismNode::Serial {
                edge_start,
                edge_count,
            } => {
                let start = *edge_start as usize;
                let end = start + *edge_count as usize;
                (
                    self.edges[start..end].to_vec(),
                    self.edge_boundaries[start + 1..end].to_vec(),
                    self.origins[id.index()].clone(),
                )
            }
            FrontendMorphismNode::Id => unreachable!("identity is handled before flattening"),
            FrontendMorphismNode::Wait(_) => (vec![id], Vec::new(), Vec::new()),
        }
    }

    fn push_leaf(
        &mut self,
        node: FrontendMorphismNode,
        origins: Vec<OriginContribution>,
    ) -> FrontendMorphismId {
        debug_assert!(!matches!(node, FrontendMorphismNode::Serial { .. }));
        let id = FrontendMorphismId(self.nodes.len() as u32);
        self.nodes.push(node);
        self.origins.push(origins);
        id
    }

    fn push_serial(
        &mut self,
        children: Vec<FrontendMorphismId>,
        origins: Vec<OriginContribution>,
        boundaries: Vec<Vec<OriginContribution>>,
    ) -> FrontendMorphismId {
        assert!(children.len() >= 2, "Serial requires at least two children");
        assert_eq!(boundaries.len() + 1, children.len());
        let edge_start = self.edges.len() as u32;
        let edge_count = children.len() as u32;
        self.edges.extend(children);
        self.edge_boundaries.push(Vec::new());
        self.edge_boundaries.extend(boundaries);
        let id = FrontendMorphismId(self.nodes.len() as u32);
        self.nodes.push(FrontendMorphismNode::Serial {
            edge_start,
            edge_count,
        });
        self.origins.push(origins);
        id
    }

    fn children(&self, id: FrontendMorphismId) -> &[FrontendMorphismId] {
        match &self.nodes[id.index()] {
            FrontendMorphismNode::Serial {
                edge_start,
                edge_count,
            } => {
                let start = *edge_start as usize;
                &self.edges[start..start + *edge_count as usize]
            }
            FrontendMorphismNode::Id | FrontendMorphismNode::Wait(_) => &[],
        }
    }

    fn finish(
        self,
        root: FrontendMorphismId,
    ) -> Result<(FrontendMorphismGraph, MorphismOrigins, FrontendMorphismId), &'static str> {
        if root.index() >= self.nodes.len() {
            return Err("Morphism root does not belong to the builder");
        }
        let mut reachable = BTreeSet::new();
        let mut pending = vec![root];
        while let Some(id) = pending.pop() {
            if !reachable.insert(id) {
                continue;
            }
            if matches!(self.nodes[id.index()], FrontendMorphismNode::Serial { .. }) {
                pending.extend(self.children(id).iter().copied());
            }
        }
        let mut remap = BTreeMap::new();
        for old in reachable.iter().copied() {
            remap.insert(old, FrontendMorphismId(remap.len() as u32));
        }
        let mut nodes = Vec::with_capacity(reachable.len());
        let mut edges = Vec::new();
        let mut origins = Vec::with_capacity(reachable.len());
        let mut origin_edge_ranges = Vec::with_capacity(reachable.len());
        let mut edge_boundaries = Vec::new();
        for old in reachable.iter().copied() {
            let node = match &self.nodes[old.index()] {
                FrontendMorphismNode::Id => FrontendMorphismNode::Id,
                FrontendMorphismNode::Wait(duration) => FrontendMorphismNode::Wait(*duration),
                FrontendMorphismNode::Serial {
                    edge_start,
                    edge_count,
                } => {
                    let source_start = *edge_start as usize;
                    let source_end = source_start + *edge_count as usize;
                    let new_edge_start = edges.len() as u32;
                    edges.extend(
                        self.edges[source_start..source_end]
                            .iter()
                            .map(|child| remap[child]),
                    );
                    edge_boundaries
                        .extend_from_slice(&self.edge_boundaries[source_start..source_end]);
                    FrontendMorphismNode::Serial {
                        edge_start: new_edge_start,
                        edge_count: *edge_count,
                    }
                }
            };
            origin_edge_ranges.push(match &node {
                FrontendMorphismNode::Serial {
                    edge_start,
                    edge_count,
                } => Some((*edge_start, *edge_count)),
                FrontendMorphismNode::Id | FrontendMorphismNode::Wait(_) => None,
            });
            nodes.push(node);
            origins.push(self.origins[old.index()].clone());
        }
        let root = remap[&root];
        Ok((
            FrontendMorphismGraph { root, nodes, edges },
            MorphismOrigins {
                nodes: origins,
                edge_ranges: origin_edge_ranges,
                edge_boundaries,
            },
            root,
        ))
    }
}

#[derive(Clone, Debug)]
struct MorphismOrigins {
    nodes: Vec<Vec<OriginContribution>>,
    edge_ranges: Vec<Option<(u32, u32)>>,
    edge_boundaries: Vec<Vec<OriginContribution>>,
}

#[derive(Clone, Debug)]
pub struct FrontendOriginMap {
    anchors: Vec<SourceAnchor>,
    entry: Vec<OriginContribution>,
    values: Vec<Vec<OriginContribution>>,
    morphisms: MorphismOrigins,
    control: ControlOriginMap,
}

impl FrontendOriginMap {
    pub fn anchor(&self, id: OriginId) -> Option<&SourceAnchor> {
        self.anchors.get(id.index())
    }

    pub fn entry(&self) -> &[OriginContribution] {
        &self.entry
    }

    pub fn value(&self, id: FrontendValueId) -> &[OriginContribution] {
        &self.values[id.index()]
    }

    pub fn morphism(&self, id: FrontendMorphismId) -> &[OriginContribution] {
        &self.morphisms.nodes[id.index()]
    }

    pub fn morphism_boundary(
        &self,
        serial: FrontendMorphismId,
        boundary_index: usize,
    ) -> &[OriginContribution] {
        let (edge_start, edge_count) = self.morphisms.edge_ranges[serial.index()]
            .expect("only Serial Morphisms have boundary origins");
        let edge_offset = boundary_index
            .checked_add(1)
            .expect("Morphism boundary index fits usize");
        assert!(
            edge_offset < edge_count as usize,
            "Morphism boundary index belongs to the Serial edge range"
        );
        &self.morphisms.edge_boundaries[edge_start as usize + edge_offset]
    }

    pub fn control_node(&self, id: catseq_core::control::ControlNodeId) -> &[OriginContribution] {
        self.control.node(id)
    }

    pub fn contributions(&self) -> impl Iterator<Item = &OriginContribution> {
        self.entry
            .iter()
            .chain(self.values.iter().flatten())
            .chain(self.morphisms.nodes.iter().flatten())
            .chain(self.morphisms.edge_boundaries.iter().flatten())
            .chain(self.control.contributions())
    }
}

#[derive(Default)]
struct OriginBuilder {
    anchors: Vec<SourceAnchor>,
    entry: Vec<OriginContribution>,
}

impl OriginBuilder {
    fn contribution(&mut self, anchor: &SourceAnchor, role: OriginRole) -> OriginContribution {
        let origin = OriginId::new(self.anchors.len() as u32);
        self.anchors.push(anchor.clone());
        OriginContribution { origin, role }
    }

    fn record_entry(&mut self, anchor: &SourceAnchor) -> OriginContribution {
        let contribution = self.contribution(anchor, OriginRole::Entry);
        self.entry.push(contribution);
        contribution
    }

    fn anchor(&self, id: OriginId) -> Option<&SourceAnchor> {
        self.anchors.get(id.index())
    }

    fn finish(
        self,
        values: Vec<Vec<OriginContribution>>,
        morphisms: MorphismOrigins,
        control: ControlOriginMap,
    ) -> FrontendOriginMap {
        FrontendOriginMap {
            anchors: self.anchors,
            entry: self.entry,
            values,
            morphisms,
            control,
        }
    }
}

impl MorphismOrigins {
    fn all_for(
        &self,
        graph: &FrontendMorphismGraph,
        id: FrontendMorphismId,
    ) -> Vec<OriginContribution> {
        let mut output = self.nodes[id.index()].clone();
        if let FrontendMorphismNode::Serial { edge_start, .. } = &graph.nodes[id.index()] {
            let children = graph
                .children(id)
                .expect("validated Serial Morphism retains its edge range");
            for (index, child) in children.iter().enumerate() {
                if index != 0 {
                    output.extend(
                        self.edge_boundaries[*edge_start as usize + index]
                            .iter()
                            .copied(),
                    );
                }
                output.extend(self.nodes[child.index()].iter().copied());
            }
        }
        output
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalSummary {
    exact_cycle_delta: Option<i64>,
}

impl TemporalSummary {
    pub const fn exact_cycle_delta(&self) -> Option<i64> {
        self.exact_cycle_delta
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValueSummary {
    node_count: usize,
    compile_count: usize,
    link_count: usize,
    device_count: usize,
    structural_count: usize,
    relocatable_count: usize,
}

impl ValueSummary {
    pub const fn node_count(&self) -> usize {
        self.node_count
    }

    pub const fn compile_count(&self) -> usize {
        self.compile_count
    }

    pub const fn link_count(&self) -> usize {
        self.link_count
    }

    pub const fn device_count(&self) -> usize {
        self.device_count
    }

    pub const fn structural_count(&self) -> usize {
        self.structural_count
    }

    pub const fn relocatable_count(&self) -> usize {
        self.relocatable_count
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LogicalResourceSummary {
    resource_count: usize,
}

impl LogicalResourceSummary {
    pub const fn resource_count(&self) -> usize {
        self.resource_count
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologySummary {
    morphism_node_count: usize,
    control_node_count: usize,
    morphism_island_count: usize,
}

impl TopologySummary {
    pub const fn morphism_node_count(&self) -> usize {
        self.morphism_node_count
    }

    pub const fn control_node_count(&self) -> usize {
        self.control_node_count
    }

    pub const fn morphism_island_count(&self) -> usize {
        self.morphism_island_count
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompletionSummary {
    has_normal_exit: bool,
}

impl CompletionSummary {
    pub const fn has_normal_exit(&self) -> bool {
        self.has_normal_exit
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FailureSummary {
    has_failure_exit: bool,
}

impl FailureSummary {
    pub const fn has_failure_exit(&self) -> bool {
        self.has_failure_exit
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrontendProgramSummaries {
    temporal: TemporalSummary,
    values: ValueSummary,
    logical_resources: LogicalResourceSummary,
    topology: TopologySummary,
    completion: CompletionSummary,
    failure: FailureSummary,
}

impl FrontendProgramSummaries {
    fn new(
        values: &FrontendValueGraph,
        morphisms: &FrontendMorphismGraph,
        control: &ControlArena<FrontendMorphismId, FrontendValueId, ValueType>,
        control_summary: &ControlSummary<ValueType>,
    ) -> Self {
        Self {
            temporal: TemporalSummary {
                exact_cycle_delta: morphisms.exact_cycle_delta(morphisms.root, values),
            },
            values: ValueSummary {
                node_count: values.nodes.len(),
                compile_count: values
                    .nodes
                    .iter()
                    .filter(|node| node.availability == ValueAvailability::Compile)
                    .count(),
                link_count: values
                    .nodes
                    .iter()
                    .filter(|node| node.availability == ValueAvailability::Link)
                    .count(),
                device_count: values
                    .nodes
                    .iter()
                    .filter(|node| node.availability == ValueAvailability::Device)
                    .count(),
                structural_count: values
                    .nodes
                    .iter()
                    .filter(|node| node.dependency_roles.contains(&DependencyRole::Structural))
                    .count(),
                relocatable_count: values
                    .nodes
                    .iter()
                    .filter(|node| node.dependency_roles.contains(&DependencyRole::Relocatable))
                    .count(),
            },
            logical_resources: LogicalResourceSummary { resource_count: 0 },
            topology: TopologySummary {
                morphism_node_count: morphisms.nodes.len(),
                control_node_count: control.nodes().len(),
                morphism_island_count: control_summary.morphism_island_count,
            },
            completion: CompletionSummary {
                has_normal_exit: control_summary.has_normal_exit,
            },
            failure: FailureSummary {
                has_failure_exit: control_summary.has_failure_exit,
            },
        }
    }

    pub const fn temporal(&self) -> &TemporalSummary {
        &self.temporal
    }

    pub const fn values(&self) -> &ValueSummary {
        &self.values
    }

    pub const fn logical_resources(&self) -> &LogicalResourceSummary {
        &self.logical_resources
    }

    pub const fn topology(&self) -> &TopologySummary {
        &self.topology
    }

    pub const fn completion(&self) -> &CompletionSummary {
        &self.completion
    }

    pub const fn failure(&self) -> &FailureSummary {
        &self.failure
    }
}

#[derive(Clone, Debug)]
pub struct FrontendProgram {
    entry_definition_id: usize,
    entry: String,
    values: FrontendValueGraph,
    morphisms: FrontendMorphismGraph,
    control: ControlArena<FrontendMorphismId, FrontendValueId, ValueType>,
    summaries: FrontendProgramSummaries,
    origins: FrontendOriginMap,
}

impl FrontendProgram {
    pub const fn entry_definition_id(&self) -> usize {
        self.entry_definition_id
    }

    pub fn entry(&self) -> &str {
        &self.entry
    }

    pub const fn values(&self) -> &FrontendValueGraph {
        &self.values
    }

    pub const fn morphisms(&self) -> &FrontendMorphismGraph {
        &self.morphisms
    }

    pub const fn control(&self) -> &ControlArena<FrontendMorphismId, FrontendValueId, ValueType> {
        &self.control
    }

    pub const fn summaries(&self) -> &FrontendProgramSummaries {
        &self.summaries
    }

    pub const fn origins(&self) -> &FrontendOriginMap {
        &self.origins
    }
}

impl PartialEq for FrontendProgram {
    fn eq(&self, other: &Self) -> bool {
        self.values == other.values
            && self.morphisms == other.morphisms
            && self.control == other.control
            && self.summaries == other.summaries
    }
}

impl Eq for FrontendProgram {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FrontendElaborationErrorCode {
    MissingEntryDefinition,
    InvalidTypedReference,
    MissingReturn,
    AmbiguousReturn,
    DiscardedMorphism,
    UnsupportedSource,
    InvalidGraphInvariant,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrontendElaborationError {
    code: FrontendElaborationErrorCode,
    message: String,
    primary: Option<SourceAnchor>,
    related: Vec<SourceAnchor>,
}

impl FrontendElaborationError {
    fn new(code: FrontendElaborationErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            primary: None,
            related: Vec::new(),
        }
    }

    fn at(
        code: FrontendElaborationErrorCode,
        message: impl Into<String>,
        primary: &SourceAnchor,
    ) -> Self {
        Self {
            code,
            message: message.into(),
            primary: Some(primary.clone()),
            related: Vec::new(),
        }
    }

    pub const fn code(&self) -> FrontendElaborationErrorCode {
        self.code
    }

    pub fn message(&self) -> &str {
        &self.message
    }

    pub const fn primary_anchor(&self) -> Option<&SourceAnchor> {
        self.primary.as_ref()
    }

    pub fn related_anchors(&self) -> &[SourceAnchor] {
        &self.related
    }
}

impl Display for FrontendElaborationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)?;
        if let Some(anchor) = &self.primary {
            write!(
                formatter,
                " at {}:{}:{}",
                anchor.file_name(),
                anchor.line(),
                anchor.column()
            )?;
        }
        Ok(())
    }
}

impl Error for FrontendElaborationError {}

struct ProgramMorphismAlgebra<'a> {
    graph: &'a FrontendMorphismGraph,
}

impl MorphismAlgebra<FrontendMorphismId> for ProgramMorphismAlgebra<'_> {
    type Error = std::convert::Infallible;

    fn is_identity(&self, morphism: &FrontendMorphismId) -> bool {
        matches!(self.graph.node(*morphism), Some(FrontendMorphismNode::Id))
    }

    fn serial(
        &mut self,
        _morphisms: Vec<FrontendMorphismId>,
    ) -> Result<FrontendMorphismId, Self::Error> {
        unreachable!("the initial frontend entry contains one Control Lift")
    }
}

#[derive(Clone, Copy, Debug)]
enum ElaboratedValue {
    Value(FrontendValueId),
    Morphism(FrontendMorphismId),
}

struct DefinitionFrame {
    definition: TypedDefinition,
    environment: BTreeMap<String, ElaboratedValue>,
    morphism_parameter_anchors: BTreeMap<String, SourceAnchor>,
    used_morphism_parameters: BTreeSet<String>,
    assignment_anchors: BTreeMap<u32, Vec<SourceAnchor>>,
    assignments: Vec<(u32, u32)>,
    return_root: u32,
    return_value: u32,
    reachable: Vec<u32>,
    next_node: usize,
    results: BTreeMap<u32, ElaboratedValue>,
    pending_call: Option<u32>,
}

enum ReadyNode {
    Complete(ElaboratedValue),
    DefinitionCall {
        definition_id: usize,
        environment: BTreeMap<String, ElaboratedValue>,
        parameter_anchors: BTreeMap<String, SourceAnchor>,
    },
}

struct Elaborator<'a> {
    report: &'a TypedCheckReport,
    definitions: BTreeMap<usize, &'a TypedDefinition>,
    values: ValueGraphBuilder,
    morphisms: MorphismGraphBuilder,
    origins: OriginBuilder,
    active_definitions: BTreeSet<usize>,
}

pub fn elaborate_frontend_program(
    report: &TypedCheckReport,
) -> Result<FrontendProgram, FrontendElaborationError> {
    let mut elaborator = Elaborator::new(report)?;
    let entry = elaborator
        .definitions
        .get(&report.entry_definition_id())
        .copied()
        .ok_or_else(|| {
            FrontendElaborationError::new(
                FrontendElaborationErrorCode::MissingEntryDefinition,
                format!(
                    "typed report does not contain entry definition {}",
                    report.entry_definition_id()
                ),
            )
        })?;
    elaborator.origins.record_entry(entry.anchor());
    let result = elaborator.evaluate_definition(entry.definition_id(), BTreeMap::new())?;
    let ElaboratedValue::Morphism(root) = result else {
        return Err(FrontendElaborationError::at(
            FrontendElaborationErrorCode::InvalidTypedReference,
            "entry result is not a Morphism",
            entry.anchor(),
        ));
    };

    let (mut morphisms, morphism_origins, root) =
        elaborator.morphisms.finish(root).map_err(|message| {
            FrontendElaborationError::at(
                FrontendElaborationErrorCode::InvalidGraphInvariant,
                message,
                entry.anchor(),
            )
        })?;
    let (values, value_origins) =
        elaborator
            .values
            .finish_reachable(&mut morphisms)
            .map_err(|message| {
                FrontendElaborationError::at(
                    FrontendElaborationErrorCode::InvalidGraphInvariant,
                    message,
                    entry.anchor(),
                )
            })?;
    morphisms.validate(&values).map_err(|message| {
        FrontendElaborationError::at(
            FrontendElaborationErrorCode::InvalidGraphInvariant,
            message,
            entry.anchor(),
        )
    })?;

    let lift_origins = morphism_origins.all_for(&morphisms, root);
    let mut control_builder = ControlBuilder::new();
    let control_root = control_builder.lift(MorphismTerm::from_origins(root, lift_origins));
    let normalized = {
        let mut algebra = ProgramMorphismAlgebra { graph: &morphisms };
        control_builder.finish(control_root, &mut algebra)
    }
    .map_err(|error| match error {
        ControlBuildError::Morphism(never) => match never {},
        ControlBuildError::Diagnostic(diagnostic) => {
            let primary = elaborator
                .origins
                .anchor(diagnostic.primary_origin)
                .unwrap_or(entry.anchor());
            let mut error = FrontendElaborationError::at(
                FrontendElaborationErrorCode::InvalidGraphInvariant,
                format!("Control normalization failed: {:?}", diagnostic.code),
                primary,
            );
            error.related = diagnostic
                .related_origins
                .iter()
                .filter_map(|origin| elaborator.origins.anchor(*origin).cloned())
                .collect();
            error
        }
    })?;
    let (control, control_origins, control_summary) = normalized.into_parts();
    let summaries = FrontendProgramSummaries::new(&values, &morphisms, &control, &control_summary);
    let origins = elaborator
        .origins
        .finish(value_origins, morphism_origins, control_origins);

    Ok(FrontendProgram {
        entry_definition_id: report.entry_definition_id(),
        entry: report.entry().to_owned(),
        values,
        morphisms,
        control,
        summaries,
        origins,
    })
}

impl<'a> Elaborator<'a> {
    fn new(report: &'a TypedCheckReport) -> Result<Self, FrontendElaborationError> {
        let mut definitions = BTreeMap::new();
        for definition in report.definitions() {
            if definitions
                .insert(definition.definition_id(), definition)
                .is_some()
            {
                return Err(FrontendElaborationError::at(
                    FrontendElaborationErrorCode::InvalidTypedReference,
                    format!(
                        "typed report contains duplicate definition {}",
                        definition.definition_id()
                    ),
                    definition.anchor(),
                ));
            }
        }

        let elaborator = Self {
            report,
            definitions,
            values: ValueGraphBuilder::default(),
            morphisms: MorphismGraphBuilder::default(),
            origins: OriginBuilder::default(),
            active_definitions: BTreeSet::new(),
        };
        for definition in report.definitions() {
            elaborator.validate_hir(definition)?;
        }
        Ok(elaborator)
    }

    fn validate_hir(&self, definition: &TypedDefinition) -> Result<(), FrontendElaborationError> {
        let hir = definition.hir();
        if hir.definition_id() != definition.definition_id() {
            return Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::InvalidTypedReference,
                "typed definition and HIR definition identifiers disagree",
                definition.anchor(),
            ));
        }
        if matches!(
            definition.role(),
            RegisteredDefinitionRole::Atomic | RegisteredDefinitionRole::Intrinsic
        ) {
            if hir.nodes().is_empty()
                && hir.edges().is_empty()
                && hir.roots().is_empty()
                && hir.facts().is_empty()
            {
                return Ok(());
            }
            return Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::InvalidTypedReference,
                format!(
                    "body-less {} definition has non-empty source HIR",
                    definition.role().as_str()
                ),
                definition.anchor(),
            ));
        }
        for (node_index, node) in hir.nodes().iter().enumerate() {
            let edge_start = node.edge_start() as usize;
            let edge_end = edge_start
                .checked_add(node.edge_count() as usize)
                .ok_or_else(|| self.invalid_reference(node, "source HIR edge span overflows"))?;
            let children = hir.edges().get(edge_start..edge_end).ok_or_else(|| {
                self.invalid_reference(node, "source HIR edge span is out of bounds")
            })?;
            if children.iter().any(|child| *child as usize >= node_index) {
                return Err(
                    self.invalid_reference(node, "source HIR child does not precede its parent")
                );
            }
            let fact = &hir.facts()[node_index];
            if fact
                .resolved_node()
                .is_some_and(|resolved| resolved as usize >= node_index)
            {
                return Err(self.invalid_reference(
                    node,
                    "source HIR resolved value does not precede its use",
                ));
            }
            if fact
                .call_arguments()
                .iter()
                .any(|argument| argument.value_node() as usize >= node_index)
            {
                return Err(self.invalid_reference(
                    node,
                    "source HIR call argument does not precede its call",
                ));
            }
            if let Some(read_id) = fact.external_read_id()
                && !self
                    .report
                    .external_reads()
                    .iter()
                    .any(|read| read.id() == read_id)
            {
                return Err(self.invalid_reference(
                    node,
                    format!("source HIR references unknown external read {read_id}"),
                ));
            }
            if let Some(ResolvedCallTarget::Definition { definition_id, .. }) = fact.resolved_call()
                && !self.definitions.contains_key(definition_id)
            {
                return Err(self.invalid_reference(
                    node,
                    format!("source HIR references unknown definition {definition_id}"),
                ));
            }
        }

        let mut return_count = 0;
        let mut roots = BTreeSet::new();
        for root in hir.roots() {
            if !roots.insert(*root) {
                return Err(FrontendElaborationError::at(
                    FrontendElaborationErrorCode::InvalidTypedReference,
                    "source HIR contains a duplicate root",
                    definition.anchor(),
                ));
            }
            let node = hir.nodes().get(*root as usize).ok_or_else(|| {
                FrontendElaborationError::at(
                    FrontendElaborationErrorCode::InvalidTypedReference,
                    format!("source HIR references unknown root {root}"),
                    definition.anchor(),
                )
            })?;
            match node.kind() {
                SourceHirKind::Assignment => {
                    if self.children(hir, node).len() != 2 {
                        return Err(self.invalid_reference(
                            node,
                            "source HIR assignment does not have target and value children",
                        ));
                    }
                }
                SourceHirKind::ExpressionStatement => {
                    if self.children(hir, node).len() != 1 {
                        return Err(self.invalid_reference(
                            node,
                            "source HIR expression statement does not have one value child",
                        ));
                    }
                }
                SourceHirKind::Return => {
                    if self.children(hir, node).len() != 1 {
                        return Err(self.invalid_reference(
                            node,
                            "source HIR return does not have one value child",
                        ));
                    }
                    return_count += 1;
                }
                _ => {
                    return Err(self.invalid_reference(
                        node,
                        "source HIR root is not an assignment, expression statement, or return",
                    ));
                }
            }
        }
        match return_count {
            0 => Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::MissingReturn,
                "source HIR has no return root",
                definition.anchor(),
            )),
            1 => Ok(()),
            _ => Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::AmbiguousReturn,
                "source HIR has more than one return root",
                definition.anchor(),
            )),
        }
    }

    fn invalid_reference(
        &self,
        node: &SourceHirNode,
        message: impl Into<String>,
    ) -> FrontendElaborationError {
        FrontendElaborationError::at(
            FrontendElaborationErrorCode::InvalidTypedReference,
            message,
            node.anchor(),
        )
    }

    fn children<'hir>(&self, hir: &'hir TypedSourceHir, node: &SourceHirNode) -> &'hir [u32] {
        let start = node.edge_start() as usize;
        let end = start + node.edge_count() as usize;
        &hir.edges()[start..end]
    }
}

impl Elaborator<'_> {
    fn evaluate_definition(
        &mut self,
        definition_id: usize,
        environment: BTreeMap<String, ElaboratedValue>,
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        let first =
            self.build_definition_frame(definition_id, environment, BTreeMap::new(), None)?;
        let mut frames = vec![first];

        loop {
            let mut frame = frames
                .pop()
                .expect("frontend evaluation retains one active definition frame");
            if frame.next_node == frame.reachable.len() {
                let completed_definition_id = frame.definition.definition_id();
                let result = self.finish_definition_frame(&frame)?;
                self.active_definitions.remove(&completed_definition_id);
                if let Some(parent) = frames.last_mut() {
                    let call = parent
                        .pending_call
                        .take()
                        .expect("a child definition frame has one suspended caller");
                    self.finish_definition_call(parent, call, result)?;
                    continue;
                }
                return Ok(result);
            }

            let node_id = frame.reachable[frame.next_node];
            match self.evaluate_ready_node(&mut frame, node_id)? {
                ReadyNode::Complete(result) => {
                    self.complete_node(&mut frame, node_id, result);
                    frame.next_node += 1;
                    frames.push(frame);
                }
                ReadyNode::DefinitionCall {
                    definition_id,
                    environment,
                    parameter_anchors,
                } => {
                    let call_anchor = frame.definition.hir().nodes()[node_id as usize]
                        .anchor()
                        .clone();
                    frame.next_node += 1;
                    frame.pending_call = Some(node_id);
                    frames.push(frame);
                    let callee = self.build_definition_frame(
                        definition_id,
                        environment,
                        parameter_anchors,
                        Some(&call_anchor),
                    )?;
                    frames.push(callee);
                }
            }
        }
    }

    fn build_definition_frame(
        &mut self,
        definition_id: usize,
        environment: BTreeMap<String, ElaboratedValue>,
        parameter_anchors: BTreeMap<String, SourceAnchor>,
        call_anchor: Option<&SourceAnchor>,
    ) -> Result<DefinitionFrame, FrontendElaborationError> {
        let definition = (*self
            .definitions
            .get(&definition_id)
            .expect("validated call targets retain their typed definition"))
        .clone();
        if !self.active_definitions.insert(definition_id) {
            return Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::InvalidTypedReference,
                "recursive definition reached frontend elaboration",
                call_anchor.unwrap_or(definition.anchor()),
            ));
        }

        let hir = definition.hir();
        let mut assignment_anchors = BTreeMap::<u32, Vec<SourceAnchor>>::new();
        let mut assignments = Vec::new();
        let mut return_root = None;
        for root in hir.roots() {
            let node = &hir.nodes()[*root as usize];
            match node.kind() {
                SourceHirKind::Assignment => {
                    let children = self.children(hir, node);
                    assignment_anchors
                        .entry(children[1])
                        .or_default()
                        .push(node.anchor().clone());
                    assignments.push((*root, children[1]));
                }
                SourceHirKind::ExpressionStatement => {
                    let message = if hir.facts()[*root as usize].value_type()
                        == Some(&ValueType::Morphism)
                    {
                        "Morphism-producing expression statement discards its result"
                    } else {
                        "discarded value expression statements are outside the initial frontend tracer"
                    };
                    let code =
                        if hir.facts()[*root as usize].value_type() == Some(&ValueType::Morphism) {
                            FrontendElaborationErrorCode::DiscardedMorphism
                        } else {
                            FrontendElaborationErrorCode::UnsupportedSource
                        };
                    return Err(FrontendElaborationError::at(code, message, node.anchor()));
                }
                SourceHirKind::Return => return_root = Some(*root),
                _ => unreachable!("validated source HIR roots retain statement kinds"),
            }
        }
        let return_root = return_root.expect("validated source HIR has one return");
        let return_node = &hir.nodes()[return_root as usize];
        let return_value = self.children(hir, return_node)[0];
        let reachable = self.collect_reachable(hir, return_value);
        let morphism_parameter_anchors = environment
            .iter()
            .filter(|(_, value)| matches!(value, ElaboratedValue::Morphism(_)))
            .map(|(name, _)| {
                (
                    name.clone(),
                    parameter_anchors
                        .get(name)
                        .cloned()
                        .unwrap_or_else(|| definition.anchor().clone()),
                )
            })
            .collect();

        Ok(DefinitionFrame {
            definition,
            environment,
            morphism_parameter_anchors,
            used_morphism_parameters: BTreeSet::new(),
            assignment_anchors,
            assignments,
            return_root,
            return_value,
            reachable,
            next_node: 0,
            results: BTreeMap::new(),
            pending_call: None,
        })
    }

    fn collect_reachable(&self, hir: &TypedSourceHir, root: u32) -> Vec<u32> {
        let mut reachable = BTreeSet::new();
        let mut pending = vec![root];
        while let Some(node_id) = pending.pop() {
            if !reachable.insert(node_id) {
                continue;
            }
            let node = &hir.nodes()[node_id as usize];
            let fact = &hir.facts()[node_id as usize];
            match node.kind() {
                SourceHirKind::Name => pending.extend(fact.resolved_node()),
                SourceHirKind::Binary if node.morphism_composition().is_some() => {
                    pending.extend(self.children(hir, node));
                }
                SourceHirKind::Binary
                    if node.value_operation() == Some(SourceValueOperation::ScaleDuration) =>
                {
                    pending.push(self.children(hir, node)[0]);
                }
                SourceHirKind::Call => pending.extend(
                    fact.call_arguments()
                        .iter()
                        .map(|argument| argument.value_node()),
                ),
                SourceHirKind::Constant
                | SourceHirKind::Attribute
                | SourceHirKind::Subscript
                | SourceHirKind::Binary => {}
                SourceHirKind::Assignment
                | SourceHirKind::ExpressionStatement
                | SourceHirKind::Return => {
                    unreachable!("statement roots are not frontend value dependencies")
                }
            }
        }
        reachable.into_iter().collect()
    }

    fn finish_definition_frame(
        &mut self,
        frame: &DefinitionFrame,
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        let hir = frame.definition.hir();
        let result = frame.results[&frame.return_value];
        let return_node = &hir.nodes()[frame.return_root as usize];
        let return_origin = self
            .origins
            .contribution(return_node.anchor(), OriginRole::Return);
        self.record_result(result, return_origin);

        for (assignment, value) in &frame.assignments {
            if hir.facts()[*value as usize].value_type() == Some(&ValueType::Morphism)
                && !frame.results.contains_key(value)
            {
                let node = &hir.nodes()[*assignment as usize];
                return Err(FrontendElaborationError::at(
                    FrontendElaborationErrorCode::DiscardedMorphism,
                    "Morphism-producing assignment is discarded before the return",
                    node.anchor(),
                ));
            }
        }
        if let Some((name, anchor)) = frame
            .morphism_parameter_anchors
            .iter()
            .find(|(name, _)| !frame.used_morphism_parameters.contains(*name))
        {
            return Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::DiscardedMorphism,
                format!("Morphism argument `{name}` is discarded by the called definition"),
                anchor,
            ));
        }
        Ok(result)
    }

    fn finish_definition_call(
        &mut self,
        frame: &mut DefinitionFrame,
        node_id: u32,
        result: ElaboratedValue,
    ) -> Result<(), FrontendElaborationError> {
        let node = &frame.definition.hir().nodes()[node_id as usize];
        let fact = &frame.definition.hir().facts()[node_id as usize];
        if !matches!(result, ElaboratedValue::Morphism(_))
            || fact.value_type() != Some(&ValueType::Morphism)
        {
            return Err(self.invalid_reference(
                node,
                "Morphism Definition call did not elaborate to a Morphism",
            ));
        }
        let call_origin = self.origins.contribution(node.anchor(), OriginRole::Call);
        self.record_result(result, call_origin);
        self.complete_node(frame, node_id, result);
        Ok(())
    }

    fn complete_node(
        &mut self,
        frame: &mut DefinitionFrame,
        node_id: u32,
        result: ElaboratedValue,
    ) {
        if let Some(anchors) = frame.assignment_anchors.get(&node_id) {
            for anchor in anchors {
                let origin = self.origins.contribution(anchor, OriginRole::Assignment);
                self.record_result(result, origin);
            }
        }
        frame.results.insert(node_id, result);
    }

    fn evaluate_ready_node(
        &mut self,
        frame: &mut DefinitionFrame,
        node_id: u32,
    ) -> Result<ReadyNode, FrontendElaborationError> {
        let hir = frame.definition.hir();
        let node = hir.nodes()[node_id as usize].clone();
        let fact = hir.facts()[node_id as usize].clone();
        let children = self.children(hir, &node).to_vec();
        let result = match node.kind() {
            SourceHirKind::Name => self.evaluate_name(frame, &node, &fact)?,
            SourceHirKind::Constant => ReadyNode::Complete(self.evaluate_literal(&node, &fact)?),
            SourceHirKind::Subscript => {
                ReadyNode::Complete(self.evaluate_external_read(&node, &fact)?)
            }
            SourceHirKind::Binary => {
                ReadyNode::Complete(self.evaluate_binary(frame, &node, &fact, &children)?)
            }
            SourceHirKind::Call => self.evaluate_call(frame, &node, &fact)?,
            SourceHirKind::Attribute
            | SourceHirKind::Assignment
            | SourceHirKind::ExpressionStatement
            | SourceHirKind::Return => {
                return Err(FrontendElaborationError::at(
                    FrontendElaborationErrorCode::InvalidTypedReference,
                    format!(
                        "{} source HIR node cannot produce a frontend value",
                        node.kind().as_str()
                    ),
                    node.anchor(),
                ));
            }
        };
        Ok(result)
    }

    fn evaluate_name(
        &mut self,
        frame: &mut DefinitionFrame,
        node: &SourceHirNode,
        fact: &SemanticFact,
    ) -> Result<ReadyNode, FrontendElaborationError> {
        let value = if let Some(resolved) = fact.resolved_node() {
            *frame.results.get(&resolved).ok_or_else(|| {
                self.invalid_reference(node, "resolved value was not evaluated before its Name")
            })?
        } else {
            let symbol = node.symbol().ok_or_else(|| {
                self.invalid_reference(node, "value Name is missing its source symbol")
            })?;
            let value = *frame.environment.get(symbol).ok_or_else(|| {
                self.invalid_reference(
                    node,
                    format!("value Name `{symbol}` has no resolved value or parameter binding"),
                )
            })?;
            if matches!(value, ElaboratedValue::Morphism(_)) {
                frame.used_morphism_parameters.insert(symbol.to_owned());
            }
            value
        };
        let result_type = self.result_type(value);
        if !fact
            .value_type()
            .is_some_and(|expected| expected.accepts(&result_type))
        {
            return Err(
                self.invalid_reference(node, "value Name and its resolved frontend value disagree")
            );
        }
        let origin = self.origins.contribution(
            node.anchor(),
            match value {
                ElaboratedValue::Value(_) => OriginRole::Value,
                ElaboratedValue::Morphism(_) => OriginRole::Morphism,
            },
        );
        self.record_result(value, origin);
        Ok(ReadyNode::Complete(value))
    }

    fn evaluate_literal(
        &mut self,
        node: &SourceHirNode,
        fact: &SemanticFact,
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        let literal = node.literal().ok_or_else(|| {
            self.invalid_reference(node, "constant source HIR node has no literal")
        })?;
        let value_type = fact.value_type().cloned().ok_or_else(|| {
            self.invalid_reference(node, "constant source HIR node has no ValueType")
        })?;
        if source_literal_type(literal) != value_type {
            return Err(
                self.invalid_reference(node, "constant literal and typed source fact disagree")
            );
        }
        let origin = self.origins.contribution(node.anchor(), OriginRole::Value);
        Ok(ElaboratedValue::Value(self.values.push(
            FrontendValueKind::Literal(FrontendLiteral::from(literal)),
            value_type,
            fact.availability(),
            fact.roles().to_vec(),
            Vec::new(),
            origin,
        )))
    }

    fn evaluate_external_read(
        &mut self,
        node: &SourceHirNode,
        fact: &SemanticFact,
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        let read_id = fact.external_read_id().ok_or_else(|| {
            self.invalid_reference(
                node,
                "Subscript source HIR node has no sealed external read",
            )
        })?;
        let read = self
            .report
            .external_reads()
            .iter()
            .find(|read| read.id() == read_id)
            .expect("validated external read references remain in the typed report");
        if fact.value_type() != Some(read.value_type())
            || fact.availability() != read.availability()
            || source_literal_type(read.value()) != *read.value_type()
        {
            return Err(
                self.invalid_reference(node, "sealed external read and typed source fact disagree")
            );
        }
        let origin = self.origins.contribution(node.anchor(), OriginRole::Value);
        Ok(ElaboratedValue::Value(self.values.push(
            FrontendValueKind::SealedExternal {
                name: read.name().to_owned(),
                value: FrontendLiteral::from(read.value()),
            },
            read.value_type().clone(),
            read.availability(),
            fact.roles().to_vec(),
            Vec::new(),
            origin,
        )))
    }

    fn evaluate_binary(
        &mut self,
        frame: &DefinitionFrame,
        node: &SourceHirNode,
        fact: &SemanticFact,
        children: &[u32],
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        let [left, right] = children else {
            return Err(
                self.invalid_reference(node, "binary source HIR node does not have two operands")
            );
        };
        if node.morphism_composition().is_some() {
            let left = frame.results[left];
            let right = frame.results[right];
            let (ElaboratedValue::Morphism(left), ElaboratedValue::Morphism(right)) = (left, right)
            else {
                return Err(
                    self.invalid_reference(node, "Serial source HIR operands are not Morphisms")
                );
            };
            let operator = self
                .origins
                .contribution(node.anchor(), OriginRole::SerialOperator);
            return Ok(ElaboratedValue::Morphism(
                self.morphisms.serial(left, right, operator),
            ));
        }
        if node.value_operation() == Some(SourceValueOperation::ScaleDuration) {
            let scalar = frame.results[left];
            let ElaboratedValue::Value(scalar) = scalar else {
                return Err(self
                    .invalid_reference(node, "physical Duration scalar is not a frontend value"));
            };
            let scalar_availability = self.values.node(scalar).availability();
            let unit_fact = &frame.definition.hir().facts()[*right as usize];
            let Some(SourceBinding::DurationUnit(unit)) = unit_fact.source_binding() else {
                return Err(self.invalid_reference(
                    node,
                    "physical Duration expression has no exact unit binding",
                ));
            };
            if !matches!(
                self.values.node(scalar).value_type,
                ValueType::Int32 | ValueType::Float64
            ) || fact.value_type() != Some(&ValueType::Duration)
            {
                return Err(
                    self.invalid_reference(node, "physical Duration typed source shape is invalid")
                );
            }
            let origin = self.origins.contribution(node.anchor(), OriginRole::Value);
            let value = self.values.push(
                FrontendValueKind::ScaleDuration(*unit),
                ValueType::Duration,
                scalar_availability,
                fact.roles().to_vec(),
                vec![scalar],
                origin,
            );
            let unit_node = &frame.definition.hir().nodes()[*right as usize];
            let unit_origin = self
                .origins
                .contribution(unit_node.anchor(), OriginRole::Value);
            self.values.record(value, unit_origin);
            return Ok(ElaboratedValue::Value(value));
        }
        Err(FrontendElaborationError::at(
            FrontendElaborationErrorCode::UnsupportedSource,
            "binary value operation is outside the initial frontend tracer",
            node.anchor(),
        ))
    }

    fn record_result(&mut self, value: ElaboratedValue, origin: OriginContribution) {
        match value {
            ElaboratedValue::Value(value) => self.values.record(value, origin),
            ElaboratedValue::Morphism(morphism) => self.morphisms.record(morphism, origin),
        }
    }

    fn result_type(&self, value: ElaboratedValue) -> ValueType {
        match value {
            ElaboratedValue::Value(value) => self.values.node(value).value_type().clone(),
            ElaboratedValue::Morphism(_) => ValueType::Morphism,
        }
    }

    fn evaluate_call(
        &mut self,
        frame: &DefinitionFrame,
        node: &SourceHirNode,
        fact: &SemanticFact,
    ) -> Result<ReadyNode, FrontendElaborationError> {
        let target = fact.resolved_call().cloned().ok_or_else(|| {
            self.invalid_reference(node, "Call source HIR node has no resolved target")
        })?;
        let arguments = self.evaluate_call_arguments(frame, node, fact)?;
        match target {
            ResolvedCallTarget::Intrinsic(SourceIntrinsic::Cycles) => {
                let count = self.one_argument(node, &arguments, "count")?;
                let ElaboratedValue::Value(count) = count else {
                    return Err(
                        self.invalid_reference(node, "cycles count is not a frontend value")
                    );
                };
                let count_availability = self.values.node(count).availability();
                if self.values.node(count).value_type() != &ValueType::Int32
                    || fact.value_type() != Some(&ValueType::Duration)
                {
                    return Err(
                        self.invalid_reference(node, "cycles typed source shape is invalid")
                    );
                }
                let value_origin = self.origins.contribution(node.anchor(), OriginRole::Value);
                let value = self.values.push(
                    FrontendValueKind::Cycles,
                    ValueType::Duration,
                    count_availability,
                    fact.roles().to_vec(),
                    vec![count],
                    value_origin,
                );
                let call_origin = self.origins.contribution(node.anchor(), OriginRole::Call);
                self.values.record(value, call_origin);
                Ok(ReadyNode::Complete(ElaboratedValue::Value(value)))
            }
            ResolvedCallTarget::Intrinsic(SourceIntrinsic::Id) => {
                if !arguments.is_empty() || fact.value_type() != Some(&ValueType::Morphism) {
                    return Err(self.invalid_reference(node, "Id typed source shape is invalid"));
                }
                let call_origin = self.origins.contribution(node.anchor(), OriginRole::Call);
                let morphism = self.morphisms.id(call_origin);
                let morphism_origin = self
                    .origins
                    .contribution(node.anchor(), OriginRole::Morphism);
                self.morphisms.record(morphism, morphism_origin);
                Ok(ReadyNode::Complete(ElaboratedValue::Morphism(morphism)))
            }
            ResolvedCallTarget::Intrinsic(SourceIntrinsic::Wait) => {
                let duration = self.one_argument(node, &arguments, "duration")?;
                let ElaboratedValue::Value(duration) = duration else {
                    return Err(
                        self.invalid_reference(node, "Wait duration is not a frontend value")
                    );
                };
                if self.values.node(duration).value_type() != &ValueType::Duration
                    || fact.value_type() != Some(&ValueType::Morphism)
                {
                    return Err(self.invalid_reference(node, "Wait typed source shape is invalid"));
                }
                let call_origin = self.origins.contribution(node.anchor(), OriginRole::Call);
                let morphism = if self.values.exact_cycle_delta(duration) == Some(0) {
                    let eliminated_origins = self.values.all_origins(duration);
                    let morphism = self.morphisms.id(call_origin);
                    for origin in eliminated_origins {
                        self.morphisms.record(morphism, origin);
                    }
                    morphism
                } else {
                    self.morphisms.wait(duration, call_origin)
                };
                let morphism_origin = self
                    .origins
                    .contribution(node.anchor(), OriginRole::Morphism);
                self.morphisms.record(morphism, morphism_origin);
                Ok(ReadyNode::Complete(ElaboratedValue::Morphism(morphism)))
            }
            ResolvedCallTarget::Definition {
                definition_id,
                role,
            } => {
                if role != RegisteredDefinitionRole::MorphismDefinition {
                    return Err(FrontendElaborationError::at(
                        FrontendElaborationErrorCode::UnsupportedSource,
                        format!(
                            "{} calls are outside the initial frontend tracer",
                            role.as_str()
                        ),
                        node.anchor(),
                    ));
                }
                let target = *self
                    .definitions
                    .get(&definition_id)
                    .expect("validated definition references remain in the typed report");
                if target.role() != role {
                    return Err(self.invalid_reference(
                        node,
                        "resolved call role disagrees with its typed definition",
                    ));
                }
                for parameter in target.signature().parameters() {
                    match parameter.semantics() {
                        ParameterSemantics::Value { value_type, .. } => {
                            let argument = arguments.get(parameter.name()).ok_or_else(|| {
                                self.invalid_reference(
                                    node,
                                    format!(
                                        "Morphism Definition argument `{}` is missing",
                                        parameter.name()
                                    ),
                                )
                            })?;
                            if !value_type.accepts(&self.result_type(*argument)) {
                                return Err(self.invalid_reference(
                                    node,
                                    format!(
                                        "Morphism Definition argument `{}` has the wrong ValueType",
                                        parameter.name()
                                    ),
                                ));
                            }
                        }
                        ParameterSemantics::SourceAuthority(_) => {}
                    }
                }
                if arguments.keys().any(|name| {
                    !target.signature().parameters().iter().any(|parameter| {
                        parameter.name() == name
                            && matches!(parameter.semantics(), ParameterSemantics::Value { .. })
                    })
                }) {
                    return Err(self.invalid_reference(
                        node,
                        "Morphism Definition call contains an unknown value argument",
                    ));
                }
                if fact.value_type() != Some(&ValueType::Morphism) {
                    return Err(self.invalid_reference(
                        node,
                        "Morphism Definition call has a non-Morphism result fact",
                    ));
                }
                let parameter_anchors = fact
                    .call_arguments()
                    .iter()
                    .map(|argument| {
                        (
                            argument.parameter().to_owned(),
                            frame.definition.hir().nodes()[argument.value_node() as usize]
                                .anchor()
                                .clone(),
                        )
                    })
                    .collect();
                Ok(ReadyNode::DefinitionCall {
                    definition_id,
                    environment: arguments,
                    parameter_anchors,
                })
            }
            ResolvedCallTarget::Compute(_) => Err(FrontendElaborationError::at(
                FrontendElaborationErrorCode::UnsupportedSource,
                "Compute calls are outside the initial frontend tracer",
                node.anchor(),
            )),
        }
    }

    fn evaluate_call_arguments(
        &self,
        frame: &DefinitionFrame,
        node: &SourceHirNode,
        fact: &SemanticFact,
    ) -> Result<BTreeMap<String, ElaboratedValue>, FrontendElaborationError> {
        let mut arguments = BTreeMap::new();
        for argument in fact.call_arguments() {
            let value = *frame.results.get(&argument.value_node()).ok_or_else(|| {
                self.invalid_reference(node, "Call argument was not evaluated before its call")
            })?;
            if arguments
                .insert(argument.parameter().to_owned(), value)
                .is_some()
            {
                return Err(self.invalid_reference(
                    node,
                    format!(
                        "Call source HIR binds argument `{}` more than once",
                        argument.parameter()
                    ),
                ));
            }
        }
        Ok(arguments)
    }

    fn one_argument(
        &self,
        node: &SourceHirNode,
        arguments: &BTreeMap<String, ElaboratedValue>,
        name: &str,
    ) -> Result<ElaboratedValue, FrontendElaborationError> {
        if arguments.len() != 1 {
            return Err(self.invalid_reference(
                node,
                format!("intrinsic call does not bind exactly one `{name}` argument"),
            ));
        }
        arguments.get(name).copied().ok_or_else(|| {
            self.invalid_reference(
                node,
                format!("intrinsic call does not bind its `{name}` argument"),
            )
        })
    }
}

fn source_literal_type(literal: &SourceLiteral) -> ValueType {
    match literal {
        SourceLiteral::None => ValueType::None,
        SourceLiteral::Bool(_) => ValueType::Bool,
        SourceLiteral::Int32(_) => ValueType::Int32,
        SourceLiteral::Float64(_) => ValueType::Float64,
        SourceLiteral::String(_) => ValueType::String,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::registered_modules::{
        DefinitionRegistrationInput, ModuleRegistrationInput, RegistrationInput,
        register_kernel_modules,
    };
    use crate::source_hir::TopologyEffect;
    use crate::typed::TypeSignature;

    #[test]
    fn reports_a_broken_typed_child_reference_at_the_source_anchor() {
        let registered = register_kernel_modules(RegistrationInput {
            modules: vec![ModuleRegistrationInput {
                id: 1,
                import_name: "broken".to_owned(),
                file_name: "/project/broken.py".to_owned(),
                source: Arc::from("@kernel\ndef entry() -> Morphism:\n    return Id()\n"),
            }],
            definitions: vec![DefinitionRegistrationInput {
                id: 7,
                module_id: 1,
                qualified_name: "entry".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            }],
            definition_name_bindings: Vec::new(),
            builtin_name_bindings: Vec::new(),
            entry_definition_id: 7,
        })
        .unwrap();
        let anchor = SourceAnchor::new("broken", "/project/broken.py", 3, 5);
        let hir = TypedSourceHir::new(
            7,
            "entry".to_owned(),
            vec![SourceHirNode::new(
                SourceHirKind::Return,
                None,
                None,
                None,
                None,
                0,
                1,
                anchor,
            )],
            vec![99],
            vec![0],
            vec![SemanticFact::value(
                ValueType::Morphism,
                ValueAvailability::Compile,
                TopologyEffect::Morphism,
            )],
        );
        let definition = TypedDefinition::from_registered(
            registered.definition(7).unwrap(),
            &registered.modules()[0],
            TypeSignature::new(Vec::new(), ValueType::Morphism),
            hir,
        );
        let report = TypedCheckReport::new(
            7,
            "broken.entry".to_owned(),
            vec![definition],
            Vec::new(),
            Vec::new(),
            Vec::new(),
            vec!["broken".to_owned()],
        );

        let error = elaborate_frontend_program(&report)
            .expect_err("a broken typed edge must not become an empty program");

        assert_eq!(
            error.code(),
            FrontendElaborationErrorCode::InvalidTypedReference
        );
        let primary = error.primary_anchor().unwrap();
        assert_eq!(primary.file_name(), "/project/broken.py");
        assert_eq!(primary.line(), 3);
        assert_eq!(primary.column(), 5);
    }
}
