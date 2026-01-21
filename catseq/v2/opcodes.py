"""OpCode definitions for CatSeq V2.

OpCodes are u16 values that Python defines and Rust stores opaquely.
The semantic interpretation happens entirely in Python.

OpCode 编码约定:
    0x00xx - 时间/同步操作
    0x01xx - TTL 操作
    0x02xx - RWG 操作
    0x03xx - 保留
"""

from enum import IntEnum


class OpCode(IntEnum):
    """原子操作码 (u16)

    Rust 端只存储这个值，不解释其语义。
    语义解释完全在 Python 端进行。
    """
    # 时间/同步操作 (0x00xx)
    IDENTITY = 0x0000
    SYNC_MASTER = 0x0001
    SYNC_SLAVE = 0x0002

    # TTL 操作 (0x01xx)
    TTL_INIT = 0x0100
    TTL_ON = 0x0101
    TTL_OFF = 0x0102

    # RWG 操作 (0x02xx)
    RWG_INIT = 0x0200
    RWG_SET_CARRIER = 0x0201
    RWG_LOAD_COEFFS = 0x0202
    RWG_UPDATE_PARAMS = 0x0203
    RWG_RF_SWITCH = 0x0204

    # 黑盒操作 (0x03xx)
    OPAQUE_OASM_FUNC = 0x0300


# 便捷的分类检查函数
def is_ttl_op(opcode: OpCode) -> bool:
    """检查是否为 TTL 操作"""
    return 0x0100 <= opcode <= 0x01FF


def is_rwg_op(opcode: OpCode) -> bool:
    """检查是否为 RWG 操作"""
    return 0x0200 <= opcode <= 0x02FF


def is_timing_op(opcode: OpCode) -> bool:
    """检查是否为时间/同步操作"""
    return 0x0000 <= opcode <= 0x00FF
