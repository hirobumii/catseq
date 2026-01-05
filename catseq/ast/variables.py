"""
Variable system for CatSeq programs.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class CompileTimeParam:
    """编译时参数（Python 常量）

    例如：
        n = CompileTimeParam("iterations", 100)
        program = execute(pulse).replicate(n)
    """
    name: str
    value: int | float


@dataclass(frozen=True)
class RuntimeVar:
    """运行时变量（RTMQ TCS 寄存器）

    映射到 RTMQ 的 TCS 寄存器 ($xx)

    例如：
        adc_value = var("adc_value", "int32")
        threshold = var("threshold", "int32")
    """
    name: str
    register_id: int  # TCS 寄存器编号 (0x00-0xFF)
    var_type: str  # "int32", "bool"


class TCSAllocator:
    """TCS 寄存器分配器

    RTMQ TCS 地址空间:
    - $00-$01: 特殊寄存器 ($00=0, $01=-1)
    - $02-$1F: GPR（30个通用寄存器，总是可访问）
    - $20-$FF: 栈相对寄存器（需要 STK 管理）

    策略：从 $20 开始分配（保留 $02-$1F 用于临时变量）
    """

    def __init__(self):
        self.next_reg = 0x20  # 从 $20 开始分配
        self.var_map: Dict[str, int] = {}  # 变量名 -> 寄存器 ID

    def allocate(self, var_name: str) -> int:
        """为变量分配 TCS 寄存器"""
        if var_name in self.var_map:
            return self.var_map[var_name]

        if self.next_reg > 0xFF:
            raise RuntimeError(f"TCS register exhausted (max 256)")

        reg_id = self.next_reg
        self.var_map[var_name] = reg_id
        self.next_reg += 1
        return reg_id

    def get_register(self, var: RuntimeVar) -> str:
        """获取寄存器名称（OASM 格式）"""
        return f"${var.register_id:02X}"

    def reset(self):
        """重置分配器（用于测试或新程序）"""
        self.next_reg = 0x20
        self.var_map.clear()


# 全局分配器实例（单例模式）
_global_allocator = TCSAllocator()


def get_allocator() -> TCSAllocator:
    """获取全局分配器"""
    return _global_allocator


def reset_allocator():
    """重置全局分配器"""
    _global_allocator.reset()
