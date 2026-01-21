"""Type stubs for catseq_rs - Rust-accelerated CatSeq backend.

This file provides type hints for IDE autocompletion and static type checking.
"""

from typing import Dict, List, Tuple, Optional

class CompilerContext:
    """编译器上下文 - 管理 Arena 分配的节点。

    所有 Node 都必须通过 CompilerContext 创建。

    Example:
        >>> ctx = CompilerContext()
        >>> node = ctx.atomic(0, 100, b"payload")
        >>> ctx.node_count()
        1
    """

    def __init__(self) -> None:
        """创建新的编译器上下文。"""
        ...

    @staticmethod
    def with_capacity(capacity: int) -> "CompilerContext":
        """创建带预分配容量的上下文。

        Args:
            capacity: 预分配的节点数量，用于避免频繁重分配。

        Returns:
            新的 CompilerContext 实例。
        """
        ...

    def atomic(
        self,
        channel_id: int,
        duration: int,
        opcode: int,
        data: bytes,
    ) -> "Node":
        """创建原子操作节点。

        Args:
            channel_id: 通道标识符（u32），高 16 位为 board_id。
            duration: 持续时间（时钟周期）。
            opcode: 操作码（u16），由 Python 层定义，Rust 不解释。
            data: 不透明的参数 Blob，由 Python 层解释。

        Returns:
            新创建的 Node 句柄。

        Example:
            >>> ctx = CompilerContext()
            >>> node = ctx.atomic(0, 250, 0x0100, b"\\x01")
            >>> node.duration
            250
        """
        ...

    def enable_incremental(self) -> None:
        """启用增量编译。

        增量编译会缓存已编译的子树，提升复用场景的性能。
        """
        ...

    def disable_incremental(self) -> None:
        """禁用增量编译并清空缓存。"""
        ...

    def is_incremental_enabled(self) -> bool:
        """检查是否启用了增量编译。"""
        ...

    def get_incremental_stats(self) -> Optional[Tuple[int, int, int, float]]:
        """获取增量编译统计信息。

        Returns:
            如果启用了增量编译，返回 (cached_nodes, cache_hits, cache_misses, hit_rate)。
            如果未启用，返回 None。
        """
        ...

    def clear_incremental_cache(self) -> None:
        """清空增量编译缓存（但保持启用状态）。"""
        ...

    def node_count(self) -> int:
        """获取当前 Arena 中的节点总数。"""
        ...

    def clear(self) -> None:
        """清空 Arena 中的所有节点。"""
        ...

    def compose(self, a: int, b: int) -> int:
        """串行组合两个节点（通过 NodeId）。

        用于 OpenMorphism 模式，Python 层直接操作 NodeId。

        Args:
            a: 第一个节点的 ID
            b: 第二个节点的 ID

        Returns:
            新创建的串行组合节点 ID
        """
        ...

    def parallel_compose(self, a: int, b: int) -> int:
        """并行组合两个节点（通过 NodeId）。

        用于 OpenMorphism 模式，Python 层直接操作 NodeId。

        Args:
            a: 第一个节点的 ID
            b: 第二个节点的 ID

        Returns:
            新创建的并行组合节点 ID

        Raises:
            ValueError: 如果两个节点的通道有交集
        """
        ...

    def get_duration(self, node_id: int) -> int:
        """获取节点时长（通过 NodeId）。"""
        ...

    def get_channels(self, node_id: int) -> List[int]:
        """获取节点涉及的通道（通过 NodeId）。"""
        ...

    def __repr__(self) -> str: ...


class Node:
    """Morphism 节点句柄。

    Node 是轻量级的句柄（仅包含 NodeId 和 Context 引用），
    实际数据存储在 CompilerContext 的 Arena 中。

    支持的操作符：
        - `@` (matmul): 串行组合
        - `|` (or): 并行组合（通道必须不相交）

    Example:
        >>> ctx = CompilerContext()
        >>> a = ctx.atomic(0, 100, b"A")
        >>> b = ctx.atomic(0, 50, b"B")
        >>> seq = a @ b  # 串行：总时长 150
        >>> seq.duration
        150
    """

    @property
    def node_id(self) -> int:
        """获取节点 ID（用于 OpenMorphism 模式）。"""
        ...

    @property
    def duration(self) -> int:
        """获取总时长（时钟周期）。"""
        ...

    @property
    def channels(self) -> List[int]:
        """获取涉及的通道列表（channel_id）。"""
        ...

    def __matmul__(self, other: "Node") -> "Node":
        """串行组合 (@)。

        self @ other: 先执行 self，再执行 other。
        结果时长 = self.duration + other.duration

        Args:
            other: 要串行连接的节点。

        Returns:
            新的复合节点。
        """
        ...

    def __or__(self, other: "Node") -> "Node":
        """并行组合 (|)。

        self | other: 同时执行 self 和 other。
        结果时长 = max(self.duration, other.duration)

        Args:
            other: 要并行执行的节点。

        Returns:
            新的复合节点。

        Raises:
            ValueError: 如果 self 和 other 的通道有交集。
        """
        ...

    def compile(self) -> List[Tuple[int, int, int, bytes]]:
        """编译为扁平事件列表。

        如果启用了增量编译，会自动使用缓存。

        Returns:
            事件列表 [(time, channel_id, opcode, data), ...]，按时间排序。

        Example:
            >>> ctx = CompilerContext()
            >>> a = ctx.atomic(0, 100, 0x0100, b"\\x01")
            >>> b = ctx.atomic(0, 50, 0x0101, b"\\x00")
            >>> (a @ b).compile()
            [(0, 0, 256, b'\\x01'), (100, 0, 257, b'\\x00')]
        """
        ...

    def compile_by_board(self) -> Dict[int, List[Tuple[int, int, int, bytes]]]:
        """编译并按板卡分组。

        假设 channel_id 的高 16 位是 board_id。

        Returns:
            板卡到事件列表的映射 {board_id: [(time, channel_id, opcode, data), ...]}
        """
        ...

    def leaf_count(self) -> int:
        """获取叶子节点（原子操作）数量。"""
        ...

    def max_depth(self) -> int:
        """获取树的最大深度。"""
        ...

    def __repr__(self) -> str: ...
