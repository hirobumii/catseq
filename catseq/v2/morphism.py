"""CatSeq V2 Morphism - Three-Phase Architecture with Eager State Inference

类型转换链：
    OpenMorphism ──(绑定通道)──> BoundMorphism ──(绑定初始状态)──> Morphism
      (模版)                      (通道已绑定)                   (完全物化)

State Inference:
    - 类型级：OpenMorphism.transitions 在 >> 时检查 domain/codomain 兼容性
    - 值级：OpenMorphism.infer_state 提供状态推导函数，BoundMorphism 在 >> 时即时求值
    - Backpatching：动态 payload（callable）在 >> 组合时通过 PendingPatch 解析
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Iterator, TypeAlias, TYPE_CHECKING

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
    状态是纯数据容器，不包含任何状态转换逻辑（SRP）。
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

# State transition table: domain state type -> codomain state type
# None means passthrough (identity/wait): preserves any state
StateTransitions: TypeAlias = dict[type[HardwareState], type[HardwareState]] | None

# State inference function: computes output state from input state
# None means passthrough (identity/wait)
InferState: TypeAlias = Callable[[HardwareState], HardwareState] | None

# Backpatch generator: computes payload from resolved state
PatchGenerator: TypeAlias = Callable[[HardwareState], bytes]


@dataclass
class PendingPatch:
    """Deferred payload computation, resolved at composition time (>>) or materialization.

    Attributes:
        node_id: Rust Arena 中的原子节点 ID（持有占位 payload）
        channel: 目标通道
        opcode: 操作码
        generator: 接收前序状态，返回真实 payload
        pre_infer: 从 start_state 推导到 patch 点的状态函数（用于 __call__ 解析）
    """
    node_id: int
    channel: Channel
    opcode: int
    generator: PatchGenerator
    pre_infer: InferState = None


def _compose_transitions(
    left: StateTransitions,
    right: StateTransitions,
) -> StateTransitions:
    """Compose two transition tables (functional composition)."""
    if left is None:
        return right
    if right is None:
        return left
    composed: dict[type[HardwareState], type[HardwareState]] = {}
    for d_left, c_left in left.items():
        if c_left in right:
            composed[d_left] = right[c_left]
    if not composed:
        left_cod = set(left.values())
        right_dom = set(right.keys())
        raise ValueError(
            f"State transition mismatch: codomain {left_cod} "
            f"has no overlap with domain {right_dom}"
        )
    return composed


def _domains_of(t: StateTransitions) -> set[type[HardwareState]] | None:
    """Extract domain set from transitions. None means any."""
    return set(t.keys()) if t is not None else None


def _codomains_of(t: StateTransitions) -> set[type[HardwareState]] | None:
    """Extract codomain set from transitions. None means passthrough."""
    return set(t.values()) if t is not None else None


def _compose_infer_state(left: InferState, right: InferState) -> InferState:
    """Compose two infer_state functions (functional composition)."""
    if left is None:
        return right
    if right is None:
        return left
    return lambda s: right(left(s))


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
        new_id = ctx.compose(self.node_id, other.node_id)
        new_states = {**self.end_states, **other.end_states}
        return Morphism(new_id, new_states)

    def __or__(self, other: Morphism) -> Morphism:
        """Parallel Composition (|)"""
        if not isinstance(other, Morphism):
            return NotImplemented

        ctx = get_context()
        new_id = ctx.parallel(self.node_id, other.node_id)
        new_states = {**self.end_states, **other.end_states}
        return Morphism(new_id, new_states)

    @staticmethod
    def sequential_all(morphisms: list[Morphism]) -> Morphism:
        """批量串行组合，生成平衡树而非偏斜树"""
        if not morphisms:
            raise ValueError("Empty list")

        ctx = get_context()
        ids = [m.node_id for m in morphisms]
        root_id = ctx.compose_sequence(ids)

        final_states: dict[Channel, HardwareState] = {}
        for m in morphisms:
            final_states.update(m.end_states)

        return Morphism(root_id, final_states)

    def compile(self, ctx: catseq_rs.CompilerContext | None = None) -> list:
        if ctx is None:
            ctx = get_context()
        return ctx.compile_graph(self.node_id)


# =============================================================================
# BoundMorphism (Phase 2: 通道已绑定)
# =============================================================================

class BoundMorphism:
    """Phase 2: 通道已绑定，直接持有 Rust Arena 节点 ID

    Eager State Inference:
        _entry_req: 每通道入口状态要求（domain 类型集合，None = any）
        _exit_state: 每通道出口状态实例（concrete HardwareState，None = unknown/passthrough）
        _patches: 待 backpatch 的节点（payload 依赖前序状态值）

    所有状态演化在 append/append_dynamic 时即时完成。
    __call__ 仅做最终的入口检查和并行组合。
    """

    __slots__ = (
        "_nodes", "_durations",
        "_entry_req", "_exit_state",
        "_infer_fn", "_patches",
    )

    def __init__(
        self,
        data: Channel | dict[Channel, int],
        durations: dict[Channel, int] | None = None,
        entry_req: dict[Channel, set[type[HardwareState]] | None] | None = None,
        exit_state: dict[Channel, HardwareState | None] | None = None,
        infer_fn: dict[Channel, InferState] | None = None,
        patches: list[PendingPatch] | None = None,
    ):
        if isinstance(data, Channel):
            ctx = get_context()
            channel_id = encode_channel_id(data)
            node_id = ctx.atomic_id(channel_id, 0, OP_IDENTITY, b"")
            self._nodes: dict[Channel, int] = {data: node_id}
            self._durations: dict[Channel, int] = {data: 0}
            self._entry_req: dict[Channel, set[type[HardwareState]] | None] = {data: None}
            self._exit_state: dict[Channel, HardwareState | None] = {data: None}
            self._infer_fn: dict[Channel, InferState] = {data: None}
            self._patches: list[PendingPatch] = []
        else:
            self._nodes = data
            self._durations = durations or {}
            self._entry_req = entry_req or {}
            self._exit_state = exit_state or {}
            self._infer_fn = infer_fn or {}
            self._patches = patches or []

    def append(
        self,
        duration: int,
        opcode: int,
        payload: bytes,
        channel: Channel | None = None,
    ) -> None:
        """追加操作到指定通道（即时构建 Rust 图节点 + 即时状态演化）"""
        target_ch = channel

        if target_ch is None:
            if len(self._nodes) == 1:
                target_ch = next(iter(self._nodes))
            else:
                raise ValueError("多通道 BoundMorphism 必须指定 channel")

        ctx = get_context()
        ch_id = encode_channel_id(target_ch)

        if target_ch not in self._nodes:
            self._nodes[target_ch] = ctx.atomic_id(ch_id, 0, OP_IDENTITY, b"")
            self._durations[target_ch] = 0
            self._entry_req[target_ch] = None
            self._exit_state[target_ch] = None

        # Rust 图节点构建
        atom_id = ctx.atomic_id(ch_id, duration, opcode, payload)
        self._nodes[target_ch] = ctx.compose(self._nodes[target_ch], atom_id)
        self._durations[target_ch] += duration

    def append_dynamic(
        self,
        duration: int,
        opcode: int,
        generator: PatchGenerator,
        channel: Channel | None = None,
        placeholder_size: int = 64,
        output_state: HardwareState | None = None,
        pre_infer: InferState = None,
    ) -> None:
        """追加动态操作（payload 在 >> 组合时或 __call__ 时通过 backpatching 解析）

        Args:
            duration: 持续时间（时钟周期）
            opcode: 操作码
            generator: 接收前序 HardwareState 返回 bytes 的回调
            channel: 目标通道
            placeholder_size: 占位 payload 大小
            output_state: patch 解析后的符号输出状态（用于后续推导）
            pre_infer: 从 start_state 到 patch 点的状态推导函数
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
            self._nodes[target_ch] = ctx.atomic_id(ch_id, 0, OP_IDENTITY, b"")
            self._durations[target_ch] = 0
            self._entry_req[target_ch] = None
            self._exit_state[target_ch] = None

        # Path A: 前序状态已知 → 立即计算 payload
        current = self._exit_state.get(target_ch)
        if current is not None:
            payload = generator(current)
            atom_id = ctx.atomic_id(ch_id, duration, opcode, payload)
            self._nodes[target_ch] = ctx.compose(self._nodes[target_ch], atom_id)
            self._durations[target_ch] += duration
            if output_state is not None:
                self._exit_state[target_ch] = output_state
            return

        # Path B: 前序状态未知 → 占位 + 注册 patch
        placeholder = b"\x00" * placeholder_size
        atom_id = ctx.atomic_id(ch_id, duration, opcode, placeholder)
        self._nodes[target_ch] = ctx.compose(self._nodes[target_ch], atom_id)
        self._durations[target_ch] += duration

        self._patches.append(PendingPatch(
            node_id=atom_id,
            channel=target_ch,
            opcode=opcode,
            generator=generator,
            pre_infer=pre_infer,
        ))

    @property
    def channels(self) -> set[Channel]:
        return set(self._nodes.keys())

    @property
    def duration(self) -> int:
        if not self._durations:
            return 0
        return max(self._durations.values())

    def __or__(self, other: BoundMorphism) -> BoundMorphism:
        """并行组合 (|): 矩形对齐"""
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

        return BoundMorphism(
            new_nodes, new_durations,
            entry_req={**self._entry_req, **other._entry_req},
            exit_state={**self._exit_state, **other._exit_state},
            infer_fn={**self._infer_fn, **other._infer_fn},
            patches=self._patches + other._patches,
        )

    def __rshift__(self, other: BoundMorphism) -> BoundMorphism:
        """串行组合 (>>): 填充与拼接 + 状态检查 + patch 解析

        1. 类型级兼容性检查
        2. Resolve right 的 pending patches（使用 left 的 exit_state）
        3. 图节点组合
        """
        # 1. 类型级状态兼容性检查
        shared_channels = set(self._nodes.keys()) & set(other._nodes.keys())
        for ch in shared_channels:
            left_exit_state = self._exit_state.get(ch)
            right_entry = other._entry_req.get(ch)
            if left_exit_state is not None and right_entry is not None:
                if type(left_exit_state) not in right_entry:
                    raise ValueError(
                        f"通道 {ch.global_id} 状态不兼容: "
                        f"exit {type(left_exit_state).__name__} "
                        f"不在 entry {right_entry} 中"
                    )

        # 2. Resolve right's patches using left's exit_state
        ctx = get_context()
        resolved_patches: set[int] = set()  # indices of resolved patches
        for i, patch in enumerate(other._patches):
            left_state = self._exit_state.get(patch.channel)
            if left_state is not None:
                payload = patch.generator(left_state)
                ctx.update_payload(patch.node_id, patch.opcode, payload)
                resolved_patches.add(i)

        # 未解析的 patches 继续传递
        remaining_patches = self._patches + [
            p for i, p in enumerate(other._patches) if i not in resolved_patches
        ]

        # 3. Eagerly compute exit_state for right side using left's concrete exit
        for ch in shared_channels:
            left_exit = self._exit_state.get(ch)
            right_exit = other._exit_state.get(ch)
            if left_exit is not None and right_exit is None:
                right_fn = other._infer_fn.get(ch)
                if right_fn is not None:
                    other._exit_state[ch] = right_fn(left_exit)

        # 4. 图节点组合
        dur_a = self.duration
        dur_b = other.duration

        all_channels = set(self._nodes.keys()) | set(other._nodes.keys())
        new_nodes: dict[Channel, int] = {}
        new_durations: dict[Channel, int] = {}
        new_entry: dict[Channel, set[type[HardwareState]] | None] = {}
        new_exit: dict[Channel, HardwareState | None] = {}
        new_infer: dict[Channel, InferState] = {}

        for ch in all_channels:
            node_a = self._nodes.get(ch)
            node_b = other._nodes.get(ch)

            if node_a is not None and node_b is not None:
                gap_a = dur_a - self._durations[ch]
                padded_a = ctx.pad_end(node_a, gap_a, OP_IDENTITY)
                new_nodes[ch] = ctx.compose(padded_a, node_b)
                new_durations[ch] = dur_a + other._durations[ch]
                new_entry[ch] = self._entry_req.get(ch)
                new_exit[ch] = other._exit_state.get(ch) or self._exit_state.get(ch)
                new_infer[ch] = _compose_infer_state(
                    self._infer_fn.get(ch), other._infer_fn.get(ch)
                )

            elif node_a is not None:
                gap = (dur_a - self._durations[ch]) + dur_b
                new_nodes[ch] = ctx.pad_end(node_a, gap, OP_IDENTITY)
                new_durations[ch] = dur_a + dur_b
                new_entry[ch] = self._entry_req.get(ch)
                new_exit[ch] = self._exit_state.get(ch)
                new_infer[ch] = self._infer_fn.get(ch)

            else:
                ch_id = encode_channel_id(ch)
                id_node = ctx.atomic_id(ch_id, dur_a, OP_IDENTITY, b"")
                new_nodes[ch] = ctx.compose(id_node, node_b)
                new_durations[ch] = dur_a + other._durations[ch]
                new_entry[ch] = other._entry_req.get(ch)
                new_exit[ch] = other._exit_state.get(ch)
                new_infer[ch] = other._infer_fn.get(ch)

        return BoundMorphism(
            new_nodes, new_durations,
            entry_req=new_entry, exit_state=new_exit,
            infer_fn=new_infer, patches=remaining_patches,
        )

    def __call__(
        self,
        start_states: dict[Channel, HardwareState],
        ctx: catseq_rs.CompilerContext | None = None,
    ) -> Morphism:
        """Finalize: 静态入口检查 + 并行组合

        所有状态演化和 payload 计算已在 Phase 2 完成。
        此方法仅验证 start_states 并创建最终的 Morphism。

        Raises:
            ValueError: 如果 start_states 不满足 entry_req 或存在未解析的 patches
        """
        if ctx is None:
            ctx = get_context()

        # Resolve remaining patches using start_states + pre_infer
        if self._patches:
            still_unresolved = []
            for patch in self._patches:
                start = start_states.get(patch.channel)
                if start is not None:
                    pre_state = patch.pre_infer(start) if patch.pre_infer else start
                    payload = patch.generator(pre_state)
                    ctx.update_payload(patch.node_id, patch.opcode, payload)
                else:
                    still_unresolved.append(patch)
            if still_unresolved:
                names = [f"{p.channel.global_id}(node={p.node_id})" for p in still_unresolved]
                raise ValueError(f"存在未解析的 patches: {names}")

        final_nodes: list[int] = []
        final_end_states: dict[Channel, HardwareState] = {}

        for ch, node_id in self._nodes.items():
            state = start_states.get(ch)
            if state is None:
                raise ValueError(f"缺少通道 {ch} 的起始状态")

            # 类型级入口检查
            entry = self._entry_req.get(ch)
            if entry is not None and type(state) not in entry:
                raise ValueError(
                    f"通道 {ch.global_id} 起始状态 {type(state).__name__} "
                    f"不在 entry_req {entry} 中"
                )

            final_nodes.append(node_id)
            # end_state: 使用已推导的 exit_state；否则通过 infer_fn 计算
            exit = self._exit_state.get(ch)
            if exit is None:
                fn = self._infer_fn.get(ch)
                exit = fn(state) if fn is not None else state
            final_end_states[ch] = exit

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
        patches = f" patches={len(self._patches)}" if self._patches else ""
        return f"<BoundMorphism [{channels}] duration={self.duration}{patches}>"


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
        >> : 串行组合（生成器拼接 + 类型级转换表组合）
    """

    __slots__ = ('_gen', 'name', '_transitions', '_infer_state', '_chain')

    def __init__(
        self,
        gen: DataGenerator,
        name: str = "anon",
        transitions: StateTransitions = None,
        infer_state: InferState = None,
    ):
        """创建 OpenMorphism

        Args:
            gen: 数据生成器函数，调用时 yields (duration, opcode, payload_or_callable)
                 payload 为 bytes 时直接使用；为 callable 时表示动态 payload（需 backpatching）
            name: 调试用名称
            transitions: 状态转换表 {domain_type: codomain_type}，None 表示 passthrough
            infer_state: 值级状态推导函数，接收输入状态返回输出状态，None 表示 passthrough
        """
        self._gen = gen
        self.name = name
        self._transitions = transitions
        self._infer_state = infer_state
        self._chain: list[OpenMorphism] | None = None  # for per-op infer tracking

    def __call__(self, channel: Channel) -> BoundMorphism:
        """绑定通道，即时生成操作到 BoundMorphism"""
        bm = BoundMorphism(channel)
        chain = self._chain or [self]

        # Track cumulative infer_state for patch pre_infer
        cumulative_infer: InferState = None

        for om in chain:
            for duration, opcode, payload in om._gen():
                if callable(payload):
                    bm.append_dynamic(
                        duration, opcode, payload, channel,
                        pre_infer=cumulative_infer,
                    )
                else:
                    bm.append(duration, opcode, payload, channel)
            cumulative_infer = _compose_infer_state(cumulative_infer, om._infer_state)

        bm._entry_req = {channel: _domains_of(self._transitions)}
        bm._infer_fn = {channel: self._infer_state}
        return bm

    def __rshift__(self, other: OpenMorphism) -> OpenMorphism:
        """串行组合 (>>): 生成器级别的拼接 + 类型级转换表组合"""
        left_gen = self._gen
        right_gen = other._gen

        def composed_gen() -> Iterator[tuple[int, int, bytes]]:
            yield from left_gen()
            yield from right_gen()

        transitions = _compose_transitions(self._transitions, other._transitions)
        infer = _compose_infer_state(self._infer_state, other._infer_state)

        result = OpenMorphism(
            composed_gen,
            name=f"({self.name} >> {other.name})",
            transitions=transitions,
            infer_state=infer,
        )
        # Build chain for per-op infer tracking in __call__
        left_chain = self._chain or [self]
        right_chain = other._chain or [other]
        result._chain = left_chain + right_chain
        return result

    def __repr__(self) -> str:
        return f"<OpenMorphism: {self.name}>"


# =============================================================================
# parallel() 函数
# =============================================================================

def parallel(ops: dict[Channel, OpenMorphism]) -> BoundMorphism:
    """将多通道 OpenMorphism 并行组合为 BoundMorphism"""
    if not ops:
        raise ValueError("parallel() 需要至少一个操作")

    result: BoundMorphism | None = None
    for ch, op in ops.items():
        bm = op(ch)
        result = bm if result is None else result | bm

    assert result is not None
    return result
