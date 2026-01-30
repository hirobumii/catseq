"""CatSeq V2 Morphism - Three-Phase Architecture

类型转换链：
    OpenMorphism ──(绑定通道)──> BoundMorphism ──(绑定初始状态)──> Morphism
      (模版)                      (通道已绑定)                   (完全物化)

使用示例：
    >>> from catseq.v2.morphism import OpenMorphism, BoundMorphism, parallel
    >>> from catseq.v2.ttl import ttl_on, ttl_pulse, TTLOff
    >>> from catseq.types.common import Board, Channel, ChannelType
    >>> from catseq.time_utils import us
    >>>
    >>> ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    >>> ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)
    >>>
    >>> # 用法 A: 直接构建
    >>> bound = ttl_on(ch0)
    >>> result = bound({ch0: TTLOff()})
    >>>
    >>> # 用法 B: 模版复用
    >>> template = ttl_pulse(10*us)
    >>> bound0 = template(ch0)
    >>> bound1 = template(ch1)
    >>>
    >>> # 用法 C: 多通道并行
    >>> bound = parallel({ch0: ttl_on(), ch1: ttl_pulse(10*us)})
    >>> result = bound({ch0: TTLOff(), ch1: TTLOff()})
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Iterator, TYPE_CHECKING

import catseq_rs

from catseq.types.common import Channel
from catseq.v2.context import get_context
from catseq.v2.opcodes import OpCode

if TYPE_CHECKING:
    pass


# =============================================================================
# Hardware State (抽象基类)
# =============================================================================

class HardwareState(ABC):
    """硬件状态基类 (必须不可变)

    子类代表具体的硬件状态：TTLOn, TTLOff, RWGActive 等。
    """

    @abstractmethod
    def is_compatible_with(self, other: HardwareState) -> bool:
        """检查是否可以转换到另一个状态"""
        ...


# =============================================================================
# 辅助函数
# =============================================================================

def encode_channel_id(channel: Channel) -> int:
    """将 Channel 编码为 u32

    编码格式: (board_num << 16) | local_id
    """
    board_num = int(channel.board.id.split("_")[-1])
    return (board_num << 16) | channel.local_id


# Identity/Wait 操作码
OP_IDENTITY = OpCode.IDENTITY  # 0x0000


# =============================================================================
# Morphism (Phase 3: 最终结果)
# =============================================================================

class Morphism:
    """Phase 3: Arena Graph Node Wrapper
    
    这是不可变的、轻量级的句柄，指向 Rust Arena 中的节点。
    所有的组合操作都是 O(1) 的图节点创建。
    """
    __slots__ = ("node_id", "end_states")

    def __init__(self, node_id: int, end_states: dict[Channel, HardwareState]):
        self.node_id = node_id
        self.end_states = end_states

    def __rshift__(self, other: Morphism) -> Morphism:
        """Sequential Composition (@)"""
        if not isinstance(other, Morphism):
            return NotImplemented
            
        ctx = get_context()
        # Rust 调用：创建一个指向这两个旧节点的新节点
        new_id = ctx.compose(self.node_id, other.node_id)
        
        # 状态追踪：覆盖旧状态
        new_states = {**self.end_states, **other.end_states}
        return Morphism(new_id, new_states)

    def __or__(self, other: Morphism) -> Morphism:
        """Parallel Composition (|)"""
        if not isinstance(other, Morphism):
            return NotImplemented
            
        ctx = get_context()
        # Rust 调用：可能抛出 ValueError (如果通道冲突)
        new_id = ctx.parallel(self.node_id, other.node_id)
        
        # 状态追踪：合并状态
        new_states = {**self.end_states, **other.end_states}
        return Morphism(new_id, new_states)
    
    # --- 进阶优化：支持 sum() 或 reduce 的批量操作 ---
    
    @staticmethod
    def sequential_all(morphisms: list[Morphism]) -> Morphism:
        """批量串行组合，生成平衡树而非偏斜树"""
        if not morphisms:
            raise ValueError("Empty list")
        
        ctx = get_context()
        ids = [m.node_id for m in morphisms]
        
        # 调用 Rust 的 compose_sequence 进行 O(N) 的平衡树构建
        root_id = ctx.compose_sequence(ids)
        
        # 简单合并所有状态（假设后面的覆盖前面的）
        final_states = {}
        for m in morphisms:
            final_states.update(m.end_states)
            
        return Morphism(root_id, final_states)

    def compile(self, ctx=None):
        if ctx is None:
            ctx = get_context()
        return ctx.compile_graph(self.node_id)


# =============================================================================
# BoundMorphism (Phase 2: 通道已绑定)
# =============================================================================

class BoundMorphism:
    """Phase 2: 通道已绑定，直接持有 Rust Arena 节点 ID

    实现严格的 Monoidal Category 语义，所有组合操作保证矩形对齐。
    内部维护 Dict[Channel, int] (Rust NodeId)，所有图构建在 append 时即时完成。
    """

    __slots__ = ("_nodes", "_durations")

    def __init__(
        self,
        data: Channel | dict[Channel, int],
        durations: dict[Channel, int] | None = None,
    ):
        """创建 BoundMorphism

        Args:
            data: 单个 Channel（自动创建 Identity(0) 节点）或已有的 nodes 字典
            durations: 各通道时长缓存（仅 dict 模式使用）
        """
        if isinstance(data, Channel):
            ctx = get_context()
            channel_id = encode_channel_id(data)
            node_id = ctx.atomic_id(channel_id, 0, OP_IDENTITY, b"")
            self._nodes: dict[Channel, int] = {data: node_id}
            self._durations: dict[Channel, int] = {data: 0}
        else:
            self._nodes = data
            self._durations = durations if durations is not None else {}

    def append(
        self,
        duration: int,
        opcode: int,
        payload: bytes,
        channel: Channel | None = None,
    ) -> None:
        """追加操作到指定通道（即时构建 Rust 图节点）

        Args:
            duration: 持续时间（时钟周期）
            opcode: 操作码
            payload: 载荷数据
            channel: 目标通道（单通道 BoundMorphism 可省略）

        Raises:
            ValueError: 多通道时未指定 channel
        """
        target_ch = channel

        if target_ch is None:
            if len(self._nodes) == 1:
                target_ch = next(iter(self._nodes))
            else:
                raise ValueError("多通道 BoundMorphism 必须指定 channel")

        ctx = get_context()
        ch_id = encode_channel_id(target_ch)

        if target_ch not in self._nodes:
            # 新通道：创建初始 Identity(0) 节点
            self._nodes[target_ch] = ctx.atomic_id(ch_id, 0, OP_IDENTITY, b"")
            self._durations[target_ch] = 0

        # 创建原子节点并串行组合
        atom_id = ctx.atomic_id(ch_id, duration, opcode, payload)
        self._nodes[target_ch] = ctx.compose(self._nodes[target_ch], atom_id)
        self._durations[target_ch] += duration

    @property
    def channels(self) -> set[Channel]:
        """获取涉及的通道集合"""
        return set(self._nodes.keys())

    @property
    def duration(self) -> int:
        """获取矩形时长（最长通道的持续时间）"""
        if not self._durations:
            return 0
        return max(self._durations.values())

    def __or__(self, other: BoundMorphism) -> BoundMorphism:
        """并行组合 (|): 矩形对齐

        通过在短通道末尾补 Identity 实现时间对齐。

        Returns:
            新的 BoundMorphism，所有通道时长相等

        Raises:
            ValueError: 如果通道有交集
        """
        overlap = set(self._nodes.keys()) & set(other._nodes.keys())
        if overlap:
            raise ValueError(f"并行组合通道冲突: {overlap}")

        target_duration = max(self.duration, other.duration)
        ctx = get_context()
        new_nodes: dict[Channel, int] = {}
        new_durations: dict[Channel, int] = {}

        for ch, nid in self._nodes.items():
            gap = target_duration - self._durations[ch]
            new_nodes[ch] = ctx.pad_end(nid, gap, OP_IDENTITY)
            new_durations[ch] = target_duration

        for ch, nid in other._nodes.items():
            gap = target_duration - other._durations[ch]
            new_nodes[ch] = ctx.pad_end(nid, gap, OP_IDENTITY)
            new_durations[ch] = target_duration

        return BoundMorphism(new_nodes, new_durations)

    def __rshift__(self, other: BoundMorphism) -> BoundMorphism:
        """串行组合 (>>): 填充与拼接

        三种情况：
        1. 交集通道 (A ∩ B): A 对齐后拼接 B
        2. A 独有 (A - B): A 对齐后补 Identity(dur_B)
        3. B 独有 (B - A): Identity(dur_A) 拼接 B

        Returns:
            新的 BoundMorphism
        """
        dur_a = self.duration
        dur_b = other.duration

        all_channels = set(self._nodes.keys()) | set(other._nodes.keys())
        ctx = get_context()
        new_nodes: dict[Channel, int] = {}
        new_durations: dict[Channel, int] = {}

        for ch in all_channels:
            node_a = self._nodes.get(ch)
            node_b = other._nodes.get(ch)

            if node_a is not None and node_b is not None:
                # Case 1: A >> B（都存在）
                # 先对齐 A 到 dur_a
                gap_a = dur_a - self._durations[ch]
                padded_a = ctx.pad_end(node_a, gap_a, OP_IDENTITY)
                # 拼接 B
                new_nodes[ch] = ctx.compose(padded_a, node_b)
                new_durations[ch] = dur_a + other._durations[ch]

            elif node_a is not None:
                # Case 2: A >> Id_B（A 存在，B 缺失）
                gap = (dur_a - self._durations[ch]) + dur_b
                new_nodes[ch] = ctx.pad_end(node_a, gap, OP_IDENTITY)
                new_durations[ch] = dur_a + dur_b

            else:
                # Case 3: Id_A >> B（A 缺失，B 存在）
                ch_id = encode_channel_id(ch)
                id_node = ctx.atomic_id(ch_id, dur_a, OP_IDENTITY, b"")
                new_nodes[ch] = ctx.compose(id_node, node_b)
                new_durations[ch] = dur_a + other._durations[ch]

        return BoundMorphism(new_nodes, new_durations)

    def __call__(
        self,
        start_states: dict[Channel, HardwareState],
        ctx: catseq_rs.CompilerContext | None = None,
    ) -> Morphism:
        """Finalize: 验证状态并创建 Morphism

        图节点已在 append/compose 时构建完毕，此处仅做状态检查和并行组合。

        Args:
            start_states: 各通道的起始状态
            ctx: CompilerContext（可选，默认使用全局）

        Returns:
            Morphism: 包含根节点 ID 和结束状态

        Raises:
            ValueError: 如果缺少起始状态或 BoundMorphism 为空
        """
        if ctx is None:
            ctx = get_context()

        final_nodes: list[int] = []
        final_end_states: dict[Channel, HardwareState] = {}

        for ch, node_id in self._nodes.items():
            state = start_states.get(ch)
            if state is None:
                raise ValueError(f"缺少通道 {ch} 的起始状态")

            final_nodes.append(node_id)
            # TODO: 实现完整的状态追踪
            final_end_states[ch] = state

        if len(final_nodes) == 0:
            raise ValueError("BoundMorphism 为空")
        elif len(final_nodes) == 1:
            root_id = final_nodes[0]
        else:
            root_id = ctx.parallel_compose_many(final_nodes)
            if root_id is None:
                raise ValueError("并行组合失败")

        return Morphism(root_id, final_end_states)

    def __repr__(self) -> str:
        channels = ", ".join(
            f"{ch.global_id}:dur={self._durations.get(ch, 0)}"
            for ch in self._nodes
        )
        return f"<BoundMorphism [{channels}] duration={self.duration}>"


# =============================================================================
# OpenMorphism (Phase 1: 惰性模版)
# =============================================================================

# 操作生成器类型：yields (duration, opcode, payload)
DataGenerator = Callable[[], Iterator[tuple[int, int, bytes]]]


class OpenMorphism:
    """Phase 1: State Transformer Function (惰性模版)

    OpenMorphism 包装一个数据生成器，在绑定通道时即时生成操作。
    这允许模版复用和惰性组合。

    组合操作符：
        >> : 串行组合（生成器拼接）
    """

    __slots__ = ('_gen', 'name')

    def __init__(self, gen: DataGenerator, name: str = "anon"):
        """创建 OpenMorphism

        Args:
            gen: 数据生成器函数，调用时 yields (duration, opcode, payload)
            name: 调试用名称
        """
        self._gen = gen
        self.name = name

    def __call__(self, channel: Channel) -> BoundMorphism:
        """绑定通道，即时生成操作到 BoundMorphism

        Args:
            channel: 目标硬件通道

        Returns:
            BoundMorphism: 通道已绑定的操作缓冲区
        """
        bm = BoundMorphism(channel)
        for duration, opcode, payload in self._gen():
            bm.append(duration, opcode, payload, channel)
        return bm

    def __rshift__(self, other: OpenMorphism) -> OpenMorphism:
        """串行组合 (>>): 生成器级别的拼接

        语法: seq = op1 >> op2

        语义: 执行 op1 的所有操作，然后执行 op2 的所有操作
        """
        left_gen = self._gen
        right_gen = other._gen

        def composed_gen() -> Iterator[tuple[int, int, bytes]]:
            yield from left_gen()
            yield from right_gen()

        return OpenMorphism(
            composed_gen,
            name=f"({self.name} >> {other.name})"
        )

    def __repr__(self) -> str:
        return f"<OpenMorphism: {self.name}>"


# =============================================================================
# parallel() 函数
# =============================================================================

def parallel(ops: dict[Channel, OpenMorphism]) -> BoundMorphism:
    """将多通道 OpenMorphism 并行组合为 BoundMorphism

    Args:
        ops: 通道到 OpenMorphism 的映射

    Returns:
        BoundMorphism: 多通道操作缓冲区，自动矩形对齐

    Example:
        >>> bound = parallel({ch0: ttl_on(), ch1: ttl_pulse(10*us)})
        >>> result = bound({ch0: TTLOff(), ch1: TTLOff()})
    """
    if not ops:
        raise ValueError("parallel() 需要至少一个操作")

    result: BoundMorphism | None = None
    for ch, op in ops.items():
        bm = op(ch)  # OpenMorphism -> BoundMorphism
        result = bm if result is None else result | bm

    assert result is not None
    return result
