/// Arena-based Morphism storage
///
/// Rust 完全不知道操作的语义，只关心 Monoidal Category 的代数结构：
/// - 串行组合 (@): duration 相加
/// - 并行组合 (|): duration 取 max + 通道冲突检测

use std::sync::Arc;

pub type ChannelId = u32;
pub type Time = u64;
pub type NodeId = u32;

/// 原子操作的载荷
///
/// 包含 OpCode 和不透明的二进制数据
/// Rust 不解析 data 的内容，只存储和传递
#[derive(Clone, Debug)]
pub struct AtomicPayload {
    pub opcode: u16,        // 操作码，如 0x0100 (TTL_ON)
    pub data: Arc<Vec<u8>>, // 不透明的参数 Blob（使用 Arc 支持零拷贝）
}

impl AtomicPayload {
    pub fn new(opcode: u16, data: Vec<u8>) -> Self {
        AtomicPayload {
            opcode,
            data: Arc::new(data),
        }
    }
}

/// Morphism 数据（存储在 Arena 中）
#[derive(Clone)]
pub enum MorphismData {
    /// 原子操作
    Atomic {
        channel_id: ChannelId,
        duration: Time,
        payload: AtomicPayload,  // OpCode + 不透明 Blob
    },
    /// 串行组合 (@)
    Sequential {
        lhs: NodeId,
        rhs: NodeId,
        duration: Time,              // 预计算：lhs.duration + rhs.duration
        channels: Vec<ChannelId>,    // 预计算：lhs ∪ rhs（排序去重）
    },
    /// 并行组合 (|)
    Parallel {
        lhs: NodeId,
        rhs: NodeId,
        duration: Time,              // 预计算：max(lhs.duration, rhs.duration)
        channels: Vec<ChannelId>,    // 预计算：lhs ∪ rhs（排序去重）
    },
}

impl MorphismData {
    /// 获取时长（O(1)）
    #[inline]
    pub fn duration(&self) -> Time {
        match self {
            MorphismData::Atomic { duration, .. } => *duration,
            MorphismData::Sequential { duration, .. } => *duration,
            MorphismData::Parallel { duration, .. } => *duration,
        }
    }

    /// 获取通道列表引用（O(1)）
    #[inline]
    pub fn channels(&self) -> &[ChannelId] {
        match self {
            MorphismData::Atomic { channel_id, .. } => {
                // 对于 Atomic，我们需要返回一个切片
                // 这里使用 unsafe 从单个值创建切片（性能优化）
                unsafe { std::slice::from_raw_parts(channel_id, 1) }
            }
            MorphismData::Sequential { channels, .. } => channels.as_slice(),
            MorphismData::Parallel { channels, .. } => channels.as_slice(),
        }
    }

    /// 获取通道向量（用于构建）
    pub fn channels_vec(&self) -> Vec<ChannelId> {
        match self {
            MorphismData::Atomic { channel_id, .. } => vec![*channel_id],
            MorphismData::Sequential { channels, .. } => channels.clone(),
            MorphismData::Parallel { channels, .. } => channels.clone(),
        }
    }
}

/// Arena 上下文 - 所有 Morphism 节点的存储
pub struct ArenaContext {
    pub nodes: Vec<MorphismData>,
}

impl ArenaContext {
    pub fn new() -> Self {
        ArenaContext {
            nodes: Vec::with_capacity(100_000),
        }
    }

    pub fn with_capacity(capacity: usize) -> Self {
        ArenaContext {
            nodes: Vec::with_capacity(capacity),
        }
    }

    /// 创建原子操作
    ///
    /// Args:
    ///     channel_id: 通道标识符
    ///     duration: 持续时间（时钟周期）
    ///     opcode: 操作码（u16），如 0x0100 (TTL_ON)
    ///     data: 不透明的参数 Blob
    pub fn atomic(&mut self, channel_id: ChannelId, duration: Time, opcode: u16, data: Vec<u8>) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(MorphismData::Atomic {
            channel_id,
            duration,
            payload: AtomicPayload::new(opcode, data),
        });
        id
    }

    /// 串行组合 (@)
    pub fn sequential(&mut self, lhs: NodeId, rhs: NodeId) -> NodeId {
        let lhs_data = &self.nodes[lhs as usize];
        let rhs_data = &self.nodes[rhs as usize];

        // 预计算 duration（O(1)）
        let duration = lhs_data.duration() + rhs_data.duration();

        // 预计算 channels（O(C log C)，C 为通道数，通常很小）
        let mut channels = lhs_data.channels_vec();
        channels.extend_from_slice(rhs_data.channels());
        channels.sort_unstable();
        channels.dedup();

        let id = self.nodes.len() as NodeId;
        self.nodes.push(MorphismData::Sequential {
            lhs,
            rhs,
            duration,
            channels,
        });
        id
    }

    /// 并行组合 (|)
    pub fn parallel(&mut self, lhs: NodeId, rhs: NodeId) -> Result<NodeId, String> {
        let lhs_data = &self.nodes[lhs as usize];
        let rhs_data = &self.nodes[rhs as usize];

        // 检测通道冲突（O(C)，C 为通道数）
        if has_intersection(lhs_data.channels(), rhs_data.channels()) {
            return Err("Parallel composition requires disjoint channels".to_string());
        }

        // 预计算 duration（O(1)）
        let duration = lhs_data.duration().max(rhs_data.duration());

        // 预计算 channels（O(C log C)）
        let mut channels = lhs_data.channels_vec();
        channels.extend_from_slice(rhs_data.channels());
        channels.sort_unstable();
        // 不需要 dedup，因为通道已经不相交

        let id = self.nodes.len() as NodeId;
        self.nodes.push(MorphismData::Parallel {
            lhs,
            rhs,
            duration,
            channels,
        });
        Ok(id)
    }

    /// 获取节点引用
    #[inline]
    pub fn get(&self, id: NodeId) -> &MorphismData {
        &self.nodes[id as usize]
    }

    /// 获取节点数量
    #[inline]
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    /// 检查是否为空
    #[inline]
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// 使用显式栈计算叶子节点数量（避免栈溢出）
    pub fn leaf_count(&self, root: NodeId) -> usize {
        let mut stack = vec![root];
        let mut count = 0;

        while let Some(node_id) = stack.pop() {
            let node = self.get(node_id);
            match node {
                MorphismData::Atomic { .. } => count += 1,
                MorphismData::Sequential { lhs, rhs, .. } => {
                    stack.push(*rhs);
                    stack.push(*lhs);
                }
                MorphismData::Parallel { lhs, rhs, .. } => {
                    stack.push(*rhs);
                    stack.push(*lhs);
                }
            }
        }

        count
    }

    /// 计算树的最大深度（使用显式栈）
    pub fn max_depth(&self, root: NodeId) -> usize {
        let mut stack = vec![(root, 1usize)];
        let mut max_depth = 0;

        while let Some((node_id, depth)) = stack.pop() {
            max_depth = max_depth.max(depth);

            let node = self.get(node_id);
            match node {
                MorphismData::Atomic { .. } => {}
                MorphismData::Sequential { lhs, rhs, .. }
                | MorphismData::Parallel { lhs, rhs, .. } => {
                    stack.push((*rhs, depth + 1));
                    stack.push((*lhs, depth + 1));
                }
            }
        }

        max_depth
    }
}

/// 检测两个排序后的切片是否有交集（O(n + m)）
fn has_intersection(a: &[ChannelId], b: &[ChannelId]) -> bool {
    let mut i = 0;
    let mut j = 0;

    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Equal => return true,
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
        }
    }

    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_atomic_creation() {
        let mut arena = ArenaContext::new();
        // opcode 和 data 对 Rust 来说是不透明的
        let node = arena.atomic(0, 100, 0x01, vec![1, 2, 3]);

        assert_eq!(arena.get(node).duration(), 100);
        assert_eq!(arena.get(node).channels(), &[0]);
    }

    #[test]
    fn test_sequential_composition() {
        let mut arena = ArenaContext::new();
        let n1 = arena.atomic(0, 100, 0x01, vec![]);
        let n2 = arena.atomic(0, 50, 0x02, vec![]);
        let seq = arena.sequential(n1, n2);

        assert_eq!(arena.get(seq).duration(), 150);
        assert_eq!(arena.get(seq).channels(), &[0]);
    }

    #[test]
    fn test_parallel_composition() {
        let mut arena = ArenaContext::new();
        let n1 = arena.atomic(0, 100, 0x01, vec![]);
        let n2 = arena.atomic(1, 200, 0x01, vec![]);
        let par = arena.parallel(n1, n2).unwrap();

        assert_eq!(arena.get(par).duration(), 200);
        assert_eq!(arena.get(par).channels(), &[0, 1]);
    }

    #[test]
    fn test_parallel_channel_conflict() {
        let mut arena = ArenaContext::new();
        let n1 = arena.atomic(0, 100, 0x01, vec![]);
        let n2 = arena.atomic(0, 100, 0x01, vec![]);
        let result = arena.parallel(n1, n2);

        assert!(result.is_err());
        assert!(result.unwrap_err().contains("disjoint"));
    }

    #[test]
    fn test_deep_chain() {
        let mut arena = ArenaContext::new();
        let mut root = arena.atomic(0, 1, 0x00, vec![]);

        for _ in 1..10_000 {
            let next = arena.atomic(0, 1, 0x00, vec![]);
            root = arena.sequential(root, next);
        }

        assert_eq!(arena.get(root).duration(), 10_000);
        assert_eq!(arena.leaf_count(root), 10_000);
    }

    #[test]
    fn test_has_intersection() {
        assert!(has_intersection(&[1, 2, 3], &[2, 4, 5]));
        assert!(!has_intersection(&[1, 2, 3], &[4, 5, 6]));
        assert!(has_intersection(&[1], &[1]));
        assert!(!has_intersection(&[], &[1, 2]));
    }

    #[test]
    fn test_complex_composition() {
        let mut arena = ArenaContext::new();

        // (A | B) @ C - Rust 只关心代数结构
        let a = arena.atomic(0, 100, 0x01, vec![]);
        let b = arena.atomic(1, 50, 0x01, vec![]);
        let c = arena.atomic(0, 30, 0x02, vec![]);

        let ab = arena.parallel(a, b).unwrap();
        assert_eq!(arena.get(ab).duration(), 100);

        let result = arena.sequential(ab, c);
        assert_eq!(arena.get(result).duration(), 130);
        assert_eq!(arena.get(result).channels(), &[0, 1]);
    }

    #[test]
    fn test_atomic_payload_storage() {
        // 验证 opcode 和 data 被正确存储（Rust 不解释其含义）
        let payload = AtomicPayload::new(0xABCD, vec![0x01, 0x02, 0x03]);
        assert_eq!(payload.opcode, 0xABCD);
        assert_eq!(*payload.data, vec![0x01, 0x02, 0x03]);
    }
}
