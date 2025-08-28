"""
CatSeq Object系统
实现范畴论中的对象（Objects）- 系统状态的完整描述
"""

from typing import Self
from dataclasses import dataclass, field
from .protocols import Channel, State


@dataclass(frozen=True)
class SystemState:
    """
    系统完整状态 - Category Theory中的对象（Object）
    
    表示某个时刻系统中所有相关通道的状态快照
    这是Morphism的定义域(dom)和值域(cod)的类型
    """
    channel_states: dict[Channel, State] = field(default_factory=dict)
    timestamp: float = 0.0
    
    def __post_init__(self) -> None:
        """验证状态的一致性"""
        if not self.channel_states:
            raise ValueError("SystemState must contain at least one channel state")
        
        # 验证每个状态与其通道兼容
        for channel, state in self.channel_states.items():
            try:
                # 这里应该有类型验证，暂时跳过
                pass
            except Exception as e:
                raise ValueError(f"State {state} incompatible with channel {channel}: {e}")
    
    @property
    def channels(self) -> set[Channel]:
        """获取所有通道"""
        return set(self.channel_states.keys())
    
    def get_state(self, channel: Channel) -> State:
        """获取指定通道的状态"""
        if channel not in self.channel_states:
            raise ValueError(f"Channel {channel} not found in system state")
        return self.channel_states[channel]
    
    def has_channel(self, channel: Channel) -> bool:
        """检查是否包含指定通道"""
        return channel in self.channel_states
    
    def with_channel_state(self, channel: Channel, state: State) -> Self:
        """创建包含新通道状态的系统状态"""
        new_channel_states = self.channel_states.copy()
        new_channel_states[channel] = state
        return type(self)(
            channel_states=new_channel_states,
            timestamp=self.timestamp
        )
    
    def without_channel(self, channel: Channel) -> Self:
        """创建移除指定通道的系统状态"""
        if channel not in self.channel_states:
            return self
        
        new_channel_states = self.channel_states.copy()
        del new_channel_states[channel]
        
        if not new_channel_states:
            raise ValueError("Cannot create empty SystemState")
            
        return type(self)(
            channel_states=new_channel_states,
            timestamp=self.timestamp
        )
    
    def merge_with(self, other: Self) -> Self:
        """
        合并两个系统状态
        
        用于并行组合时创建新的系统状态
        如果有重叠通道，other的状态会覆盖self的状态
        """
        merged_states = self.channel_states.copy()
        merged_states.update(other.channel_states)
        
        # 时间戳取较大值
        merged_timestamp = max(self.timestamp, other.timestamp)
        
        return type(self)(
            channel_states=merged_states,
            timestamp=merged_timestamp
        )
    
    def is_compatible_for_composition(self, other: Self) -> bool:
        """
        检查两个系统状态是否可以进行串行组合
        
        对于串行组合 m1 @ m2，需要 m1.cod 与 m2.dom 兼容
        兼容条件：重叠通道的状态必须相同
        """
        overlapping_channels = self.channels & other.channels
        
        for channel in overlapping_channels:
            if self.get_state(channel) != other.get_state(channel):
                return False
        
        return True
    
    def __len__(self) -> int:
        """返回包含的通道数量"""
        return len(self.channel_states)
    
    def __contains__(self, channel: Channel) -> bool:
        """检查是否包含指定通道"""
        return channel in self.channel_states
    
    def __repr__(self) -> str:
        channel_info = ", ".join(
            f"{channel.name}: {state}" 
            for channel, state in self.channel_states.items()
        )
        return f"SystemState({channel_info} @ t={self.timestamp:.3f})"


def create_system_state(*channel_state_pairs: tuple[Channel, State], timestamp: float = 0.0) -> SystemState:
    """
    便利函数：创建系统状态
    
    Args:
        *channel_state_pairs: (Channel, State) 对的序列
        timestamp: 时间戳
        
    Returns:
        SystemState实例
        
    Example:
        state = create_system_state(
            (ttl0, TTLOn()),
            (rwg0, RWGReady(carrier_freq=100.0)),
            timestamp=1.5
        )
    """
    channel_states = dict(channel_state_pairs)
    return SystemState(channel_states=channel_states, timestamp=timestamp)


class SystemStateBuilder:
    """
    系统状态构建器
    
    用于逐步构建复杂的系统状态
    """
    
    def __init__(self, timestamp: float = 0.0):
        self._channel_states: dict[Channel, State] = {}
        self._timestamp = timestamp
    
    def add_channel(self, channel: Channel, state: State) -> Self:
        """添加通道状态"""
        self._channel_states[channel] = state
        return self
    
    def set_timestamp(self, timestamp: float) -> Self:
        """设置时间戳"""
        self._timestamp = timestamp
        return self
    
    def build(self) -> SystemState:
        """构建系统状态"""
        if not self._channel_states:
            raise ValueError("SystemStateBuilder must contain at least one channel state")
        
        return SystemState(
            channel_states=self._channel_states.copy(),
            timestamp=self._timestamp
        )
    
    def clear(self) -> Self:
        """清除所有通道状态"""
        self._channel_states.clear()
        return self