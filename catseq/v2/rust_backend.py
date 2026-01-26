"""CatSeq Rust 后端包装层 (V2 Hybrid Architecture)

提供与 Rust 底层库 (catseq_rs) 的 Python 绑定。

V2 架构变更：
1. 移除 OperationType 枚举检查，全面支持 u16 OpCode。
2. 移除自动 Pickle 序列化，直接传递 bytes payload。
3. 移除全局上下文管理（由 catseq.v2.context 接管）。
"""

from typing import Dict, List, Tuple, Optional, Union
import catseq_rs
from catseq_rs import CompilerContext as RustContext, Node as RustNode
from catseq.types.common import Channel, ChannelType
from catseq.v2.opcodes import OpCode


def pack_channel_id(channel: Channel) -> int:
    """将 Channel 打包为 u32

    布局:
    - bits [31:16]: board_id
    - bits [15:14]: channel_type (TTL=0, RWG=1)
    - bits [13:0]:  local_id
    """
    type_map = {ChannelType.TTL: 0, ChannelType.RWG: 1}
    
    try:
        # 解析 "RWG_0" -> 0
        board_id = int(channel.board.id.split("_")[-1])
    except (ValueError, IndexError):
        board_id = 0

    # === 修正点：使用 channel.channel_type 而非 channel.type ===
    c_type = getattr(channel, "channel_type", ChannelType.TTL)
    channel_type = type_map.get(c_type, 0)
    
    local_id = channel.local_id

    return (board_id << 16) | (channel_type << 14) | local_id


def unpack_channel_id(packed: int) -> Tuple[int, int, int]:
    """解包 u32 为 (board_id, channel_type, local_id)"""
    board_id = (packed >> 16) & 0xFFFF
    channel_type = (packed >> 14) & 0x3
    local_id = packed & 0x3FFF
    return board_id, channel_type, local_id


class RustMorphism:
    """Rust-backed Morphism Wrapper

    轻量级包装器，不再包含旧的业务逻辑检查。
    """

    def __init__(self, rust_node: RustNode):
        self._node = rust_node

    @staticmethod
    def create_context(capacity: int = 100_000) -> RustContext:
        """创建一个新的编译器上下文"""
        return RustContext.with_capacity(capacity)

    @staticmethod
    def atomic(
        ctx: RustContext,
        channel: Channel,
        duration_cycles: int,
        opcode: Union[int, OpCode],
        payload: bytes,
    ) -> "RustMorphism":
        """创建原子操作

        Args:
            ctx: 编译器上下文
            channel: 通道对象
            duration_cycles: 持续时间
            opcode: 操作码 (u16)
            payload: 数据载荷 (bytes)

        Returns:
            RustMorphism: 包装后的节点
        """
        channel_id = pack_channel_id(channel)
        
        # 确保 opcode 是 int 类型
        opcode_int = int(opcode)

        # 调用 Rust 接口
        rust_node = ctx.atomic(channel_id, duration_cycles, opcode_int, payload)
        
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

    def compile(self) -> List[Tuple[int, int, int, bytes]]:
        """编译为扁平事件列表

        Returns:
            List[Tuple[int, int, int, bytes]]: 
            [(time, channel_id, opcode, payload), ...]
        """
        return self._node.compile()

    def compile_by_board(self) -> Dict[int, List[Tuple[int, int, int, bytes]]]:
        """编译并按板卡分组

        Returns:
            Dict[int, List[Tuple[int, int, int, bytes]]]:
                board_id -> [(time, channel_id, opcode, payload), ...]
        """
        return self._node.compile_by_board()

    def __repr__(self) -> str:
        return f"<RustMorphism duration={self.total_duration_cycles}>"