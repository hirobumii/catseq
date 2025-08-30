"""
OASM DSL function definitions.

This module contains the actual OASM DSL functions that will be called
when executing compiled sequences on the hardware.
"""
from oasm.rtmq2 import sfs, amk
from .mask_utils import binary_to_rtmq_mask

def ttl_config(mask, dir):
    """配置 TTL 通道状态
    
    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101)
        dir: TTL 状态值，指定选中通道的方向 (binary format, e.g., 0b0001)
    """
    # Convert binary mask to RTMQ "A.B" format if possible
    rtmq_mask = binary_to_rtmq_mask(mask)
    
    # TTL direction uses registers $00 or $01
    # Convert dir value to appropriate register address
    if dir == 0:
        dir_reg = '$00'  # Register $00 for direction 0
    elif dir == 1:
        dir_reg = '$01'  # Register $01 for direction 1
    else:
        # For complex patterns, convert to RTMQ format
        dir_reg = binary_to_rtmq_mask(dir)
    
    sfs('dio', 'dir')
    amk('dio', rtmq_mask, dir_reg)
    
    print(f"SFS - DIO DIR")
    print(f"AMK - DIO {rtmq_mask} {dir_reg}")
    print(f"  -> mask=0b{mask:08b}, dir=0b{dir:08b}")

def wait_us(duration):
    """等待指定微秒数
    
    Args:
        duration: 等待时长（微秒）
    """
    print(f"OASM: Wait {duration} μs")


def my_wait():
    """自定义等待操作"""
    print("OASM: My wait")


def trig_slave(param):
    """触发从设备
    
    Args:
        param: 触发参数
    """
    print(f"OASM: Trigger slave - param={param}")