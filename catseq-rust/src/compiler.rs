/// 编译器 - 将 Morphism 树展平为时间排序的事件列表
///
/// 使用显式栈机器避免递归深度限制

use crate::arena::{ArenaContext, ChannelId, MorphismData, NodeId, Time};
use std::sync::Arc;

/// 扁平事件 - 编译后的输出
///
/// 使用 Arc 包装 data 以支持零拷贝共享（增量编译需要）
#[derive(Debug, Clone)]
pub struct FlatEvent {
    pub time: Time,
    pub channel_id: ChannelId,
    pub opcode: u16,         // 操作码，由 Python 层解释
    pub data: Arc<Vec<u8>>,  // 不透明参数 Blob
}

/// 编译 Morphism 为扁平事件列表
///
/// 算法：
/// 1. 使用显式栈进行深度优先遍历
/// 2. 追踪每个节点的开始时间
/// 3. 收集所有原子操作的 (time, channel, payload)
/// 4. 按时间排序
///
/// 时间复杂度：O(N log N)，N 为节点数
/// 空间复杂度：O(N)
pub fn compile(arena: &ArenaContext, root: NodeId) -> Vec<FlatEvent> {
    let mut stack = vec![(root, 0u64)];
    let mut events = Vec::new();

    while let Some((node_id, start_time)) = stack.pop() {
        let node = arena.get(node_id);

        match node {
            MorphismData::Atomic {
                channel_id,
                payload,
                ..
            } => {
                // payload.data 已经是 Arc<Vec<u8>>，直接克隆 Arc（零拷贝）
                events.push(FlatEvent {
                    time: start_time,
                    channel_id: *channel_id,
                    opcode: payload.opcode,
                    data: payload.data.clone(),
                });
            }
            MorphismData::Sequential { lhs, rhs, .. } => {
                let lhs_duration = arena.get(*lhs).duration();
                // 右子树时间偏移
                stack.push((*rhs, start_time + lhs_duration));
                // 左子树保持当前时间（后进先出确保左优先）
                stack.push((*lhs, start_time));
            }
            MorphismData::Parallel { lhs, rhs, .. } => {
                // 两者同时开始
                stack.push((*rhs, start_time));
                stack.push((*lhs, start_time));
            }
        }
    }

    // 按时间排序（稳定排序保持相同时间的原始顺序）
    events.sort_by_key(|e| e.time);
    events
}

/// 编译并按板卡分组
///
/// 假设 channel_id 的高 16 位是 board_id
pub fn compile_by_board(
    arena: &ArenaContext,
    root: NodeId,
) -> std::collections::HashMap<u16, Vec<FlatEvent>> {
    let events = compile(arena, root);

    let mut grouped = std::collections::HashMap::new();
    for event in events {
        let board_id = (event.channel_id >> 16) as u16;
        grouped.entry(board_id).or_insert_with(Vec::new).push(event);
    }

    grouped
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arena::ArenaContext;

    #[test]
    fn test_compile_atomic() {
        let mut arena = ArenaContext::new();
        // opcode (0x01) 对编译器来说是不透明的
        let node = arena.atomic(0, 100, 0x01, vec![1, 2, 3]);

        let events = compile(&arena, node);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].time, 0);
        assert_eq!(events[0].channel_id, 0);
        assert_eq!(*events[0].data, vec![1, 2, 3]);
    }

    #[test]
    fn test_compile_sequential() {
        let mut arena = ArenaContext::new();
        let n1 = arena.atomic(0, 100, 0x01, vec![1]);
        let n2 = arena.atomic(0, 50, 0x02, vec![2]);
        let seq = arena.sequential(n1, n2);

        let events = compile(&arena, seq);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].time, 0);
        assert_eq!(*events[0].data, vec![1]);
        assert_eq!(events[1].time, 100);
        assert_eq!(*events[1].data, vec![2]);
    }

    #[test]
    fn test_compile_parallel() {
        let mut arena = ArenaContext::new();
        let n1 = arena.atomic(0, 100, 0x01, vec![1]);
        let n2 = arena.atomic(1, 200, 0x01, vec![2]);
        let par = arena.parallel(n1, n2).unwrap();

        let events = compile(&arena, par);
        assert_eq!(events.len(), 2);
        // 两者同时开始
        assert_eq!(events[0].time, 0);
        assert_eq!(events[1].time, 0);
        // 按时间排序后，按原始顺序
        assert!(events[0].channel_id == 0 || events[0].channel_id == 1);
    }

    #[test]
    fn test_compile_complex() {
        let mut arena = ArenaContext::new();

        // (A | B) @ C - 纯代数组合
        let a = arena.atomic(0, 100, 0x01, vec![10]);
        let b = arena.atomic(1, 50, 0x01, vec![20]);
        let c = arena.atomic(0, 30, 0x02, vec![30]);

        let ab = arena.parallel(a, b).unwrap();
        let result = arena.sequential(ab, c);

        let events = compile(&arena, result);
        assert_eq!(events.len(), 3);

        // A at t=0, B at t=0, C at t=100
        assert_eq!(events[0].time, 0);
        assert_eq!(events[1].time, 0);
        assert_eq!(events[2].time, 100);
        assert_eq!(*events[2].data, vec![30u8]);
    }

    #[test]
    fn test_compile_deep_chain() {
        let mut arena = ArenaContext::new();
        let mut root = arena.atomic(0, 10, 0x00, vec![0]);

        for i in 1..100 {
            let next = arena.atomic(0, 10, 0x00, vec![i]);
            root = arena.sequential(root, next);
        }

        let events = compile(&arena, root);
        assert_eq!(events.len(), 100);

        // 验证时间递增
        for (i, event) in events.iter().enumerate() {
            assert_eq!(event.time, (i as u64) * 10);
        }
    }

    #[test]
    fn test_compile_wide_parallel() {
        let mut arena = ArenaContext::new();

        // 创建 100 个并行通道
        let mut nodes = Vec::new();
        for i in 0..100 {
            nodes.push(arena.atomic(i, 10 * (i as u64 + 1), 0x01, vec![i as u8]));
        }

        // 逐步并行组合
        let mut root = nodes[0];
        for &node in &nodes[1..] {
            root = arena.parallel(root, node).unwrap();
        }

        let events = compile(&arena, root);
        assert_eq!(events.len(), 100);

        // 所有事件在 t=0 开始
        for event in &events {
            assert_eq!(event.time, 0);
        }
    }

    #[test]
    fn test_compile_by_board() {
        let mut arena = ArenaContext::new();

        // board_id 编码在 channel_id 的高 16 位
        let ch0_board0 = 0u32;           // board 0, channel 0
        let ch1_board0 = 1u32;           // board 0, channel 1
        let ch0_board1 = 1u32 << 16;     // board 1, channel 0

        let n1 = arena.atomic(ch0_board0, 100, 0x01, vec![1]);
        let n2 = arena.atomic(ch1_board0, 100, 0x01, vec![2]);
        let n3 = arena.atomic(ch0_board1, 100, 0x01, vec![3]);

        let par1 = arena.parallel(n1, n2).unwrap();
        let par2 = arena.parallel(par1, n3).unwrap();

        let grouped = compile_by_board(&arena, par2);

        assert_eq!(grouped.len(), 2);
        assert_eq!(grouped[&0].len(), 2); // board 0 有 2 个事件
        assert_eq!(grouped[&1].len(), 1); // board 1 有 1 个事件
    }
}
