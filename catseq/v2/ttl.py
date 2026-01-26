"""CatSeq V2 TTL Operations - Hybrid Architecture

实现了 API 重载策略：
1. 模版模式 (Template Mode): 不传 channel，返回 OpenMorphism (蓝图)。
2. 构建模式 (Build Mode): 传入 channel，返回 BoundMorphism (预制件)，直接操作 Rust 内存。

使用示例：
    >>> from catseq.v2.hardware.ttl import ttl_pulse, wait, TTLOff
    >>> from catseq.types.common import Channel
    >>>
    >>> # 用法 A: 快速构建 (Fast Path) - 推荐用于具体实验脚本
    >>> # 直接返回 BoundMorphism，无闭包开销
    >>> seq = ttl_pulse(ch, 10e-6)
    >>>
    >>> # 用法 B: 定义模版 (Template) - 推荐用于通用库函数
    >>> # 返回 OpenMorphism
    >>> template = ttl_pulse(10e-6)
    >>> bound = template(ch)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, overload, Union

import catseq_rs

from catseq.types.common import Channel
from catseq.time_utils import time_to_cycles
from catseq.v2.open_morphism import HardwareState, Morphism, OpenMorphism
from catseq.v2.bound_morphism import BoundMorphism
from catseq.v2.opcodes import OpCode

if TYPE_CHECKING:
    from catseq.v2.context import CompilerContext

# =============================================================================
# TTL Hardware States
# =============================================================================

@dataclass(frozen=True)
class TTLOff(HardwareState):
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))

@dataclass(frozen=True)
class TTLOn(HardwareState):
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))

# =============================================================================
# Data Generators (Pure Logic)
# =============================================================================
# 提取纯数据生成逻辑，供 OpenMorphism 和 BoundMorphism 复用
# Yields: (duration_cycles, opcode, payload_bytes)

def _gen_ttl_on():
    yield (0, OpCode.TTL_ON, b"")

def _gen_ttl_off():
    yield (0, OpCode.TTL_OFF, b"")

def _gen_wait(duration: float):
    cycles = time_to_cycles(duration)
    if cycles > 0:
        yield (cycles, OpCode.IDENTITY, b"")

def _gen_ttl_init():
    yield (0, OpCode.TTL_INIT, b"")

def _gen_ttl_pulse(duration: float):
    yield from _gen_ttl_on()
    yield from _gen_wait(duration)
    yield from _gen_ttl_off()

# =============================================================================
# Helper: Channel Encoding
# =============================================================================

def encode_channel_id(channel: Channel) -> int:
    # 临时处理，未来应移至 Channel 类本身
    board_num = int(channel.board.id.split("_")[-1])
    return (board_num << 16) | channel.local_id

# =============================================================================
# Hybrid API Implementation
# =============================================================================

# --- 1. TTL ON ---

@overload
def ttl_on() -> OpenMorphism: ...
@overload
def ttl_on(channel: Channel) -> BoundMorphism: ...

def ttl_on(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL ON 操作 (Hybrid)"""
    
    # Fast Path: BoundMorphism
    if channel is not None:
        bm = BoundMorphism(channel)
        for d, o, p in _gen_ttl_on():
            bm.append(d, o, p, channel)
        return bm

    # Template Path: OpenMorphism
    def _kleisli(ctx: CompilerContext, ch: Channel, state: HardwareState) -> Morphism:
        if not isinstance(state, TTLOff):
            raise TypeError(f"ttl_on 需要 TTLOff，得到 {type(state).__name__}")
        
        # OpenMorphism 这里只产生一个节点，通常不需要循环生成器
        # 但为了逻辑统一，我们手动展开
        # 注意：OpenMorphism 必须返回 (NodeId, EndState)，所以这里简化处理
        node = ctx.atomic_id(encode_channel_id(ch), 0, OpCode.TTL_ON, b"")
        return Morphism(node, TTLOn())

    return OpenMorphism(_kleisli, name="ttl_on")


# --- 2. TTL OFF ---

@overload
def ttl_off() -> OpenMorphism: ...
@overload
def ttl_off(channel: Channel) -> BoundMorphism: ...

def ttl_off(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL OFF 操作 (Hybrid)"""
    
    if channel is not None:
        bm = BoundMorphism(channel)
        for d, o, p in _gen_ttl_off():
            bm.append(d, o, p, channel)
        return bm

    def _kleisli(ctx: CompilerContext, ch: Channel, state: HardwareState) -> Morphism:
        if not isinstance(state, TTLOn):
            raise TypeError(f"ttl_off 需要 TTLOn，得到 {type(state).__name__}")
        node = ctx.atomic_id(encode_channel_id(ch), 0, OpCode.TTL_OFF, b"")
        return Morphism(node, TTLOff())

    return OpenMorphism(_kleisli, name="ttl_off")


# --- 3. WAIT ---

@overload
def wait(duration: float) -> OpenMorphism: ...
@overload
def wait(channel: Channel, duration: float) -> BoundMorphism: ...

def wait(arg1: Union[Channel, float], arg2: float | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建等待操作 (Hybrid)"""
    
    # 识别参数模式
    if isinstance(arg1, Channel):
        # wait(channel, duration) -> BoundMorphism
        channel = arg1
        duration = arg2 if arg2 is not None else 0.0
        
        bm = BoundMorphism(channel)
        # 直接使用 Rust 后端的 align/identity 优化可能更好，
        # 但为了通用性，这里复用生成器
        for d, o, p in _gen_wait(duration):
            bm.append(d, o, p, channel)
        return bm
    else:
        # wait(duration) -> OpenMorphism
        duration = float(arg1)
        
        def _kleisli(ctx: CompilerContext, ch: Channel, state: HardwareState) -> Morphism:
            cycles = time_to_cycles(duration)
            node = ctx.atomic_id(encode_channel_id(ch), cycles, OpCode.IDENTITY, b"")
            return Morphism(node, state)

        return OpenMorphism(_kleisli, name=f"wait({duration*1e6:.1f}us)")


# --- 4. TTL PULSE (Composite) ---

@overload
def ttl_pulse(duration: float) -> OpenMorphism: ...
@overload
def ttl_pulse(channel: Channel, duration: float) -> BoundMorphism: ...

def ttl_pulse(arg1: Union[Channel, float], arg2: float | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL 脉冲 (Hybrid Composite)"""
    
    # Fast Path
    if isinstance(arg1, Channel):
        channel = arg1
        duration = arg2 if arg2 is not None else 0.0
        
        bm = BoundMorphism(channel)
        # 直接在 Rust 内存中追加三个操作，极快
        for d, o, p in _gen_ttl_pulse(duration):
            bm.append(d, o, p, channel)
        return bm
        
    # Template Path
    else:
        duration = float(arg1)
        # 复用已有的 OpenMorphism 组合逻辑
        return ttl_on() >> wait(duration) >> ttl_off()
    
# --- TTL INIT ---

@overload
def ttl_init() -> OpenMorphism: ...
@overload
def ttl_init(channel: Channel) -> BoundMorphism: ...

def ttl_init(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL 初始化操作 (Hybrid)
    
    通常用于序列开头，强制将状态置为 TTLOff。
    状态转换: Any -> TTLOff
    """
    
    # Fast Path: BoundMorphism
    if channel is not None:
        bm = BoundMorphism(channel)
        for d, o, p in _gen_ttl_init():
            bm.append(d, o, p, channel)
        return bm

    # Template Path: OpenMorphism
    def _kleisli(ctx: CompilerContext, ch: Channel, state: HardwareState) -> Morphism:
        # Init 操作通常不需要检查前置状态 (state)，因为它就是用来重置状态的
        node = ctx.atomic_id(encode_channel_id(ch), 0, OpCode.TTL_INIT, b"")
        return Morphism(node, TTLOff())

    return OpenMorphism(_kleisli, name="ttl_init")