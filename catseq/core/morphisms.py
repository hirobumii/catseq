"""
CatSeq Morphism系统
实现范畴论中的态射（Morphisms）- 经过验证的时序演化过程
"""

from dataclasses import dataclass, field

from .protocols import Channel, State, PhysicsViolationError, CompositionError
from .objects import SystemState


@dataclass(frozen=True)
class AtomicOperation:
    """
    原子操作：对应一个硬件waveform segment
    
    这是最小的不可分割的硬件操作单元
    每个原子操作对应硬件的一个segment，包含Taylor系数参数
    """
    channel: Channel
    from_state: State
    to_state: State
    duration: float                    # 波形播放时长（用户关心的时间）
    hardware_params: dict[str, tuple[float, ...]]  # Taylor系数等硬件参数
    
    def __post_init__(self) -> None:
        """验证原子操作的物理可行性"""
        if self.duration < 0:
            raise ValueError(f"Duration must be non-negative, got {self.duration}")
        
        # 验证状态转换的物理可行性
        try:
            self.channel.device.validate_transition(self.from_state, self.to_state)
        except Exception as e:
            raise PhysicsViolationError(f"Invalid state transition on {self.channel}: {e}")
        
        # 验证Taylor系数的硬件可行性
        if 'freq_coeffs' in self.hardware_params and 'amp_coeffs' in self.hardware_params:
            try:
                self.channel.device.validate_taylor_coefficients(
                    self.hardware_params['freq_coeffs'],
                    self.hardware_params['amp_coeffs']
                )
            except Exception as e:
                raise PhysicsViolationError(f"Invalid Taylor coefficients on {self.channel}: {e}")
    
    def get_write_instruction_count(self) -> int:
        """
        返回参数写入需要的指令数量
        用于编译器时序调度计算
        """
        # 简化实现：基于硬件参数估算指令数
        instruction_count = 0
        
        if 'freq_coeffs' in self.hardware_params:
            instruction_count += len(self.hardware_params['freq_coeffs'])  # F0, F1, F2, F3
        
        if 'amp_coeffs' in self.hardware_params:
            instruction_count += len(self.hardware_params['amp_coeffs'])   # A0, A1, A2, A3
        
        if 'phase' in self.hardware_params:
            instruction_count += 1  # POF寄存器
        
        # TTL等简单操作
        if instruction_count == 0:
            instruction_count = 1
        
        return instruction_count
    
    def __repr__(self) -> str:
        return f"AtomicOperation({self.channel.name}: {self.from_state} -> {self.to_state}, {self.duration:.3f}s)"


@dataclass(frozen=True)
class Morphism:
    """
    统一的Morphism类型 - 范畴论中的态射
    
    表示经过验证的时序演化过程，从一个SystemState到另一个SystemState
    内部使用lanes表示标准形式：每个通道对应一系列原子操作
    """
    dom: SystemState                   # 定义域（起始状态）
    cod: SystemState                   # 值域（结束状态）
    duration: float                    # 总时长
    lanes: dict[Channel, list[AtomicOperation]] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """验证Morphism的一致性"""
        if self.duration < 0:
            raise ValueError(f"Duration must be non-negative, got {self.duration}")
        
        # 验证lanes与dom/cod的一致性
        self._validate_dom_cod_consistency()
        
        # 验证每个lane的时长与总时长一致
        self._validate_lane_durations()
    
    def _validate_dom_cod_consistency(self) -> None:
        """验证lanes与dom/cod的一致性"""
        lane_channels = set(self.lanes.keys())
        dom_channels = self.dom.channels
        cod_channels = self.cod.channels
        
        # 验证通道集合匹配
        all_channels = dom_channels | cod_channels
        if lane_channels != all_channels:
            raise ValueError(f"Lane channels {lane_channels} don't match dom/cod channels {all_channels}")
        
        # 验证每个lane的起始和结束状态
        for channel, operations in self.lanes.items():
            if not operations:
                continue
            
            # 检查lane的起始状态
            if channel in dom_channels:
                expected_start = self.dom.get_state(channel)
                actual_start = operations[0].from_state
                if actual_start != expected_start:
                    raise ValueError(
                        f"Lane {channel} starts with {actual_start}, but dom expects {expected_start}"
                    )
            
            # 检查lane的结束状态
            if channel in cod_channels:
                expected_end = self.cod.get_state(channel)
                actual_end = operations[-1].to_state
                if actual_end != expected_end:
                    raise ValueError(
                        f"Lane {channel} ends with {actual_end}, but cod expects {expected_end}"
                    )
            
            # 检查lane内部状态连续性
            for i in range(len(operations) - 1):
                if operations[i].to_state != operations[i + 1].from_state:
                    raise ValueError(
                        f"Lane {channel} has discontinuity between operations {i} and {i+1}"
                    )
    
    def _validate_lane_durations(self) -> None:
        """验证每个lane的总时长与Morphism总时长一致"""
        for channel, operations in self.lanes.items():
            lane_duration = sum(op.duration for op in operations)
            if abs(lane_duration - self.duration) > 1e-9:  # 允许浮点误差
                raise ValueError(
                    f"Lane {channel} duration {lane_duration:.9f}s doesn't match "
                    f"Morphism duration {self.duration:.9f}s"
                )
    
    @property
    def channels(self) -> set[Channel]:
        """获取所有相关通道"""
        return set(self.lanes.keys())
    
    def get_lane_operations(self, channel: Channel) -> list[AtomicOperation]:
        """获取指定通道的操作序列"""
        return self.lanes.get(channel, [])
    
    def __matmul__(self, other: 'Morphism') -> 'Morphism':
        """
        @ 操作符：串行组合（时序连接）
        
        实现 morphism1 @ morphism2，要求 morphism1.cod 与 morphism2.dom 兼容
        """
        return _compose_serial(self, other)
    
    def __or__(self, other: 'Morphism') -> 'Morphism':
        """
        | 操作符：并行组合（同步执行）
        
        实现 morphismA | morphismB，自动同步时长并应用分配律
        """
        return _compose_parallel(self, other)
    
    def __repr__(self) -> str:
        channel_count = len(self.channels)
        return f"Morphism({channel_count} channels, {self.duration:.3f}s)"


def _compose_serial(m1: Morphism, m2: Morphism) -> Morphism:
    """
    串行组合实现：m1 @ m2
    
    要求：m1.cod 与 m2.dom 兼容（重叠通道的状态必须相同）
    """
    # 验证组合条件
    if not m1.cod.is_compatible_for_composition(m2.dom):
        raise CompositionError(
            "Cannot compose: m1.cod and m2.dom are incompatible. "
            "Overlapping channels have different states."
        )
    
    # 合并dom和cod - 需要包含所有通道
    new_dom = m1.dom.merge_with(m2.dom) 
    new_cod = m1.cod.merge_with(m2.cod)
    new_duration = m1.duration + m2.duration
    
    # 合并lanes
    new_lanes: dict[Channel, list[AtomicOperation]] = {}
    all_channels = m1.channels | m2.channels
    
    for channel in all_channels:
        m1_ops = m1.get_lane_operations(channel)
        m2_ops = m2.get_lane_operations(channel)
        
        # Handle cases where channel is not in both morphisms
        if channel in m1.channels and channel not in m2.channels:
            # Channel exists in m1 but not m2, need Identity for m2 duration
            m1_end_state = m1.cod.get_state(channel)
            identity_op = AtomicOperation(
                channel=channel,
                from_state=m1_end_state,
                to_state=m1_end_state,
                duration=m2.duration,
                hardware_params={}
            )
            new_lanes[channel] = m1_ops + [identity_op]
            
        elif channel not in m1.channels and channel in m2.channels:
            # Channel exists in m2 but not m1, need Identity for m1 duration  
            m2_start_state = m2.dom.get_state(channel)
            identity_op = AtomicOperation(
                channel=channel,
                from_state=m2_start_state,
                to_state=m2_start_state,
                duration=m1.duration,
                hardware_params={}
            )
            new_lanes[channel] = [identity_op] + m2_ops
            
        else:
            # Channel exists in both morphisms, direct concatenation
            new_lanes[channel] = m1_ops + m2_ops
    
    # 验证每个通道的转换
    for channel in all_channels:
        if channel in m1.channels and channel in m2.channels:
            # 通道在两个morphism中都存在，验证连接点状态
            m1_end_state = m1.cod.get_state(channel)
            m2_start_state = m2.dom.get_state(channel)
            
            try:
                channel.device.validate_transition(m1_end_state, m2_start_state)
            except Exception as e:
                raise CompositionError(f"Invalid transition on {channel} during composition: {e}")
    
    return Morphism(
        dom=new_dom,
        cod=new_cod,
        duration=new_duration,
        lanes=new_lanes
    )


def _compose_parallel(m1: Morphism, m2: Morphism) -> Morphism:
    """
    并行组合实现：m1 | m2
    
    自动同步时长，短的morphism自动补充Identity操作
    """
    # 检查通道冲突
    overlapping_channels = m1.channels & m2.channels
    if overlapping_channels:
        raise CompositionError(
            f"Cannot parallel compose: overlapping channels {overlapping_channels}"
        )
    
    # 计算同步时长
    max_duration = max(m1.duration, m2.duration)
    
    # 合并dom和cod
    new_dom = m1.dom.merge_with(m2.dom)
    new_cod = m1.cod.merge_with(m2.cod)
    
    # 合并lanes，自动添加Identity补齐
    new_lanes: dict[Channel, list[AtomicOperation]] = {}
    
    # 添加m1的lanes，必要时补齐时长
    for channel, operations in m1.lanes.items():
        new_lanes[channel] = operations.copy()
        
        # 如果m1较短，添加Identity操作补齐
        if m1.duration < max_duration:
            padding_duration = max_duration - m1.duration
            current_state = m1.cod.get_state(channel)
            
            identity_op = AtomicOperation(
                channel=channel,
                from_state=current_state,
                to_state=current_state,
                duration=padding_duration,
                hardware_params={}  # Identity操作无需特殊参数
            )
            new_lanes[channel].append(identity_op)
    
    # 添加m2的lanes，必要时补齐时长
    for channel, operations in m2.lanes.items():
        new_lanes[channel] = operations.copy()
        
        # 如果m2较短，添加Identity操作补齐
        if m2.duration < max_duration:
            padding_duration = max_duration - m2.duration
            current_state = m2.cod.get_state(channel)
            
            identity_op = AtomicOperation(
                channel=channel,
                from_state=current_state,
                to_state=current_state,
                duration=padding_duration,
                hardware_params={}
            )
            new_lanes[channel].append(identity_op)
    
    return Morphism(
        dom=new_dom,
        cod=new_cod,
        duration=max_duration,
        lanes=new_lanes
    )