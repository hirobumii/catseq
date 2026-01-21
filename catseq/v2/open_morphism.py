"""CatSeq V2 OpenMorphism - State Monad Pattern

架构原则：
- Rust 只关心 Monoidal Category 的代数结构（@, |）
- Python 负责状态流（State Monad）和语义解释
- Payload 使用 struct.pack，不使用 pickle

类型定义：
- Morphism: NamedTuple(node_id: int, end_state: HardwareState)
- Kleisli: Callable[[CompilerContext, Channel, HardwareState], Morphism]

使用示例：
    >>> ctx = catseq_rs.CompilerContext()
    >>> ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    >>>
    >>> # 定义 OpenMorphism（惰性）
    >>> pulse = ttl_on() >> wait(10*us) >> ttl_off()
    >>>
    >>> # 物化（执行）
    >>> result = pulse(ctx, ch, TTLOff())
    >>> print(result.node_id, result.end_state)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, NamedTuple, TYPE_CHECKING

from catseq.types.common import Channel

if TYPE_CHECKING:
    import catseq_rs


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
# Morphism (物化结果)
# =============================================================================

class Morphism(NamedTuple):
    """物化后的 Morphism 结果

    Attributes:
        node_id: Rust Arena 中的节点 ID
        end_state: 执行后的硬件状态
    """
    node_id: int
    end_state: HardwareState


# =============================================================================
# Kleisli Arrow (类型别名)
# =============================================================================

# Kleisli 箭头：(ctx, channel, start_state) -> Morphism
Kleisli = Callable[["catseq_rs.CompilerContext", Channel, HardwareState], Morphism]


# =============================================================================
# OpenMorphism (State Transformer)
# =============================================================================

class OpenMorphism:
    """State Transformer Function

    OpenMorphism 包装一个 Kleisli 函数：
        (CompilerContext, Channel, HardwareState) -> Morphism

    在被调用（物化）之前，不会在 Rust Arena 中创建任何节点。
    这允许惰性组合和优化。

    组合操作符：
        >> : 串行组合（Monadic Bind）
        |  : 并行组合（需要不同通道）
    """

    __slots__ = ('_kleisli', 'name')

    def __init__(self, kleisli: Kleisli, name: str = "anon"):
        """创建 OpenMorphism

        Args:
            kleisli: Kleisli 函数 (ctx, channel, state) -> Morphism
            name: 调试用名称
        """
        self._kleisli = kleisli
        self.name = name

    def __call__(
        self,
        ctx: catseq_rs.CompilerContext,
        channel: Channel,
        start_state: HardwareState,
    ) -> Morphism:
        """物化 OpenMorphism

        执行内部的 Kleisli 函数，在 Rust Arena 中创建节点。

        Args:
            ctx: Rust CompilerContext
            channel: 目标硬件通道
            start_state: 起始硬件状态

        Returns:
            Morphism(node_id, end_state)
        """
        return self._kleisli(ctx, channel, start_state)

    def __rshift__(self, other: OpenMorphism) -> OpenMorphism:
        """串行组合 (Monadic Bind)

        语法: seq = op1 >> op2

        语义:
            op1(s0) -> Morphism(n1, s1)
            op2(s1) -> Morphism(n2, s2)  # s1 传递给 op2
            return Morphism(compose(n1, n2), s2)
        """
        left = self
        right = other

        def composed_kleisli(
            ctx: catseq_rs.CompilerContext,
            channel: Channel,
            s0: HardwareState,
        ) -> Morphism:
            # 执行第一个操作
            m1 = left._kleisli(ctx, channel, s0)

            # 将中间状态传递给第二个操作
            m2 = right._kleisli(ctx, channel, m1.end_state)

            # 在 Rust 中组合节点
            combined_id = ctx.compose(m1.node_id, m2.node_id)

            return Morphism(combined_id, m2.end_state)

        return OpenMorphism(
            composed_kleisli,
            name=f"({left.name} >> {right.name})"
        )

    def __or__(self, other: OpenMorphism) -> OpenMorphism:
        """并行组合

        语法: par = op1 | op2

        语义:
            op1(s0) -> Morphism(n1, s1)
            op2(s0) -> Morphism(n2, s2)  # 都从 s0 开始
            return Morphism(parallel(n1, n2), merge(s1, s2))

        注意: 对于单通道操作，这通常用于不同通道。
        """
        left = self
        right = other

        def parallel_kleisli(
            ctx: catseq_rs.CompilerContext,
            channel: Channel,
            s0: HardwareState,
        ) -> Morphism:
            # 两个分支都从相同状态开始
            m1 = left._kleisli(ctx, channel, s0)
            m2 = right._kleisli(ctx, channel, s0)

            # 状态合并：相同类型时使用右侧状态
            if type(m1.end_state) == type(m2.end_state):
                s_final = m2.end_state
            else:
                raise TypeError(
                    f"并行组合产生了不兼容的状态: "
                    f"{type(m1.end_state).__name__} vs {type(m2.end_state).__name__}"
                )

            # 在 Rust 中并行组合
            combined_id = ctx.parallel_compose(m1.node_id, m2.node_id)

            return Morphism(combined_id, s_final)

        return OpenMorphism(
            parallel_kleisli,
            name=f"({left.name} | {right.name})"
        )

    def __repr__(self) -> str:
        return f"<OpenMorphism: {self.name}>"


# =============================================================================
# Multi-Channel Parallel Composition
# =============================================================================

def parallel(ops: dict[Channel, OpenMorphism]) -> MultiChannelOpenMorphism:
    """多通道并行组合

    语法: combined = parallel({ch1: op1, ch2: op2})

    Args:
        ops: 通道到 OpenMorphism 的映射

    Returns:
        MultiChannelOpenMorphism
    """
    return MultiChannelOpenMorphism(ops)


# 多通道状态类型
MultiChannelState = dict[Channel, HardwareState]


class MultiChannelMorphism(NamedTuple):
    """多通道物化结果"""
    node_id: int
    end_states: MultiChannelState


class MultiChannelOpenMorphism:
    """多通道 OpenMorphism

    用于跨多个通道的并行操作。
    """

    __slots__ = ('_ops', 'name')

    def __init__(self, ops: dict[Channel, OpenMorphism], name: str = "multi"):
        self._ops = ops
        self.name = name

    def __call__(
        self,
        ctx: catseq_rs.CompilerContext,
        states: MultiChannelState,
    ) -> MultiChannelMorphism:
        """物化多通道 OpenMorphism

        Args:
            ctx: Rust CompilerContext
            states: 每个通道的起始状态

        Returns:
            MultiChannelMorphism(node_id, end_states)
        """
        results: list[Morphism] = []
        end_states: MultiChannelState = {}

        for channel, op in self._ops.items():
            start_state = states[channel]
            m = op(ctx, channel, start_state)
            results.append(m)
            end_states[channel] = m.end_state

        # 并行组合所有节点
        if len(results) == 0:
            raise ValueError("parallel() 需要至少一个操作")

        node_id = results[0].node_id
        for m in results[1:]:
            node_id = ctx.parallel_compose(node_id, m.node_id)

        return MultiChannelMorphism(node_id, end_states)

    def __rshift__(self, other: MultiChannelOpenMorphism) -> MultiChannelOpenMorphism:
        """多通道串行组合"""
        left = self
        right = other

        # 合并两个操作的通道集合
        all_channels = set(left._ops.keys()) | set(right._ops.keys())

        def combined_ops() -> dict[Channel, OpenMorphism]:
            result = {}
            for ch in all_channels:
                left_op = left._ops.get(ch)
                right_op = right._ops.get(ch)

                if left_op and right_op:
                    result[ch] = left_op >> right_op
                elif left_op:
                    result[ch] = left_op
                else:
                    result[ch] = right_op
            return result

        return MultiChannelOpenMorphism(
            combined_ops(),
            name=f"({left.name} >> {right.name})"
        )

    def __repr__(self) -> str:
        channels = ", ".join(str(ch) for ch in self._ops.keys())
        return f"<MultiChannelOpenMorphism: {self.name} [{channels}]>"
