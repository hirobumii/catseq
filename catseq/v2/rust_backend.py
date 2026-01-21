"""CatSeq Rust 后端包装层

提供与现有 Python API 兼容的接口，内部使用 Rust 加速编译器。

架构设计：
- Rust: 纯代数引擎（只关心 @ 和 | 的代数规则）
- Python: 语义层（理解操作的具体含义）

使用前提：
- 必须先编译安装 catseq-rust 包（cd catseq-rust && maturin develop）
- 如果未安装，导入时会报 ImportError
"""

from typing import Dict, List, Tuple, Optional
import pickle

from catseq_rs import CompilerContext as RustContext, Node as RustNode
from catseq.types.common import Channel, ChannelType, OperationType


def pack_channel_id(channel: Channel) -> int:
    """将 Channel 打包为 u32

    布局:
    - bits [31:16]: board_id
    - bits [15:8]: channel_type (TTL=0, RWG=1, DAC=2)
    - bits [7:0]: local_id
    """
    type_map = {ChannelType.TTL: 0, ChannelType.RWG: 1}

    board_id = int(channel.board.id.split("_")[-1])  # "RWG_0" -> 0
    channel_type = type_map[channel.channel_type]
    local_id = channel.local_id

    return (board_id << 16) | (channel_type << 8) | local_id


def unpack_channel_id(packed: int) -> Tuple[int, int, int]:
    """解包 u32 为 (board_id, channel_type, local_id)"""
    board_id = (packed >> 16) & 0xFFFF
    channel_type = (packed >> 8) & 0xFF
    local_id = packed & 0xFF
    return board_id, channel_type, local_id


class RustMorphism:
    """Rust-backed Morphism

    用户友好的包装层，兼容现有 Morphism API
    """

    def __init__(self, rust_node: RustNode):
        self._node = rust_node

    @staticmethod
    def create_context(capacity: int = 100_000) -> RustContext:
        """创建编译器上下文

        Args:
            capacity: Arena 预分配容量（节点数）

        Returns:
            RustContext: 上下文对象
        """
        return RustContext.with_capacity(capacity)

    @staticmethod
    def atomic(
        ctx: RustContext,
        channel: Channel,
        duration_cycles: int,
        op_type: OperationType,
        params: Optional[Dict] = None,
    ) -> "RustMorphism":
        """创建原子操作

        Args:
            ctx: 编译器上下文
            channel: 通道对象
            duration_cycles: 持续时间（时钟周期）
            op_type: 操作类型枚举（OperationType.TTL_ON 等）
            params: 可选参数字典（如 RWG 的频率、幅度）

        Returns:
            RustMorphism: 新创建的 Morphism
        """
        if not isinstance(op_type, OperationType):
            raise TypeError(f"op_type must be OperationType, got {type(op_type).__name__}")

        channel_id = pack_channel_id(channel)

        # 将操作语义编码为 payload
        payload_dict = {"op_type": op_type, "params": params or {}}
        payload = pickle.dumps(payload_dict)

        rust_node = ctx.atomic(channel_id, duration_cycles, payload)
        return RustMorphism(rust_node)

    def __matmul__(self, other: "RustMorphism") -> "RustMorphism":
        """串行组合 @"""
        result = self._node @ other._node
        return RustMorphism(result)

    def __or__(self, other: "RustMorphism") -> "RustMorphism":
        """并行组合 |"""
        result = self._node | other._node
        return RustMorphism(result)

    @property
    def total_duration_cycles(self) -> int:
        """获取总时长（时钟周期）"""
        return self._node.duration

    @property
    def channels(self) -> List[int]:
        """获取涉及的通道列表（packed channel_id）"""
        return self._node.channels

    def compile(self) -> List[Tuple[int, int, bytes]]:
        """编译为扁平事件列表

        Returns:
            List[Tuple[int, int, bytes]]: [(time, channel_id, payload), ...]
        """
        return self._node.compile()

    def compile_by_board(self) -> Dict[int, List[Tuple[int, int, bytes]]]:
        """编译并按板卡分组

        Returns:
            Dict[int, List[Tuple[int, int, bytes]]]:
                board_id -> [(time, channel_id, payload), ...]
        """
        return self._node.compile_by_board()

    def to_flat_events(self) -> List[Tuple[int, Channel, str, Dict]]:
        """编译并解析 payload

        Returns:
            List[Tuple[int, Channel, str, Dict]]:
                [(time_cycles, channel, op_type, params), ...]
        """
        from catseq.types.common import Board

        events = self.compile()
        result = []

        for time, channel_id, payload in events:
            # 解包 channel_id
            board_id, channel_type_int, local_id = unpack_channel_id(channel_id)

            # 重建 Channel 对象
            channel_type_map = {0: ChannelType.TTL, 1: ChannelType.RWG}
            channel = Channel(
                board=Board(f"RWG_{board_id}"),
                local_id=local_id,
                channel_type=channel_type_map[channel_type_int],
            )

            # 解析 payload（Rust 返回 list，需要转换为 bytes）
            payload_bytes = bytes(payload) if isinstance(payload, list) else payload
            payload_dict = pickle.loads(payload_bytes)
            op_type = payload_dict["op_type"]
            params = payload_dict["params"]

            result.append((time, channel, op_type, params))

        return result

    def __repr__(self) -> str:
        return f"<RustMorphism duration={self.total_duration_cycles}>"


# ===== 全局上下文（可选）=====

_GLOBAL_CONTEXT: Optional[RustContext] = None


def get_or_create_global_context() -> RustContext:
    """获取或创建全局上下文（用于快速原型）

    注意：生产环境建议显式管理上下文生命周期
    """
    global _GLOBAL_CONTEXT
    if _GLOBAL_CONTEXT is None:
        _GLOBAL_CONTEXT = RustMorphism.create_context()
    return _GLOBAL_CONTEXT
