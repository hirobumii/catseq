"""
Cat-SEQ Model - 重新设计的架构
实现范畴论正确的 Object-Morphism 关系和现代化的类型系统
"""

from typing import Tuple, Dict, Set, Union, Any, Optional, List
from dataclasses import dataclass
from abc import ABC, ABCMeta, abstractmethod
from catseq.protocols import Channel, State, Dynamics


# === 不使用元类，直接使用装饰器 ===


# === CatObject 系统 ===

class CatObject(ABC):
    """
    范畴论中的 Object - 系统状态
    支持并行组合操作
    """
    
    @abstractmethod
    def __or__(self, other: 'CatObject') -> 'CatObject':
        """并行组合 = 状态合并"""
        pass
    
    @abstractmethod
    def channels(self) -> Set[Channel]:
        """返回这个对象涉及的所有通道"""
        pass
    
    @abstractmethod
    def get_state(self, channel: Channel) -> State:
        """获取指定通道的状态"""
        pass


@dataclass(frozen=True)
class ChannelObject(CatObject):
    """单通道对象：(Channel, State) 对"""
    channel: Channel
    state: State
    
    def __or__(self, other: CatObject) -> 'TensorObject':
        """与其他对象并行组合"""
        if isinstance(other, ChannelObject):
            if self.channel == other.channel:
                raise ValueError(f"Cannot merge objects with same channel {self.channel}")
            return TensorObject(channel_states={
                self.channel: self.state,
                other.channel: other.state
            })
        elif isinstance(other, TensorObject):
            if self.channel in other.channel_states:
                raise ValueError(f"Channel {self.channel} already exists in system")
            return TensorObject(channel_states={
                **other.channel_states,
                self.channel: self.state
            })
        else:
            return NotImplemented
    
    def channels(self) -> Set[Channel]:
        return {self.channel}
    
    def get_state(self, channel: Channel) -> State:
        if channel != self.channel:
            raise ValueError(f"Channel {channel} not found in this object")
        return self.state


@dataclass(frozen=True)
class TensorObject(CatObject):
    """多通道张量对象 - 多个通道状态的并行组合"""
    channel_states: Dict[Channel, State]
    
    def __or__(self, other: CatObject) -> 'TensorObject':
        """张量对象的并行组合"""
        if isinstance(other, ChannelObject):
            if other.channel in self.channel_states:
                raise ValueError(f"Channel {other.channel} already exists")
            return TensorObject(channel_states={
                **self.channel_states,
                other.channel: other.state
            })
        elif isinstance(other, TensorObject):
            overlap = set(self.channel_states.keys()) & set(other.channel_states.keys())
            if overlap:
                raise ValueError(f"Channels {overlap} exist in both systems")
            return TensorObject(channel_states={
                **self.channel_states,
                **other.channel_states
            })
        else:
            return NotImplemented
    
    def channels(self) -> Set[Channel]:
        return set(self.channel_states.keys())
    
    def get_state(self, channel: Channel) -> State:
        if channel not in self.channel_states:
            raise ValueError(f"Channel {channel} not found in this system")
        return self.channel_states[channel]


# === Morphism 系统 ===

class Morphism(ABC):
    """
    顶层 Morphism 抽象基类
    定义所有 morphism 的基本契约，使用模板-实例化模式支持延迟绑定
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Morphism 的名称"""
        pass
    
    @property
    @abstractmethod
    def duration(self) -> float:
        """持续时间"""
        pass
    
    @property
    @abstractmethod
    def dom(self) -> CatObject:
        """域 - 起始对象（需要 channel 绑定后才能确定）"""
        pass
    
    @property
    @abstractmethod  
    def cod(self) -> CatObject:
        """值域 - 结束对象（需要 channel 绑定后才能确定）"""
        pass
    
    @abstractmethod
    def __call__(self, channels: Union[Channel, Dict[str, Channel]]) -> 'LaneMorphism':
        """应用到具体 channel，返回 LaneMorphism（模板实例化）"""
        pass
    
    def __matmul__(self, other: 'Morphism') -> 'Morphism':
        """序列组合 @"""
        return ComposedMorphism([self, other])
    
    def __or__(self, other: 'Morphism') -> 'Morphism':
        """并行组合 |"""
        return ParallelMorphism([self, other])


class PrimitiveMorphism(Morphism):
    """
    原子 morphism 抽象基类
    子类需要实现具体的领域逻辑
    """
    
    @abstractmethod
    def get_dom(self, channel: Channel) -> ChannelObject:
        """获取域（起始状态）- 需要 channel 信息"""
        pass
    
    @abstractmethod
    def get_cod(self, channel: Channel) -> ChannelObject:  
        """获取值域（结束状态）- 需要 channel 信息"""
        pass
    
    @property
    def dom(self) -> CatObject:
        """域 - 在没有具体 channel 时无法确定"""
        raise NotImplementedError("PrimitiveMorphism.dom requires channel binding")
    
    @property
    def cod(self) -> CatObject:
        """值域 - 在没有具体 channel 时无法确定"""
        raise NotImplementedError("PrimitiveMorphism.cod requires channel binding")
    
    def __call__(self, channel: Channel) -> 'LaneMorphism':
        """实例化为具体的 LaneMorphism"""
        # 创建具体的 primitive
        concrete = ConcretePrimitive(
            name=self._get_name_for_channel(channel),
            dom=(channel, self.get_dom(channel).state),
            cod=(channel, self.get_cod(channel).state), 
            duration=self.duration,
            morphism_type=getattr(self, 'morphism_type', None),
            source_morphism=self  # 保留对原始模板的引用
        )
        return LaneMorphism.from_primitive(concrete)
    
    def _get_name_for_channel(self, channel: Channel) -> str:
        """子类可以重写此方法来生成包含 channel 信息的名称"""
        return self.name


# === 组合 Morphism 类 ===

@dataclass(frozen=True)  
class ComposedMorphism(Morphism):
    """序列组合的 morphism"""
    morphisms: List[Morphism]
    
    def __post_init__(self):
        # 使用 object.__setattr__ 因为这是 frozen dataclass
        object.__setattr__(self, 'morphisms', self._flatten_composition(self.morphisms))
    
    def _flatten_composition(self, morphisms: List[Morphism]) -> List[Morphism]:
        """扁平化组合，避免深度嵌套"""
        flattened = []
        for m in morphisms:
            if isinstance(m, ComposedMorphism):
                flattened.extend(m.morphisms)  # 展开嵌套
            else:
                flattened.append(m)
        return flattened
    
    @property  
    def name(self) -> str:
        return " @ ".join(m.name for m in self.morphisms)
    
    @property
    def duration(self) -> float:
        return sum(m.duration for m in self.morphisms)
    
    @property
    def dom(self) -> CatObject:
        """序列组合的域是第一个 morphism 的域"""
        return self.morphisms[0].dom
    
    @property
    def cod(self) -> CatObject:
        """序列组合的值域是最后一个 morphism 的值域"""
        return self.morphisms[-1].cod
    
    def __call__(self, channels: Union[Channel, Dict[str, Channel]]) -> 'LaneMorphism':
        if isinstance(channels, Channel):
            # 单通道：依次组合
            result = self.morphisms[0](channels)
            for morphism in self.morphisms[1:]:
                result = result @ morphism(channels)
            return result
        else:
            # 多通道组合（复杂情况，需要状态传递逻辑）
            raise NotImplementedError("Multi-channel composed morphism not yet implemented")


@dataclass(frozen=True)
class ParallelMorphism(Morphism):
    """并行组合的 morphism"""
    morphisms: List[Morphism]
    
    @property
    def name(self) -> str:
        return " | ".join(m.name for m in self.morphisms)
    
    @property 
    def duration(self) -> float:
        return max(m.duration for m in self.morphisms)
    
    @property
    def dom(self) -> TensorObject:
        """并行组合的域是所有 morphism 域的并行组合"""
        # 这里需要实际的 channel 绑定才能计算
        raise NotImplementedError("ParallelMorphism.dom requires channel binding")
    
    @property
    def cod(self) -> TensorObject:
        """并行组合的值域是所有 morphism 值域的并行组合"""
        # 这里需要实际的 channel 绑定才能计算
        raise NotImplementedError("ParallelMorphism.cod requires channel binding")
    
    def __call__(self, channels: Union[Channel, Dict[str, Channel]]) -> 'LaneMorphism':
        if isinstance(channels, Channel):
            # 同一通道上的并行操作：需要时间同步
            lane_morphisms = [m(channels) for m in self.morphisms]
            result = lane_morphisms[0]
            for lm in lane_morphisms[1:]:
                result = result | lm
            return result
        else:
            # 不同通道的并行操作
            lane_morphisms = []
            for i, morphism in enumerate(self.morphisms):
                # 需要实现通道分配逻辑
                channel = channels.get(f"channel_{i}", list(channels.values())[i])
                lane_morphisms.append(morphism(channel))
            
            result = lane_morphisms[0]
            for lm in lane_morphisms[1:]:
                result = result | lm
            return result


# === 具体 Primitive（实例化后的） ===

@dataclass(frozen=True)
class ConcretePrimitive:
    """
    实例化后的具体 primitive，用于 LaneMorphism
    这是原来 PrimitiveMorphism 的角色
    """
    name: str
    dom: Tuple[Channel, State]
    cod: Tuple[Channel, State]  
    duration: float
    dynamics: Optional[Dynamics] = None
    morphism_type: Optional[str] = None
    source_morphism: Optional[Morphism] = None  # 指向原始模板


# === LaneMorphism（简化版，保持兼容性） ===

@dataclass(frozen=True)
class LaneMorphism:
    """
    具体的 Lane morphism，包含实例化后的 primitive 序列
    保持与现有代码的兼容性
    """
    lanes: Dict[Channel, List[ConcretePrimitive]]
    
    @property
    def duration(self) -> float:
        if not self.lanes:
            return 0.0
        return max(sum(p.duration for p in primitives) for primitives in self.lanes.values())
    
    @classmethod
    def from_primitive(cls, primitive: ConcretePrimitive) -> 'LaneMorphism':
        """从单个 primitive 创建 LaneMorphism"""
        channel = primitive.dom[0]
        return cls(lanes={channel: [primitive]})
    
    def __matmul__(self, other: 'LaneMorphism') -> 'LaneMorphism':
        """串行组合 - 简化实现"""
        # 保持现有逻辑，具体实现需要状态传递
        raise NotImplementedError("LaneMorphism composition needs implementation")
    
    def __or__(self, other: 'LaneMorphism') -> 'LaneMorphism':
        """并行组合 - 简化实现"""
        # 合并不冲突的 lanes
        combined_lanes = {**self.lanes}
        for channel, primitives in other.lanes.items():
            if channel in combined_lanes:
                raise ValueError(f"Channel {channel} exists in both morphisms")
            combined_lanes[channel] = primitives
        return LaneMorphism(lanes=combined_lanes)