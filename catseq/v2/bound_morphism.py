"""CatSeq V2 BoundMorphism - 通道已绑定的操作缓冲区

BoundMorphism 是 Phase 2 (Assembly) 的核心类型，实现严格的 Monoidal Category 语义：
- 通道已绑定，数据存储在 Rust Vec 中
- 组合操作自动执行矩形对齐（Rectangularization）
- 调用 (__call__) 时执行 Replay Pass，进行状态验证和节点构建

矩形化规则：
- 并行组合 (|): 短通道末尾补 Identity 对齐到最长时长
- 串行组合 (>>): 缺失通道补 Identity 填充时间空隙

使用示例：
    >>> from catseq.v2.bound_morphism import BoundMorphism
    >>> from catseq.types.common import Board, Channel, ChannelType
    >>>
    >>> ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    >>> ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)
    >>>
    >>> # 创建两个不同时长的操作
    >>> bm0 = BoundMorphism(ch0)
    >>> bm0.append(100, 0x0101, b"")  # 100 cycles
    >>>
    >>> bm1 = BoundMorphism(ch1)
    >>> bm1.append(200, 0x0101, b"")  # 200 cycles
    >>>
    >>> # 并行组合：自动对齐到 200 cycles
    >>> par = bm0 | bm1
    >>> assert par.duration == 200
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import catseq_rs

from catseq.types.common import Channel
from catseq.v2.context import get_context
from catseq.v2.opcodes import OpCode

if TYPE_CHECKING:
    from catseq.v2.open_morphism import HardwareState

# Identity/Wait 操作码
OP_IDENTITY = OpCode.IDENTITY  # 0x0000


def encode_channel_id(channel: Channel) -> int:
    """将 Channel 编码为 u32"""
    board_num = int(channel.board.id.split("_")[-1])
    return (board_num << 16) | channel.local_id


class ClosedMorphism:
    """Phase 3: 状态已验证，物理节点已构建

    Attributes:
        node_id: Arena 中的根节点 ID
        end_states: 各通道的结束状态
    """

    __slots__ = ("node_id", "end_states")

    def __init__(self, node_id: int, end_states: dict[Channel, HardwareState]):
        self.node_id = node_id
        self.end_states = end_states

    def compile(self, ctx: catseq_rs.CompilerContext | None = None):
        """编译为事件列表

        Returns:
            List[Tuple[int, int, int, bytes]]: [(time, channel_id, opcode, data), ...]
        """
        if ctx is None:
            ctx = get_context()
        return ctx.compile_graph(self.node_id)

    def __repr__(self) -> str:
        channels = ", ".join(str(ch) for ch in self.end_states.keys())
        return f"<ClosedMorphism node_id={self.node_id} channels=[{channels}]>"


class BoundMorphism:
    """Phase 2: 通道已绑定的操作缓冲区

    实现严格的 Monoidal Category 语义，所有组合操作保证矩形对齐。
    内部维护 Dict[Channel, MorphismPath]，组合操作在 Rust 内存中完成。
    """

    __slots__ = ("_paths",)

    def __init__(self, data: Channel | dict[Channel, catseq_rs.MorphismPath]):
        """创建 BoundMorphism

        Args:
            data: 单个 Channel（自动创建空 Path）或已有的 paths 字典
        """
        if isinstance(data, Channel):
            channel_id = encode_channel_id(data)
            self._paths: dict[Channel, catseq_rs.MorphismPath] = {
                data: catseq_rs.MorphismPath(channel_id)
            }
        else:
            self._paths = data

    def append(
        self,
        duration: int,
        opcode: int,
        payload: bytes,
        channel: Channel | None = None,
    ) -> None:
        """追加操作到指定通道

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
            if len(self._paths) == 1:
                target_ch = next(iter(self._paths))
            else:
                raise ValueError("多通道 BoundMorphism 必须指定 channel")

        if target_ch not in self._paths:
            channel_id = encode_channel_id(target_ch)
            self._paths[target_ch] = catseq_rs.MorphismPath(channel_id)

        self._paths[target_ch].append(duration, opcode, payload)

    @property
    def channels(self) -> set[Channel]:
        """获取涉及的通道集合"""
        return set(self._paths.keys())

    @property
    def duration(self) -> int:
        """获取矩形时长（最长通道的持续时间）"""
        if not self._paths:
            return 0
        return max(p.total_duration for p in self._paths.values())

    def __or__(self, other: BoundMorphism) -> BoundMorphism:
        """并行组合 (|): 矩形对齐

        通过在短通道末尾补 Identity 实现时间对齐。

        Returns:
            新的 BoundMorphism，所有通道时长相等

        Raises:
            ValueError: 如果通道有交集
        """
        overlap = set(self._paths.keys()) & set(other._paths.keys())
        if overlap:
            raise ValueError(f"并行组合通道冲突: {overlap}")

        # 计算目标对齐边界
        target_duration = max(self.duration, other.duration)
        new_paths: dict[Channel, catseq_rs.MorphismPath] = {}

        # 处理 Self 的通道：对齐边界
        for ch, path in self._paths.items():
            new_p = path.clone()
            new_p.align(target_duration, OP_IDENTITY)
            new_paths[ch] = new_p

        # 处理 Other 的通道：对齐边界
        for ch, path in other._paths.items():
            new_p = path.clone()
            new_p.align(target_duration, OP_IDENTITY)
            new_paths[ch] = new_p

        return BoundMorphism(new_paths)

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

        all_channels = set(self._paths.keys()) | set(other._paths.keys())
        new_paths: dict[Channel, catseq_rs.MorphismPath] = {}

        for ch in all_channels:
            path_a = self._paths.get(ch)
            path_b = other._paths.get(ch)

            if path_a and path_b:
                # Case 1: A >> B（都存在）
                new_p = path_a.clone()
                new_p.align(dur_a, OP_IDENTITY)  # 确保 A 内部对齐
                new_p.extend(path_b)
                new_paths[ch] = new_p

            elif path_a:
                # Case 2: A >> Id_B（A 存在，B 缺失）
                new_p = path_a.clone()
                new_p.align(dur_a + dur_b, OP_IDENTITY)  # 直接对齐到总时长
                new_paths[ch] = new_p

            else:
                # Case 3: Id_A >> B（A 缺失，B 存在）
                ch_id = other._paths[ch].channel_id
                new_p = catseq_rs.MorphismPath.identity(ch_id, dur_a, OP_IDENTITY)
                new_p.extend(path_b)
                new_paths[ch] = new_p

        return BoundMorphism(new_paths)

    def __call__(
        self,
        start_states: dict[Channel, HardwareState],
        ctx: catseq_rs.CompilerContext | None = None,
    ) -> ClosedMorphism:
        """Replay Pass: 延迟验证与物化

        遍历 Rust Path，运行状态检查，创建 Arena 节点。

        Args:
            start_states: 各通道的起始状态
            ctx: CompilerContext（可选，默认使用全局）

        Returns:
            ClosedMorphism: 包含根节点 ID 和结束状态

        Raises:
            ValueError: 如果缺少起始状态或状态转换非法
        """
        if ctx is None:
            ctx = get_context()

        final_nodes: list[int] = []
        final_end_states: dict[Channel, HardwareState] = {}

        # 对每个通道执行重放
        for ch, path in self._paths.items():
            state = start_states.get(ch)
            if state is None:
                raise ValueError(f"缺少通道 {ch} 的起始状态")

            # 单通道 Replay Loop
            channel_nodes: list[int] = []
            for duration, opcode, payload in path:
                # 1. Python 状态检查
                # TODO: 实现通用的状态转换检查
                # state = state.next_state(opcode, payload)

                # 2. Rust 节点创建（使用 atomic_id 直接获取 int）
                node_id = ctx.atomic_id(path.channel_id, duration, opcode, payload)
                channel_nodes.append(node_id)

            # 3. Rust 批量组合（构建平衡树）
            if channel_nodes:
                seq_id = ctx.compose_sequence(channel_nodes)
                if seq_id is not None:
                    final_nodes.append(seq_id)

            # 更新结束状态（简化：保持起始状态）
            # TODO: 实现完整的状态追踪
            final_end_states[ch] = state

        # 4. 并行组合所有通道的结果
        if len(final_nodes) == 0:
            raise ValueError("BoundMorphism 为空")
        elif len(final_nodes) == 1:
            root_id = final_nodes[0]
        else:
            root_id = ctx.parallel_compose_many(final_nodes)
            if root_id is None:
                raise ValueError("并行组合失败")

        return ClosedMorphism(root_id, final_end_states)

    def __len__(self) -> int:
        """获取总步骤数"""
        return sum(len(p) for p in self._paths.values())

    def __repr__(self) -> str:
        channels = ", ".join(
            f"{ch.global_id}:{len(p)}" for ch, p in self._paths.items()
        )
        return f"<BoundMorphism [{channels}] duration={self.duration}>"
