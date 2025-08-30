"""
类型安全的 Device-State 绑定系统
使用 Python 3.12 的现代类型特性
"""

from typing import TypeVar, Generic, Type, cast, Self, Union, Unpack, TypedDict
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from catseq.protocols import State

# 定义受约束的 State 类型变量
StateT = TypeVar('StateT', bound=State)


# === TypedDict 定义 ===

class TTLDeviceConfig(TypedDict, total=False):
    """TTL设备配置参数"""
    voltage_levels: tuple[float, float]
    max_switching_frequency: float
    rise_time: float
    fall_time: float


class RWGDeviceConfig(TypedDict, total=False):
    """RWG设备配置参数"""
    amplitude_range: tuple[float, float]
    allow_ramping: bool
    allow_disable: bool
    enforce_continuity: bool
    max_freq_jump_mhz: float
    max_amp_jump_fs: float


class ChannelProperties(TypedDict, total=False):
    """通道属性配置"""
    description: str
    enabled: bool
    calibration_factor: float


class DeviceTypeConfig(TypedDict, total=False):
    """设备类型基础配置参数"""
    pass  # 抽象基类的配置，具体子类会扩展


@dataclass(frozen=True)
class DeviceType(Generic[StateT], ABC):
    """
    设备类型的抽象基类
    
    使用泛型 StateT 来约束这种设备类型支持的状态类型
    例如：TTLDeviceType[TTLState] 只能与 TTL 相关的状态配合使用
    """
    
    @abstractmethod
    def get_valid_state_types(self) -> set[Type[StateT]]:
        """返回这种设备类型支持的状态类型集合"""
        ...
    
    @abstractmethod
    def validate_transition(self, from_state: StateT, to_state: StateT) -> None:
        """
        验证状态转换是否合法
        
        Args:
            from_state: 起始状态（类型已约束为 StateT）
            to_state: 目标状态（类型已约束为 StateT）
            
        Raises:
            TypeError: 当状态转换不合法时
        """
        ...
    
    def is_valid_state(self, state: State) -> bool:
        """运行时检查状态是否与此设备类型兼容"""
        return type(state) in self.get_valid_state_types()
    
    def validate_state_type(self, state: State) -> StateT:
        """
        验证并转换状态类型
        
        Args:
            state: 要验证的状态
            
        Returns:
            经过类型验证的状态（类型为 StateT）
            
        Raises:
            TypeError: 当状态类型不兼容时
        """
        if not self.is_valid_state(state):
            valid_types = [t.__name__ for t in self.get_valid_state_types()]
            raise TypeError(
                f"State type {type(state).__name__} is not compatible with "
                f"device type {type(self).__name__}. "
                f"Valid state types: {valid_types}"
            )
        # 使用 cast 告诉类型检查器状态已经被验证为正确类型
        return cast(StateT, state)
    
    def clone(self, **changes: Unpack[DeviceTypeConfig]) -> Self:
        """克隆设备类型，可选择性修改某些字段"""
        # 使用 Self 类型，确保返回相同的具体类型
        current_dict = self.__dict__.copy()
        current_dict.update(changes)
        return type(self)(**current_dict)


# === 具体的设备类型实现 ===

from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff, TTLInput
from catseq.states.rwg import RWGState, RWGReady, RWGActive, RWGStaged, RWGArmed


@dataclass(frozen=True)
class TTLDeviceType(DeviceType[TTLState]):
    """TTL 设备类型，只支持 TTL 状态"""
    
    voltage_levels: tuple[float, float] = (0.0, 5.0)  # 使用内置 tuple 而非 Tuple
    max_switching_frequency: float = 1e6  # Hz，最大开关频率
    rise_time: float = 1e-9  # 秒，上升时间
    fall_time: float = 1e-9  # 秒，下降时间
    
    def get_valid_state_types(self) -> set[Type[TTLState]]:  # 使用内置 set
        """返回 TTL 设备支持的状态类型"""
        return {TTLOutputOn, TTLOutputOff, TTLInput}
    
    def validate_transition(self, from_state: TTLState, to_state: TTLState) -> None:
        """验证 TTL 状态转换"""
        # TTL 设备通常允许任意状态间的转换
        # 这里可以添加特定的业务逻辑，比如频率限制等
        
        valid_types = self.get_valid_state_types()
        if type(to_state) not in valid_types:
            raise TypeError(f"Invalid TTL target state: {type(to_state).__name__}")
        
        if type(from_state) not in valid_types:
            raise TypeError(f"Invalid TTL source state: {type(from_state).__name__}")
    
    def clone(self, **changes: Unpack[TTLDeviceConfig]) -> Self:
        """克隆TTL设备类型，支持TTL特定配置"""
        current_dict = self.__dict__.copy()
        current_dict.update(changes)
        return type(self)(**current_dict)


@dataclass(frozen=True)
class RWGDeviceType(DeviceType[RWGState]):
    """RWG 设备类型，只支持 RWG 状态"""
    
    available_sbgs: set[int]  # 使用内置 set
    max_ramping_order: int  # 最大斜率阶数
    frequency_range: tuple[float, float]  # MHz，频率范围
    amplitude_range: tuple[float, float] = (0.0, 1.0)  # 振幅范围（归一化）
    
    # 策略参数
    allow_ramping: bool = True
    allow_disable: bool = True
    enforce_continuity: bool = False
    max_freq_jump_mhz: float = 1e-3
    max_amp_jump_fs: float = 1e-3
    
    def get_valid_state_types(self) -> set[Type[RWGState]]:
        """返回 RWG 设备支持的状态类型"""
        return {RWGReady, RWGActive, RWGStaged, RWGArmed}
    
    def validate_transition(self, from_state: RWGState, to_state: RWGState) -> None:
        """验证 RWG 状态转换"""
        valid_types = self.get_valid_state_types()
        
        if type(to_state) not in valid_types:
            raise TypeError(f"Invalid RWG target state: {type(to_state).__name__}")
        
        if type(from_state) not in valid_types:
            raise TypeError(f"Invalid RWG source state: {type(from_state).__name__}")
        
        # RWG 特定的转换逻辑
        if isinstance(from_state, RWGActive) and isinstance(to_state, RWGActive):
            if self.enforce_continuity:
                self._validate_continuity(from_state, to_state)
    
    def _validate_continuity(self, from_state: RWGActive, to_state: RWGActive) -> None:
        """验证 RWG Active 状态间的连续性"""
        from_map = {wf.sbg_id: wf for wf in from_state.waveforms}
        to_map = {wf.sbg_id: wf for wf in to_state.waveforms}
        
        if from_map.keys() != to_map.keys():
            raise TypeError("RWG continuity violation: Active SBG set changed")
        
        for sbg_id, from_wf in from_map.items():
            to_wf = to_map[sbg_id]
            
            freq_jump = abs(from_wf.freq - to_wf.freq)
            if freq_jump > self.max_freq_jump_mhz:
                raise TypeError(
                    f"RWG frequency jump {freq_jump:.3f} MHz on SBG {sbg_id} "
                    f"exceeds limit {self.max_freq_jump_mhz:.3f} MHz"
                )
            
            amp_jump = abs(from_wf.amp - to_wf.amp)
            if amp_jump > self.max_amp_jump_fs:
                raise TypeError(
                    f"RWG amplitude jump {amp_jump:.3f} FS on SBG {sbg_id} "
                    f"exceeds limit {self.max_amp_jump_fs:.3f} FS"
                )
    
    def clone(self, **changes: Unpack[RWGDeviceConfig]) -> Self:
        """克隆RWG设备类型，支持RWG特定配置"""
        current_dict = self.__dict__.copy()
        current_dict.update(changes) 
        return type(self)(**current_dict)


# === 类型安全的 Channel ===

@dataclass(frozen=True)
class Channel(Generic[StateT]):
    """
    类型安全的通道
    
    泛型参数 StateT 确保通道只能与兼容的状态类型一起使用
    """
    name: str  # 通道名称，如 "ttl0", "rwg1_rf0"
    device_type: DeviceType[StateT]  # 设备类型，约束状态类型
    properties: dict[str, str | bool | float] = field(default_factory=dict)  # 使用内置 dict
    
    def validate_state(self, state: State) -> StateT:
        """
        验证状态是否与通道兼容
        
        Args:
            state: 要验证的状态
            
        Returns:
            验证后的状态（类型为 StateT）
        """
        return self.device_type.validate_state_type(state)
    
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """验证状态转换"""
        validated_from = self.validate_state(from_state)
        validated_to = self.validate_state(to_state)
        self.device_type.validate_transition(validated_from, validated_to)
    
    def clone(self, name: str | None = None, **device_changes: Unpack[DeviceTypeConfig]) -> Self:
        """克隆通道，可选择性修改名称或设备参数"""
        new_name = name or self.name
        new_device_type = self.device_type.clone(**device_changes) if device_changes else self.device_type
        return type(self)(
            name=new_name,
            device_type=new_device_type,
            properties=self.properties.copy()
        )


# === 类型别名 ===

# 为常用的通道类型定义别名，提高可读性
TTLChannel = Channel[TTLState]
RWGChannel = Channel[RWGState]

# 定义支持的状态类型联合
SupportedState = Union[TTLState, RWGState]

# 定义支持的通道类型联合  
SupportedChannel = Union[TTLChannel, RWGChannel]


# === 类型安全的 CatObject ===

@dataclass(frozen=True)
class TypedChannelObject(Generic[StateT]):
    """
    类型安全的 ChannelObject
    
    确保 channel 和 state 的类型一致性
    """
    channel: Channel[StateT]
    state: StateT
    
    def __post_init__(self) -> None:
        """运行时验证类型一致性"""
        # 验证状态与通道的兼容性
        self.channel.validate_state(self.state)
    
    def get_device_type(self) -> DeviceType[StateT]:
        """获取设备类型"""
        return self.channel.device_type
    
    def channels(self) -> set[Channel[StateT]]:  # 使用内置 set
        """返回通道集合（为了与现有 CatObject 接口兼容）"""
        return {self.channel}
    
    def with_state(self, new_state: StateT) -> Self:
        """创建具有新状态的对象"""
        return type(self)(channel=self.channel, state=new_state)
    
    def __or__(self, other: Self) -> "TypedTensorObject":
        """并行组合操作"""
        if self.channel.name == other.channel.name:
            raise ValueError(f"Cannot merge objects with same channel {self.channel.name}")
        
        return TypedTensorObject(channel_states={
            self.channel: self.state,
            other.channel: other.state
        })


@dataclass(frozen=True) 
class TypedTensorObject:
    """类型安全的多通道张量对象，支持TTL和RWG混合"""
    channel_states: dict[Channel[State], State]
    
    def __post_init__(self) -> None:
        """验证所有状态与通道的兼容性"""
        for channel, state in self.channel_states.items():
            channel.validate_state(state)
    
    def channels(self) -> set[SupportedChannel]:
        """返回所有通道"""
        return set(self.channel_states.keys())
    
    def get_state(self, channel: SupportedChannel) -> SupportedState:
        """获取指定通道的状态"""
        if channel not in self.channel_states:
            raise ValueError(f"Channel {channel.name} not found in tensor")
        return self.channel_states[channel]


# === 工厂函数 ===

def create_ttl_channel(name: str, **kwargs: Unpack[TTLDeviceConfig]) -> TTLChannel:
    """创建 TTL 通道的工厂函数"""
    device_type = TTLDeviceType(**kwargs)
    return Channel(name=name, device_type=device_type)


def create_rwg_channel(
    name: str, 
    available_sbgs: set[int], 
    max_ramping_order: int,
    frequency_range: tuple[float, float],
    **kwargs: Unpack[RWGDeviceConfig]
) -> RWGChannel:
    """创建 RWG 通道的工厂函数"""
    device_type = RWGDeviceType(
        available_sbgs=available_sbgs,
        max_ramping_order=max_ramping_order,
        frequency_range=frequency_range,
        **kwargs
    )
    return Channel(name=name, device_type=device_type)