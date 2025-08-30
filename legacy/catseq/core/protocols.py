"""
CatSeq核心协议定义
定义系统的基础抽象接口，无内部依赖
"""

from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    """
    硬件状态基类
    
    表示某个时刻某个通道的具体状态
    所有具体状态类都应继承此类
    """
    pass


class HardwareDevice(Protocol):
    """
    硬件设备协议
    
    定义硬件设备必须实现的验证接口
    """
    
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """
        验证状态转换是否物理可行
        
        Args:
            from_state: 起始状态
            to_state: 目标状态
            
        Raises:
            PhysicsViolationError: 当状态转换违反物理约束时
        """
        ...
    
    def validate_taylor_coefficients(self, freq_coeffs: tuple[float, ...], amp_coeffs: tuple[float, ...]) -> None:
        """
        验证Taylor系数是否在硬件能力范围内
        
        Args:
            freq_coeffs: 频率Taylor系数 (F0, F1, F2, F3)
            amp_coeffs: 振幅Taylor系数 (A0, A1, A2, A3)
            
        Raises:
            PhysicsViolationError: 当系数违反硬件约束时
        """
        ...


class Channel:
    """
    通道标识符（单例模式）
    
    表示一个具体的硬件通道，如"ttl0", "rwg1_rf0"
    使用单例模式确保同名通道只有一个实例
    """
    
    _instances: dict[str, 'Channel'] = {}
    
    def __new__(cls, name: str, device: HardwareDevice) -> 'Channel':
        if not isinstance(name, str):
            raise TypeError("Channel name must be a string")
            
        # 单例模式：同名通道返回相同实例
        if name in cls._instances:
            return cls._instances[name]
            
        instance = super().__new__(cls)
        cls._instances[name] = instance
        return instance
    
    def __init__(self, name: str, device: HardwareDevice):
        if hasattr(self, '_initialized'):
            return
            
        self._name = name
        self._device = device
        self._current_state: State | None = None
        self._initialized = True
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def device(self) -> HardwareDevice:
        return self._device
    
    @property
    def current_state(self) -> State | None:
        return self._current_state
    
    def set_current_state(self, state: State) -> None:
        """设置当前状态（由系统内部调用）"""
        self._current_state = state
    
    def __repr__(self) -> str:
        return f"Channel('{self.name}')"
    
    def __hash__(self) -> int:
        return hash(self.name)
    
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Channel) and self.name == other.name


class PhysicsViolationError(Exception):
    """物理约束违反异常"""
    pass


class CompositionError(Exception):
    """Morphism组合错误异常"""  
    pass


class CompilerError(Exception):
    """编译器错误异常"""
    pass