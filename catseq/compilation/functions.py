"""
OASM DSL function definitions.

This module contains the actual OASM DSL functions that will be called
when executing compiled sequences on the hardware.
"""
from oasm.rtmq2 import sfs, amk, wait
from .mask_utils import binary_to_rtmq_mask
from ..time_utils import us

def ttl_config(mask, dir):
    """配置 TTL 通道方向/初始化
    
    用于 TTL_INIT 操作，设置TTL通道的方向配置
    
    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101)
        dir: TTL 方向值，指定选中通道的方向 (binary format, e.g., 0b0001)
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


def ttl_set(mask, state):
    """设置 TTL 通道状态
    
    用于 TTL_ON/TTL_OFF 操作，设置TTL通道的输出状态
    
    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101) 
        state: TTL 状态值，指定选中通道的输出状态 (binary format, e.g., 0b0001)
    """
    # Convert binary masks to RTMQ "A.B" format if possible
    rtmq_mask = binary_to_rtmq_mask(mask)
    rtmq_state = binary_to_rtmq_mask(state)
    
    amk('ttl', rtmq_mask, rtmq_state)
    print(f"TTL_SET - mask={rtmq_mask}, state={rtmq_state}")
    print(f"  -> mask=0b{mask:08b}, state=0b{state:08b}")
    print("  TODO: 实现实际的OASM汇编调用")

def wait_us(duration):
    """等待指定微秒数
    
    Args:
        duration: 等待时长（微秒）
    """
    # print(f"OASM: Wait {duration} μs")
    t = round(duration * us)
    wait(t)  # 使用转换后的时间单位

def my_wait():
    """自定义等待操作"""
    print("OASM: My wait")


def trig_slave(param):
    """触发从设备
    
    Args:
        param: 触发参数
    """
    print(f"OASM: Trigger slave - param={param}")