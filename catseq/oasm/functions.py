"""
OASM DSL function definitions.

This module contains the actual OASM DSL functions that will be called
when executing compiled sequences on the hardware.
"""


def ttl_config(value, mask):
    """配置 TTL 通道状态
    
    Args:
        value: TTL 状态值 (0=OFF, 1=ON)
        mask: 通道掩码，指定哪些通道受影响
    """
    print(f"OASM: TTL config - value={value}, mask=0b{mask:08b}")


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