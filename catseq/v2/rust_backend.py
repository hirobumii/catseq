"""CatSeq Rust 后端包装层 (V2 Hybrid Architecture)

提供与 Rust 底层库 (catseq_rs) 的 Python 绑定。

V2 架构变更：
1. 移除 OperationType 枚举检查，全面支持 u16 OpCode。
2. 移除自动 Pickle 序列化，直接传递 bytes payload。
3. 移除全局上下文管理（由 catseq.v2.context 接管）。
"""

from typing import Dict, List, Tuple, Optional, Union
import catseq_rs
from catseq_rs import CompilerContext as RustContext, Node as RustNode, ProgramArena
from catseq.types.common import Channel, ChannelType
from catseq.v2.opcodes import OpCode

# 类型别名，增强代码可读性
NodeId = int
ValueId = int

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


class RustProgram:
    """Rust-backed Program Arena Wrapper

    Provides Pythonic access to the ProgramArena (Control Flow Layer).
    """

    def __init__(self, capacity_nodes: int = 1024, capacity_values: int = 1024):
        self._arena = ProgramArena.with_capacity(capacity_nodes, capacity_values)

    @property
    def node_count(self) -> int:
        return self._arena.node_count()

    @property
    def value_count(self) -> int:
        return self._arena.value_count()

    @property
    def var_count(self) -> int:
        return self._arena.var_count()

    def clear(self) -> None:
        self._arena.clear()

    # --- Value Creation ---

    def literal(self, value: int) -> ValueId:
        """创建整数字面量"""
        return self._arena.literal(value)

    def literal_float(self, value: float) -> ValueId:
        """创建浮点数字面量"""
        return self._arena.literal_float(value)

    def variable(self, name: str, type_hint: str = "int32") -> ValueId:
        """创建或获取变量"""
        return self._arena.variable(name, type_hint)

    def binary_expr(self, lhs: ValueId, op: str, rhs: ValueId) -> ValueId:
        """创建二元表达式 (lhs op rhs)"""
        return self._arena.binary_expr(lhs, op, rhs)

    def unary_expr(self, op: str, operand: ValueId) -> ValueId:
        """创建一元表达式 (op operand)"""
        return self._arena.unary_expr(op, operand)

    def condition(self, lhs: ValueId, op: str, rhs: ValueId) -> ValueId:
        """创建条件表达式 (lhs op rhs)"""
        return self._arena.condition(lhs, op, rhs)

    def logical_expr(self, lhs: ValueId, op: str, rhs: Optional[ValueId] = None) -> ValueId:
        """创建逻辑表达式 (lhs op rhs)"""
        return self._arena.logical_expr(lhs, op, rhs)

    # --- Node Creation ---

    def lift(self, morphism_ref: int, params: Dict[str, ValueId]) -> NodeId:
        """将 Morphism 提升到 Program 层"""
        return self._arena.lift(morphism_ref, params)

    def delay(self, duration: ValueId, max_hint: Optional[int] = None) -> NodeId:
        """创建延时节点"""
        return self._arena.delay(duration, max_hint)

    def set_var(self, target: ValueId, value: ValueId) -> NodeId:
        """创建变量赋值节点"""
        return self._arena.set_var(target, value)

    def chain(self, left: NodeId, right: NodeId) -> NodeId:
        """创建顺序组合节点"""
        return self._arena.chain(left, right)

    def loop_node(self, count: ValueId, body: NodeId) -> NodeId:
        """创建循环节点"""
        return self._arena.loop_(count, body)

    def match_node(self, subject: ValueId, cases: Dict[int, NodeId], default: Optional[NodeId] = None) -> NodeId:
        """创建模式匹配 (Switch) 节点"""
        return self._arena.match_(subject, cases, default)

    def apply(self, func: NodeId, args: List[ValueId]) -> NodeId:
        """创建函数调用节点"""
        return self._arena.apply(func, args)

    def func_def(self, name: str, params: List[ValueId], body: NodeId) -> NodeId:
        """创建函数定义节点"""
        return self._arena.func_def(name, params, body)

    def measure(self, target: ValueId, source: int) -> NodeId:
        """创建测量节点"""
        return self._arena.measure(target, source)

    def identity(self) -> NodeId:
        """创建 Identity 节点"""
        return self._arena.identity()

    def chain_sequence(self, nodes: List[NodeId]) -> Optional[NodeId]:
        """批量顺序组合（自动构建平衡树）"""
        return self._arena.chain_sequence(nodes)

    # --- Queries ---

    def is_literal(self, value_id: ValueId) -> bool:
        return self._arena.is_literal(value_id)

    def is_variable(self, value_id: ValueId) -> bool:
        return self._arena.is_variable(value_id)

    def get_literal_int(self, value_id: ValueId) -> Optional[int]:
        return self._arena.get_literal_int(value_id)

    def get_literal_float(self, value_id: ValueId) -> Optional[float]:
        return self._arena.get_literal_float(value_id)

    def get_variable_name(self, value_id: ValueId) -> Optional[str]:
        return self._arena.get_variable_name(value_id)

    def __repr__(self) -> str:
        return f"<RustProgram nodes={self.node_count} values={self.value_count}>"
