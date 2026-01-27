"""Type stubs for catseq_rs - Rust-accelerated CatSeq backend.

This file provides type hints for IDE autocompletion and static type checking.
"""

from typing import Dict, List, Tuple, Optional, Any

class CompilerContext:
    """编译器上下文 - 管理 Arena 分配的节点。

    所有 Node 都必须通过 CompilerContext 创建。

    Example:
        >>> ctx = CompilerContext()
        >>> node = ctx.atomic(0, 100, 0x01, b"payload")
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

    def atomic_id(
        self,
        channel_id: int,
        duration: int,
        opcode: int,
        data: bytes,
    ) -> int:
        """创建原子操作并直接返回 NodeId。

        与 atomic() 类似，但直接返回 u32 而非 Node 对象。
        适用于只需要 NodeId 的场景（如 BoundMorphism Replay Pass）。

        Args:
            channel_id: 通道标识符（u32）。
            duration: 持续时间。
            opcode: 操作码（u16）。
            data: 数据载荷。

        Returns:
            NodeId (int).
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

    def compose_sequence(self, nodes: List[int]) -> Optional[int]:
        """批量串行组合（构建平衡树）。

        将线性 NodeId 列表构建为平衡的 Sequential 树，
        避免右偏树导致的递归深度问题。

        Args:
            nodes: NodeId 列表。

        Returns:
            组合后的根节点 ID，空列表返回 None。
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

    def parallel_compose_many(self, nodes: List[int]) -> Optional[int]:
        """批量并行组合（构建平衡树）。

        将多个节点并行组合为平衡树。
        要求所有节点的通道互不相交。

        Args:
            nodes: NodeId 列表。

        Returns:
            组合后的根节点 ID，空列表返回 None。

        Raises:
            ValueError: 如果任意两个节点的通道有交集。
        """
        ...

    def compile_graph(self, node_id: int) -> List[Tuple[int, int, int, bytes]]:
        """编译指定节点为事件列表。

        直接通过 NodeId 编译，无需创建 Node 对象。

        Args:
            node_id: 要编译的节点 ID。

        Returns:
            List[Tuple[int, int, int, bytes]]: [(time, channel_id, opcode, data), ...]
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
        >>> a = ctx.atomic(0, 100, 0x01, b"A")
        >>> b = ctx.atomic(0, 50, 0x02, b"B")
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

    def __repr__(self) -> str: 
        ...


class MorphismPath:
    """线性指令缓冲区 (Phase 2)。

    用于 BoundMorphism 的后端存储，支持 O(1) append 和 O(N) extend。
    """

    channel_id: int
    total_duration: int

    def __init__(self, channel_id: int) -> None:
        """创建空的 MorphismPath。"""
        ...

    @staticmethod
    def with_capacity(channel_id: int, capacity: int) -> "MorphismPath":
        """创建带预分配容量的 MorphismPath。"""
        ...

    def append(self, duration: int, opcode: int, payload: bytes) -> None:
        """追加单个操作。"""
        ...

    def extend(self, other: "MorphismPath") -> None:
        """扩展（拼接）另一个 Path。"""
        ...

    @staticmethod
    def identity(channel_id: int, duration: int, opcode: int) -> "MorphismPath":
        """创建恒等态射 (Wait)。

        Args:
            channel_id: 通道 ID
            duration: 持续时间
            opcode: Wait 操作码
        """
        ...

    def align(self, target_duration: int, opcode: int) -> None:
        """对齐时间边界。

        如果在末尾追加 Wait 操作，直到 total_duration 达到 target_duration。

        Args:
            target_duration: 目标时长
            opcode: Wait 操作码
        """
        ...

    def __len__(self) -> int: 
        ...
    def __iter__(self) -> "PathIterator": 
        ...
    def __copy__(self) -> "MorphismPath": 
        ...
    def __deepcopy__(self, memo: Any) -> "MorphismPath": 
        ...
    def __repr__(self) -> str: 
        ...


class PathIterator:
    """MorphismPath 的迭代器。

    用于 Python 端的 Replay Pass。
    """

    def __iter__(self) -> "PathIterator": 
        ...
    def __next__(self) -> Tuple[int, int, bytes]:
        """返回 (duration, opcode, payload)。"""
        ...


class ProgramArena:
    """Program Arena - 存储所有 Program AST 节点和 Value。

    这是 Handle-based 架构的核心：
    - Python 对象只持有 `node_id` 或 `value_id`
    - 所有数据存储在这个 Arena 中
    - 支持高效的节点共享和内存管理
    """

    def __init__(self) -> None:
        """创建空的 ProgramArena。"""
        ...

    @staticmethod
    def with_capacity(node_capacity: int, value_capacity: int) -> "ProgramArena":
        """创建带预分配容量的 ProgramArena。"""
        ...

    def node_count(self) -> int:
        """获取节点数量。"""
        ...

    def value_count(self) -> int:
        """获取 Value 数量。"""
        ...

    def var_count(self) -> int:
        """获取变量数量。"""
        ...

    def clear(self) -> None:
        """清空 Arena（用于重置）。"""
        ...

    def literal(self, value: int) -> int:
        """创建整数字面量。"""
        ...

    def literal_float(self, value: float) -> int:
        """创建浮点数字面量。"""
        ...

    def variable(self, name: str, type_hint: str) -> int:
        """创建或获取变量。"""
        ...

    def binary_expr(self, lhs: int, op: str, rhs: int) -> int:
        """创建二元表达式。"""
        ...

    def unary_expr(self, op: str, operand: int) -> int:
        """创建一元表达式。"""
        ...

    def condition(self, lhs: int, op: str, rhs: int) -> int:
        """创建条件表达式。"""
        ...

    def logical_expr(self, lhs: int, op: str, rhs: Optional[int] = None) -> int:
        """创建逻辑表达式。"""
        ...

    def lift(self, morphism_ref: int, params: Dict[str, int]) -> int:
        """创建 Lift 节点。"""
        ...

    def delay(self, duration: int, max_hint: Optional[int] = None) -> int:
        """创建 Delay 节点。"""
        ...

    def set_var(self, target: int, value: int) -> int:
        """创建 Set 节点。"""
        ...

    def chain(self, left: int, right: int) -> int:
        """创建 Chain 节点。"""
        ...

    def loop_(self, count: int, body: int) -> int:
        """创建 Loop 节点。"""
        ...

    def match_(self, subject: int, cases: Dict[int, int], default: Optional[int] = None) -> int:
        """创建 Match 节点。"""
        ...

    def apply(self, func: int, args: List[int]) -> int:
        """创建 Apply 节点。"""
        ...

    def func_def(self, name: str, params: List[int], body: int) -> int:
        """创建 FuncDef 节点。"""
        ...

    def measure(self, target: int, source: int) -> int:
        """创建 Measure 节点。"""
        ...

    def identity(self) -> int:
        """创建 Identity 节点。"""
        ...

    def chain_sequence(self, nodes: List[int]) -> Optional[int]:
        """批量 Chain 组合。"""
        ...

    def is_literal(self, value_id: int) -> bool:
        """检查 ValueId 是否为字面量。"""
        ...

    def is_variable(self, value_id: int) -> bool:
        """检查 ValueId 是否为变量。"""
        ...

    def get_literal_int(self, value_id: int) -> Optional[int]:
        """获取字面量的整数值。"""
        ...

    def get_literal_float(self, value_id: int) -> Optional[float]:
        """获取字面量的浮点值。"""
        ...

    def get_variable_name(self, value_id: int) -> Optional[str]:
        """获取变量名。"""
        ...
