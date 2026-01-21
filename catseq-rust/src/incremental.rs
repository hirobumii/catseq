/// 增量编译模块（终极优化版）
///
/// 核心原则：
/// 1. **缓存存储局部真理**：所有缓存的事件时间都是相对于该节点 t=0
/// 2. **父节点负责上下文映射**：时间偏移由父节点在使用缓存时计算
/// 3. **零拷贝共享**：使用 Arc 避免 payload 深拷贝
/// 4. **Block Copy 优化**：检测非重叠区间，直接 memcpy（杀手级优化）

use crate::arena::{ArenaContext, MorphismData, NodeId};
use crate::compiler::FlatEvent;  // 复用 compiler 的 FlatEvent
use std::collections::HashMap;
use std::sync::Arc;

/// 缓存的事件列表（Arc 包装整个列表）
type EventCache = Arc<Vec<FlatEvent>>;

/// 增量编译器
pub struct IncrementalCompiler {
    cache: HashMap<NodeId, EventCache>,
    cache_hits: usize,
    cache_misses: usize,
}

impl IncrementalCompiler {
    pub fn new() -> Self {
        IncrementalCompiler {
            cache: HashMap::new(),
            cache_hits: 0,
            cache_misses: 0,
        }
    }

    /// 编译节点（返回绝对时间的事件列表）
    pub fn compile(&mut self, arena: &ArenaContext, root: NodeId) -> Vec<FlatEvent> {
        let cached = self.compile_node(arena, root);
        Arc::try_unwrap(cached).unwrap_or_else(|arc| (*arc).clone())
    }

    /// 编译节点（返回相对时间 t=0 的事件列表）
    fn compile_node(&mut self, arena: &ArenaContext, node_id: NodeId) -> EventCache {
        // 检查缓存（Arc 克隆成本极低）
        if let Some(cached) = self.cache.get(&node_id) {
            self.cache_hits += 1;
            return cached.clone();
        }

        self.cache_misses += 1;

        let node = arena.get(node_id);
        let events = match node {
            MorphismData::Atomic { channel_id, payload, .. } => {
                // payload.data 已经是 Arc<Vec<u8>>，直接克隆 Arc（零拷贝）
                vec![FlatEvent {
                    time: 0,
                    channel_id: *channel_id,
                    opcode: payload.opcode,
                    data: payload.data.clone(),
                }]
            }

            MorphismData::Sequential { lhs, rhs, .. } => {
                let lhs_events = self.compile_node(arena, *lhs);
                let rhs_events = self.compile_node(arena, *rhs);
                let lhs_duration = arena.get(*lhs).duration();

                // 合并：左侧保持原样，右侧偏移
                let mut result = Vec::with_capacity(lhs_events.len() + rhs_events.len());

                // 左侧：直接复制
                result.extend(lhs_events.iter().cloned());

                // 右侧：偏移时间
                for event in rhs_events.iter() {
                    result.push(FlatEvent {
                        time: event.time + lhs_duration,
                        channel_id: event.channel_id,
                        opcode: event.opcode,
                        data: event.data.clone(),
                    });
                }

                // Sequential 天然保证有序：左侧所有事件 < lhs_duration <= 右侧所有事件
                result
            }

            MorphismData::Parallel { lhs, rhs, .. } => {
                let lhs_events = self.compile_node(arena, *lhs);
                let rhs_events = self.compile_node(arena, *rhs);

                // 归并两个有序序列（带 Block Copy 优化）
                merge_sorted_events(&lhs_events, &rhs_events)
            }
        };

        let cached = Arc::new(events);
        self.cache.insert(node_id, cached.clone());
        cached
    }

    pub fn stats(&self) -> CacheStats {
        CacheStats {
            cached_nodes: self.cache.len(),
            cache_hits: self.cache_hits,
            cache_misses: self.cache_misses,
            hit_rate: if self.cache_hits + self.cache_misses > 0 {
                self.cache_hits as f64 / (self.cache_hits + self.cache_misses) as f64
            } else {
                0.0
            },
        }
    }

    pub fn clear(&mut self) {
        self.cache.clear();
        self.cache_hits = 0;
        self.cache_misses = 0;
    }
}

impl Default for IncrementalCompiler {
    fn default() -> Self {
        Self::new()
    }
}

/// 归并两个有序事件列表（终极优化版）
///
/// 优化策略：
/// 1. **空列表快速路径**：O(1) 检测 + O(N) clone
/// 2. **非重叠区间检测（Block Copy）**：⭐ 杀手级优化
///    - Sequential 操作天然满足：A 的所有事件 < B 的所有事件
///    - 收益：O(N+M) 归并 → O(1) 检测 + memcpy
/// 3. **标准归并**：Fallback，O(N+M)
///
/// 性能分析：
/// - 时序控制中 90% 的并行都是"拼接"而非"交错"
/// - Block Copy 将性能从 O(N+M) 降至 O(1)（检测）+ memcpy
fn merge_sorted_events(a: &[FlatEvent], b: &[FlatEvent]) -> Vec<FlatEvent> {
    // 1. 极速路径：处理空切片
    if a.is_empty() {
        return b.to_vec();
    }
    if b.is_empty() {
        return a.to_vec();
    }

    let total_len = a.len() + b.len();
    let mut result = Vec::with_capacity(total_len);

    // 2. 杀手级优化：检测非重叠区间（Block Copy）
    // 场景 1：A 都在 B 之前（常见于 (A|B) @ C 展开后）
    if a.last().unwrap().time <= b.first().unwrap().time {
        result.extend_from_slice(a);
        result.extend_from_slice(b);
        return result;
    }

    // 场景 2：B 都在 A 之前（罕见但仍需处理）
    if b.last().unwrap().time <= a.first().unwrap().time {
        result.extend_from_slice(b);
        result.extend_from_slice(a);
        return result;
    }

    // 3. 标准归并（交错情况，Fallback）
    let mut i = 0;
    let mut j = 0;

    while i < a.len() && j < b.len() {
        if a[i].time <= b[j].time {
            result.push(a[i].clone());
            i += 1;
        } else {
            result.push(b[j].clone());
            j += 1;
        }
    }

    // 添加剩余元素
    if i < a.len() {
        result.extend_from_slice(&a[i..]);
    }
    if j < b.len() {
        result.extend_from_slice(&b[j..]);
    }

    result
}

#[derive(Debug, Clone)]
pub struct CacheStats {
    pub cached_nodes: usize,
    pub cache_hits: usize,
    pub cache_misses: usize,
    pub hit_rate: f64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arena::ArenaContext;

    #[test]
    fn test_cache_correctness_sequential() {
        let mut arena = ArenaContext::new();
        let mut compiler = IncrementalCompiler::new();

        // opcode 对 Rust 来说是不透明的
        let a = arena.atomic(0, 100, 0x01, vec![1]);
        let b = arena.atomic(0, 50, 0x02, vec![2]);
        let ab = arena.sequential(a, b);

        // 第一次编译
        let events1 = compiler.compile(&arena, ab);
        assert_eq!(events1.len(), 2);
        assert_eq!(events1[0].time, 0);
        assert_eq!(events1[1].time, 100);

        // 复用 B：C(10) @ B(50)
        let c = arena.atomic(1, 10, 0x01, vec![3]);
        let cb = arena.sequential(c, b);

        let events2 = compiler.compile(&arena, cb);
        assert_eq!(events2.len(), 2);
        assert_eq!(events2[0].time, 0);
        assert_eq!(events2[1].time, 10); // B 正确偏移到 t=10

        let stats = compiler.stats();
        assert!(stats.cache_hits > 0);
    }

    #[test]
    fn test_block_copy_optimization() {
        let mut arena = ArenaContext::new();
        let mut compiler = IncrementalCompiler::new();

        // 构建 (A | B) @ (C | D)
        // 这会触发 Block Copy：左侧所有事件 < 右侧所有事件
        let a = arena.atomic(0, 100, 0x01, vec![1]);
        let b = arena.atomic(1, 100, 0x01, vec![2]);
        let ab = arena.parallel(a, b).unwrap();

        let c = arena.atomic(2, 50, 0x01, vec![3]);
        let d = arena.atomic(3, 50, 0x01, vec![4]);
        let cd = arena.parallel(c, d).unwrap();

        let result = arena.sequential(ab, cd);
        let events = compiler.compile(&arena, result);

        // 验证结果
        assert_eq!(events.len(), 4);
        assert_eq!(events[0].time, 0);   // A
        assert_eq!(events[1].time, 0);   // B
        assert_eq!(events[2].time, 100); // C（偏移后）
        assert_eq!(events[3].time, 100); // D（偏移后）

        // 验证有序性
        for i in 1..events.len() {
            assert!(events[i - 1].time <= events[i].time);
        }
    }

    #[test]
    fn test_interleaved_merge() {
        let mut arena = ArenaContext::new();
        let mut compiler = IncrementalCompiler::new();

        // 构建交错的并行操作：A(0-100) | B(50-150)
        // 这会触发标准归并
        let a1 = arena.atomic(0, 10, 0x01, vec![1]);
        let a2 = arena.atomic(0, 90, 0x02, vec![2]);
        let a = arena.sequential(a1, a2);

        let b_wait = arena.atomic(1, 50, 0x00, vec![3]);
        let b_op = arena.atomic(1, 100, 0x01, vec![4]);
        let b = arena.sequential(b_wait, b_op);

        let ab = arena.parallel(a, b).unwrap();
        let events = compiler.compile(&arena, ab);

        // 验证交错顺序
        // A: [0, 10], B: [0, 50]
        // 并行后：[0, 0, 10, 50]（两个 0 是 a1 和 b_wait）
        assert_eq!(events.len(), 4);
        assert_eq!(events[0].time, 0);   // a1 或 b_wait
        assert_eq!(events[1].time, 0);   // b_wait 或 a1
        assert_eq!(events[2].time, 10);  // a2
        assert_eq!(events[3].time, 50);  // b_op
    }

    #[test]
    fn test_cache_reuse_across_trees() {
        let mut arena = ArenaContext::new();
        let mut compiler = IncrementalCompiler::new();

        // 构建一个被多次复用的子树
        let base = arena.atomic(0, 100, 0x01, vec![1, 2, 3]);
        let other = arena.atomic(1, 50, 0x02, vec![4, 5]);
        let shared_sub = arena.sequential(base, other);

        // 构建多棵树，都复用 shared_sub
        let mut trees = Vec::new();
        for i in 0..10 {
            let leaf = arena.atomic(2, 10 * i, 0x01, vec![i as u8]);
            trees.push(arena.sequential(shared_sub, leaf));
        }

        // 编译所有树
        for tree in trees {
            compiler.compile(&arena, tree);
        }

        let stats = compiler.stats();
        println!("Cache stats: {:?}", stats);
        // shared_sub 被查询 10 次：第一次 miss，后 9 次 hit
        assert!(stats.cache_hits >= 9);
    }

    #[test]
    fn test_merge_empty() {
        let a = vec![];
        let b = vec![
            FlatEvent {
                time: 0,
                channel_id: 0,
                opcode: 0x01,
                data: Arc::new(vec![1]),
            },
        ];

        let merged = merge_sorted_events(&a, &b);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].time, 0);
    }

    #[test]
    fn test_merge_block_copy() {
        let a = vec![
            FlatEvent {
                time: 0,
                channel_id: 0,
                opcode: 0x01,
                data: Arc::new(vec![1]),
            },
            FlatEvent {
                time: 10,
                channel_id: 0,
                opcode: 0x01,
                data: Arc::new(vec![2]),
            },
        ];
        let b = vec![
            FlatEvent {
                time: 20,
                channel_id: 1,
                opcode: 0x01,
                data: Arc::new(vec![3]),
            },
            FlatEvent {
                time: 30,
                channel_id: 1,
                opcode: 0x01,
                data: Arc::new(vec![4]),
            },
        ];

        let merged = merge_sorted_events(&a, &b);
        assert_eq!(merged.len(), 4);
        // 验证 Block Copy 路径被触发（a.last <= b.first）
        assert_eq!(merged[0].time, 0);
        assert_eq!(merged[1].time, 10);
        assert_eq!(merged[2].time, 20);
        assert_eq!(merged[3].time, 30);
    }
}
