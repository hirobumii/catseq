/// CatSeq Rust Backend - 纯代数编译器
///
/// Rust 只关心 Monoidal Category 的代数结构，完全不知道操作的具体语义

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::cell::RefCell;

mod arena;
mod compiler;
mod incremental;
mod path;
mod program;

use arena::{ArenaContext, NodeId};
use compiler::compile;
use incremental::IncrementalCompiler;
use path::{MorphismPath, PathIterator};
use program::ProgramArena;

/// Python 持有的编译器上下文
///
/// 使用 RefCell 支持内部可变性（单线程）
#[pyclass(unsendable)]
pub struct CompilerContext {
    arena: RefCell<ArenaContext>,
    incremental: RefCell<Option<IncrementalCompiler>>,
}

#[pymethods]
impl CompilerContext {
    #[new]
    fn new() -> Self {
        CompilerContext {
            arena: RefCell::new(ArenaContext::new()),
            incremental: RefCell::new(None),
        }
    }

    /// 创建带预分配容量的上下文
    #[staticmethod]
    fn with_capacity(capacity: usize) -> Self {
        CompilerContext {
            arena: RefCell::new(ArenaContext::with_capacity(capacity)),
            incremental: RefCell::new(None),
        }
    }

    /// 启用增量编译
    ///
    /// 增量编译会缓存已编译的子树，提升复用场景的性能
    fn enable_incremental(&self) {
        *self.incremental.borrow_mut() = Some(IncrementalCompiler::new());
    }

    /// 禁用增量编译并清空缓存
    fn disable_incremental(&self) {
        *self.incremental.borrow_mut() = None;
    }

    /// 检查是否启用了增量编译
    fn is_incremental_enabled(&self) -> bool {
        self.incremental.borrow().is_some()
    }

    /// 获取增量编译统计信息
    ///
    /// Returns:
    ///     Dict | None: 统计信息字典，如果未启用增量编译则返回 None
    fn get_incremental_stats(&self) -> Option<(usize, usize, usize, f64)> {
        self.incremental
            .borrow()
            .as_ref()
            .map(|inc| {
                let stats = inc.stats();
                (
                    stats.cached_nodes,
                    stats.cache_hits,
                    stats.cache_misses,
                    stats.hit_rate,
                )
            })
    }

    /// 清空增量编译缓存（但保持启用状态）
    fn clear_incremental_cache(&self) {
        if let Some(inc) = self.incremental.borrow_mut().as_mut() {
            inc.clear();
        }
    }

    /// 创建原子操作
    ///
    /// Args:
    ///     channel_id: 通道标识符（u32）
    ///     duration: 持续时间（时钟周期）
    ///     opcode: 操作码（u16），如 0x0100 (TTL_ON)
    ///     data: 不透明载荷（bytes），Rust 不解析
    ///
    /// Returns:
    ///     Node: 新创建的节点句柄
    fn atomic(
        slf: Py<Self>,
        channel_id: u32,
        duration: u64,
        opcode: u16,
        data: Vec<u8>,
    ) -> PyResult<Node> {
        Python::with_gil(|py| {
            let ctx = slf.borrow(py);
            let id = ctx.arena.borrow_mut().atomic(channel_id, duration, opcode, data);
            Ok(Node { id, ctx: slf.clone_ref(py) })
        })
    }

    /// 获取节点总数
    fn node_count(&self) -> usize {
        self.arena.borrow().len()
    }

    /// 清空 Arena（用于重置）
    fn clear(&self) {
        self.arena.borrow_mut().nodes.clear();
    }

    /// 串行组合两个节点（通过 NodeId）
    ///
    /// 用于 OpenMorphism 模式，Python 层直接操作 NodeId
    ///
    /// Args:
    ///     a: 第一个节点的 ID
    ///     b: 第二个节点的 ID
    ///
    /// Returns:
    ///     int: 新创建的串行组合节点 ID
    fn compose(&self, a: u32, b: u32) -> u32 {
        self.arena.borrow_mut().sequential(a, b)
    }

    /// 并行组合两个节点（通过 NodeId）
    ///
    /// 用于 OpenMorphism 模式，Python 层直接操作 NodeId
    ///
    /// Args:
    ///     a: 第一个节点的 ID
    ///     b: 第二个节点的 ID
    ///
    /// Returns:
    ///     int: 新创建的并行组合节点 ID
    ///
    /// Raises:
    ///     ValueError: 如果两个节点的通道有交集
    fn parallel_compose(&self, a: u32, b: u32) -> PyResult<u32> {
        self.arena
            .borrow_mut()
            .parallel(a, b)
            .map_err(|e| PyValueError::new_err(e))
    }

    /// 批量串行组合（构建平衡树）
    ///
    /// 将线性 NodeId 列表构建为平衡的 Sequential 树，
    /// 避免右偏树导致的递归深度问题。
    ///
    /// Args:
    ///     nodes: NodeId 列表
    ///
    /// Returns:
    ///     int | None: 组合后的根节点 ID，空列表返回 None
    fn compose_sequence(&self, nodes: Vec<u32>) -> Option<u32> {
        self.arena.borrow_mut().compose_sequence(nodes)
    }

    /// 批量并行组合（构建平衡树）
    ///
    /// 将多个节点并行组合为平衡树。
    /// 要求所有节点的通道互不相交。
    ///
    /// Args:
    ///     nodes: NodeId 列表
    ///
    /// Returns:
    ///     int | None: 组合后的根节点 ID
    ///
    /// Raises:
    ///     ValueError: 如果任意两个节点的通道有交集
    fn parallel_compose_many(&self, nodes: Vec<u32>) -> PyResult<Option<u32>> {
        self.arena
            .borrow_mut()
            .compose_parallel(nodes)
            .map_err(|e| PyValueError::new_err(e))
    }

    /// 创建原子操作并直接返回 NodeId
    ///
    /// 与 atomic() 类似，但直接返回 u32 而非 Node 对象。
    /// 适用于只需要 NodeId 的场景（如 BoundMorphism replay）。
    fn atomic_id(
        &self,
        channel_id: u32,
        duration: u64,
        opcode: u16,
        data: Vec<u8>,
    ) -> u32 {
        self.arena.borrow_mut().atomic(channel_id, duration, opcode, data)
    }

    /// 编译指定节点为事件列表
    ///
    /// 直接通过 NodeId 编译，无需创建 Node 对象。
    ///
    /// Args:
    ///     node_id: 要编译的节点 ID
    ///
    /// Returns:
    ///     List[Tuple[int, int, int, bytes]]: [(time, channel_id, opcode, data), ...]
    fn compile_graph(&self, node_id: u32) -> Vec<(u64, u32, u16, Vec<u8>)> {
        let arena = self.arena.borrow();

        let events = if let Some(inc) = self.incremental.borrow_mut().as_mut() {
            inc.compile(&arena, node_id)
        } else {
            compile(&arena, node_id)
        };

        events
            .into_iter()
            .map(|e| (e.time, e.channel_id, e.opcode, (*e.data).clone()))
            .collect()
    }

    /// 获取节点时长（通过 NodeId）
    fn get_duration(&self, node_id: u32) -> u64 {
        self.arena.borrow().get(node_id).duration()
    }

    /// 获取节点涉及的通道（通过 NodeId）
    fn get_channels(&self, node_id: u32) -> Vec<u32> {
        self.arena.borrow().get(node_id).channels_vec()
    }

    fn __repr__(&self) -> String {
        format!("<CompilerContext nodes={}>", self.arena.borrow().len())
    }
}

/// Morphism 节点句柄
///
/// Python 只持有轻量级的 NodeId (4 字节) 和 Context 引用
#[pyclass(unsendable)]
pub struct Node {
    id: NodeId,
    ctx: Py<CompilerContext>,
}

#[pymethods]
impl Node {
    /// 串行组合 (@)
    ///
    /// self @ other: 先执行 self，再执行 other
    fn __matmul__(&self, other: &Node) -> PyResult<Node> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let id = ctx.arena.borrow_mut().sequential(self.id, other.id);
            Ok(Node {
                id,
                ctx: self.ctx.clone_ref(py),
            })
        })
    }

    /// 并行组合 (|)
    ///
    /// self | other: 同时执行 self 和 other（通道必须不相交）
    fn __or__(&self, other: &Node) -> PyResult<Node> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let id = ctx
                .arena
                .borrow_mut()
                .parallel(self.id, other.id)
                .map_err(|e| PyValueError::new_err(e))?;
            Ok(Node {
                id,
                ctx: self.ctx.clone_ref(py),
            })
        })
    }

    /// 获取节点 ID（用于 OpenMorphism 模式）
    #[getter]
    fn node_id(&self) -> u32 {
        self.id
    }

    /// 获取总时长（时钟周期）
    #[getter]
    fn duration(&self) -> PyResult<u64> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let duration = ctx.arena.borrow().get(self.id).duration();
            Ok(duration)
        })
    }

    /// 获取涉及的通道列表
    #[getter]
    fn channels(&self) -> PyResult<Vec<u32>> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let channels = ctx.arena.borrow().get(self.id).channels_vec();
            Ok(channels)
        })
    }

    /// 编译为扁平事件列表
    ///
    /// 如果启用了增量编译，会自动使用缓存
    ///
    /// Returns:
    ///     List[Tuple[int, int, int, bytes]]: [(time, channel_id, opcode, data), ...]
    fn compile(&self) -> PyResult<Vec<(u64, u32, u16, Vec<u8>)>> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);

            // 检查是否启用增量编译
            let events = if let Some(inc) = ctx.incremental.borrow_mut().as_mut() {
                // 使用增量编译器（带缓存）
                inc.compile(&ctx.arena.borrow(), self.id)
            } else {
                // 使用标准编译器
                compile(&ctx.arena.borrow(), self.id)
            };

            // 解包 Arc 返回给 Python
            Ok(events
                .into_iter()
                .map(|e| (e.time, e.channel_id, e.opcode, (*e.data).clone()))
                .collect())
        })
    }

    /// 编译并按板卡分组
    ///
    /// 假设 channel_id 的高 16 位是 board_id
    ///
    /// Returns:
    ///     Dict[int, List[Tuple[int, int, int, bytes]]]:
    ///         board_id -> [(time, channel_id, opcode, data), ...]
    fn compile_by_board(&self) -> PyResult<std::collections::HashMap<u16, Vec<(u64, u32, u16, Vec<u8>)>>> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let grouped = compiler::compile_by_board(&ctx.arena.borrow(), self.id);

            // 解包 Arc 返回给 Python
            Ok(grouped
                .into_iter()
                .map(|(board_id, events)| {
                    let events = events
                        .into_iter()
                        .map(|e| (e.time, e.channel_id, e.opcode, (*e.data).clone()))
                        .collect();
                    (board_id, events)
                })
                .collect())
        })
    }

    /// 获取叶子节点数量
    fn leaf_count(&self) -> PyResult<usize> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let count = ctx.arena.borrow().leaf_count(self.id);
            Ok(count)
        })
    }

    /// 获取树的最大深度
    fn max_depth(&self) -> PyResult<usize> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let depth = ctx.arena.borrow().max_depth(self.id);
            Ok(depth)
        })
    }

    fn __repr__(&self) -> PyResult<String> {
        Python::with_gil(|py| {
            let ctx = self.ctx.borrow(py);
            let arena = ctx.arena.borrow();
            let node = arena.get(self.id);
            Ok(format!(
                "<Node id={} duration={} channels={}>",
                self.id,
                node.duration(),
                node.channels().len()
            ))
        })
    }
}

/// Python 模块定义
#[pymodule]
fn catseq_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CompilerContext>()?;
    m.add_class::<Node>()?;
    m.add_class::<MorphismPath>()?;
    m.add_class::<PathIterator>()?;
    m.add_class::<ProgramArena>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_python_api_simulation() {
        // 模拟 Python 使用场景
        let ctx = CompilerContext::new();
        let arena = ctx.arena.borrow();

        // 创建原子操作（模拟 Python）
        // opcode 和 data 对 Rust 来说是不透明的
        drop(arena); // 释放借用
        let mut arena_mut = ctx.arena.borrow_mut();
        let n1 = arena_mut.atomic(0, 100, 0x01, vec![1, 2, 3]);
        let n2 = arena_mut.atomic(1, 50, 0x02, vec![4, 5, 6]);
        drop(arena_mut);

        // 串行组合
        let mut arena_mut = ctx.arena.borrow_mut();
        let seq = arena_mut.sequential(n1, n2);
        drop(arena_mut);

        // 验证结果
        let arena = ctx.arena.borrow();
        assert_eq!(arena.get(seq).duration(), 150);
    }
}
