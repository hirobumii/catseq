use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use catseq_core::arena::{
    ArenaError, ArenaStore, FrozenProgram, NodeKind, NodeRef, SegmentId, SegmentKind, TemplateId,
};

type ExportedColumns = (Vec<u8>, Vec<i64>, Vec<i64>, Vec<u32>, Vec<u128>, Vec<u32>);

fn value_error(error: ArenaError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

#[pyclass(module = "catseq._native", name = "ArenaStore")]
pub struct NativeArenaStore {
    store: ArenaStore,
}

#[pymethods]
impl NativeArenaStore {
    #[new]
    fn new() -> Self {
        Self {
            store: ArenaStore::new(),
        }
    }

    fn new_program(&self) -> NativeArena {
        NativeArena {
            store: self.store.clone(),
            segment: self.store.create_segment(SegmentKind::Program),
        }
    }

    fn new_template(&self) -> NativeArena {
        NativeArena {
            store: self.store.clone(),
            segment: self.store.create_segment(SegmentKind::Template),
        }
    }

    #[getter]
    fn total_node_count(&self) -> usize {
        self.store.total_node_count()
    }
}

#[pyclass(module = "catseq._native", name = "ProgramArena")]
pub struct NativeArena {
    store: ArenaStore,
    segment: SegmentId,
}

#[pymethods]
impl NativeArena {
    #[pyo3(signature = (kind, left, right, payload_id, channel_mask, provenance_id=0))]
    fn _append_raw(
        &self,
        kind: u8,
        left: Option<u32>,
        right: Option<u32>,
        payload_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> PyResult<u32> {
        let left = left
            .map(|node| self.store.local_node_ref(self.segment, node))
            .transpose()
            .map_err(value_error)?;
        let right = right
            .map(|node| self.store.local_node_ref(self.segment, node))
            .transpose()
            .map_err(value_error)?;
        let root = self
            .store
            .append_raw(
                self.segment,
                NodeKind::try_from(kind).map_err(value_error)?,
                left,
                right,
                payload_id,
                channel_mask,
                provenance_id,
            )
            .map_err(value_error)?;
        Ok(root.local_index())
    }

    fn _export_columns(&self) -> PyResult<ExportedColumns> {
        let columns = self
            .store
            .export_segment(self.segment)
            .map_err(value_error)?;
        Ok((
            columns.kinds.into_iter().map(|kind| kind as u8).collect(),
            columns
                .left
                .into_iter()
                .map(|node| node.map_or(-1, |node| i64::from(node.local_index())))
                .collect(),
            columns
                .right
                .into_iter()
                .map(|node| node.map_or(-1, |node| i64::from(node.local_index())))
                .collect(),
            columns.payload_ids,
            columns.channel_masks,
            columns.provenance_ids,
        ))
    }

    fn _channel_mask(&self, local_node_id: u32) -> PyResult<u128> {
        let node = self
            .store
            .local_node_ref(self.segment, local_node_id)
            .map_err(value_error)?;
        self.store.node_channel_mask(node).map_err(value_error)
    }

    #[pyo3(signature = (payload_id, channel_mask, provenance_id=0))]
    fn atomic(
        &self,
        payload_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> PyResult<NativeMorphismHandle> {
        let root = self
            .store
            .atomic(self.segment, payload_id, channel_mask, provenance_id)
            .map_err(value_error)?;
        Ok(self.handle(root))
    }

    #[pyo3(signature = (expression_id, provenance_id=0))]
    fn wait(&self, expression_id: u32, provenance_id: u32) -> PyResult<NativeMorphismHandle> {
        let root = self
            .store
            .wait(self.segment, expression_id, provenance_id)
            .map_err(value_error)?;
        Ok(self.handle(root))
    }

    #[pyo3(signature = (template, binding_environment_id, channel_mask, provenance_id=0))]
    fn instantiate(
        &self,
        template: &NativeTemplateHandle,
        binding_environment_id: u32,
        channel_mask: u128,
        provenance_id: u32,
    ) -> PyResult<NativeMorphismHandle> {
        let root = self
            .store
            .instantiate(
                self.segment,
                template.template,
                binding_environment_id,
                channel_mask,
                provenance_id,
            )
            .map_err(value_error)?;
        Ok(self.handle(root))
    }

    #[pyo3(signature = (root, schema_id=0))]
    fn publish(
        &self,
        root: &NativeMorphismHandle,
        schema_id: u32,
    ) -> PyResult<NativeTemplateHandle> {
        if root.root.segment() != self.segment {
            return Err(PyValueError::new_err(
                "template root belongs to another arena segment",
            ));
        }
        let template = self
            .store
            .publish_template(root.root, schema_id)
            .map_err(value_error)?;
        Ok(NativeTemplateHandle {
            store: self.store.clone(),
            template,
        })
    }

    #[getter]
    fn node_count(&self) -> PyResult<usize> {
        self.store
            .segment_node_count(self.segment)
            .map_err(value_error)
    }
}

impl NativeArena {
    fn handle(&self, root: NodeRef) -> NativeMorphismHandle {
        NativeMorphismHandle {
            store: self.store.clone(),
            segment: self.segment,
            root,
        }
    }
}

#[pyclass(module = "catseq._native", name = "MorphismHandle", frozen)]
pub struct NativeMorphismHandle {
    store: ArenaStore,
    segment: SegmentId,
    root: NodeRef,
}

#[pymethods]
impl NativeMorphismHandle {
    fn __rshift__(&self, other: &NativeMorphismHandle) -> PyResult<Self> {
        self.compose(other, NodeKind::AutoSerial)
    }

    fn __matmul__(&self, other: &NativeMorphismHandle) -> PyResult<Self> {
        self.compose(other, NodeKind::StrictSerial)
    }

    fn __or__(&self, other: &NativeMorphismHandle) -> PyResult<Self> {
        self.compose(other, NodeKind::Parallel)
    }

    fn freeze(&self) -> PyResult<NativeFrozenProgram> {
        Ok(NativeFrozenProgram {
            frozen: self.store.freeze(self.root).map_err(value_error)?,
        })
    }

    #[getter]
    fn channel_mask(&self) -> PyResult<u128> {
        Ok(self
            .store
            .node(self.root)
            .map_err(value_error)?
            .channel_mask())
    }

    #[getter]
    fn local_node_id(&self) -> u32 {
        self.root.local_index()
    }
}

impl NativeMorphismHandle {
    fn compose(&self, other: &Self, kind: NodeKind) -> PyResult<Self> {
        let root = self
            .store
            .compose(self.segment, kind, self.root, other.root, 0)
            .map_err(value_error)?;
        Ok(Self {
            store: self.store.clone(),
            segment: self.segment,
            root,
        })
    }
}

#[pyclass(module = "catseq._native", name = "TemplateHandle", frozen)]
pub struct NativeTemplateHandle {
    #[allow(dead_code)]
    store: ArenaStore,
    template: TemplateId,
}

#[pyclass(module = "catseq._native", name = "FrozenProgram", frozen)]
pub struct NativeFrozenProgram {
    frozen: FrozenProgram,
}

#[pymethods]
impl NativeFrozenProgram {
    #[getter]
    fn reachable_storage_node_count(&self) -> PyResult<usize> {
        self.frozen
            .reachable_storage_node_count()
            .map_err(value_error)
    }

    #[getter]
    fn template_instance_count(&self) -> PyResult<usize> {
        self.frozen.template_instance_count().map_err(value_error)
    }
}

pub fn add_to_module(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeArenaStore>()?;
    module.add_class::<NativeArena>()?;
    module.add_class::<NativeMorphismHandle>()?;
    module.add_class::<NativeTemplateHandle>()?;
    module.add_class::<NativeFrozenProgram>()?;
    Ok(())
}
