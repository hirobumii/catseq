# Plan 3: 编译器架构重构计划（基于硬件串行约束的修正版）

## 核心理解修正

### 关键硬件约束认识
1. **同板卡LOAD操作串行约束**：板卡内所有LOAD操作必须串行执行，共享写入硬件资源
2. **资源冲突检查分层**：硬件资源冲突应在Morphism组合阶段(`|`操作符)检查，编译器专注调度优化
3. **调度挑战**：在串行约束下实现智能的时间窗口利用，最大化硬件效率

## Plan 3架构重构

### 1. **占位符机制 (WAIT_TIME_PLACEHOLDER)**
- 引入`WAIT_TIME_PLACEHOLDER = -999999`常量
- Pass 1中SYNC_MASTER使用占位符：`TRIG_SLAVE(PLACEHOLDER, sync_code)`
- Pass 5中基于最终调度结果计算真实等待时间并替换占位符
- 解决调度优化影响同步时间计算的根本问题

### 2. **5-Pass清晰架构**
```
Pass 1: Extract & Translate
- 合并当前Pass 0+1，扁平化Morphism并翻译为OASMCall
- SYNC_MASTER使用占位符机制

Pass 2: Cost & Epoch Analysis  
- 合并当前Pass 1.5+2，成本分析和epoch检测
- 为后续串行调度提供准确的operation成本

Pass 3: Schedule & Optimize
- 新增专门调度Pass，实现串行约束下的智能调度
- 核心：基于deadline的LOAD串行调度算法

Pass 4: Constraint Validation
- 重构为纯验证Pass，检查调度后的结果
- 验证串行约束满足、时序一致性、无负等待时间

Pass 5: Final Code Generation
- 计算最终master wait time
- 替换所有WAIT_TIME_PLACEHOLDER
- 生成最终OASMCall序列
```

### 3. **串行调度算法核心**
实现考虑硬件串行约束的精细调度：

#### 调度策略
```python
def schedule_board_loads_with_serial_constraint(board_events):
    """基于串行约束和deadline的智能LOAD调度"""
    
    # 1. 分析LOAD-PLAY对应关系和deadline
    load_deadlines = calculate_load_deadlines(board_events)
    
    # 2. 按deadline排序，紧急的先执行
    sorted_loads = sort_by_deadline(load_operations)
    
    # 3. 串行调度，利用播放期间的时间窗口
    for load_op in sorted_loads:
        if not can_fit_before_deadline(load_op, current_time):
            # 寻找其他通道播放期间的可用时间窗口
            available_window = find_play_time_window(load_op)
            if available_window:
                reschedule_load_to_window(load_op, available_window)
            else:
                raise TimingViolationError("串行LOAD总时间超过可用窗口")
```

#### 调度示例
```
场景: t=5μs ch0_play, t=10μs ch1_play
LOAD约束: load0(1.4μs) + load1(0.7μs) 必须串行

策略A (保守): t=0开始串行 → t=2.1μs全部完成
策略B (优化): t=3.6μs开始load0 → t=5μs完成并开始ch0_play → 
             t=5μs开始load1(利用ch0播放期间) → t=5.7μs完成
```

### 4. **跨Epoch Pipeline支持**
- 修改`_identify_pipeline_pairs`支持跨epoch的LOAD-PLAY对识别
- 允许从后续epoch拉取LOAD操作到当前epoch执行
- 确保跨epoch调度不违反硬件串行约束

### 5. **Morphism层面约束检查增强**
在`parallel_compose_morphisms`中添加：
- 通道独立性验证（现有）
- SBG资源分配冲突检查
- 板卡级别硬件兼容性验证
- 早期发现不可并行的硬件操作组合

### 6. **调度后验证框架**
新的Pass 4专门验证调度优化后的结果：
- **串行约束验证**：确保同板卡LOAD操作确实被串行调度
- **deadline满足验证**：每个LOAD都在对应PLAY前完成
- **时序一致性检查**：无负等待时间，时间线连续
- **跨epoch边界验证**：调度优化没有违反epoch语义

## 实现路线图

### 第一阶段：核心架构重构
1. 实现占位符机制和Pass 5
2. 重构Pass架构，清晰分离职责
3. 实现基础的串行调度算法

### 第二阶段：调度算法优化
4. 完善时间窗口利用策略
5. 实现跨epoch pipeline支持
6. 优化调度性能和资源利用率

### 第三阶段：验证和完善
7. 完善调度后约束验证
8. 增强Morphism层面的约束检查
9. 完善错误诊断和调试支持

## 预期收益

### 正确性提升
- ✅ 正确处理硬件串行约束，避免资源冲突
- ✅ 准确的同步时间计算，确保多板卡协调
- ✅ 完整的调度后验证，及早发现时序问题

### 性能优化  
- ✅ 智能的时间窗口利用，最大化硬件并行度
- ✅ 跨epoch优化，突破单epoch调度限制
- ✅ 减少不必要的等待时间，提升执行效率

### 架构改进
- ✅ 符合Plan 3的清晰职责分离
- ✅ 更好的可测试性和可维护性
- ✅ 为未来硬件扩展提供良好基础

## 详细设计

### 串行LOAD调度算法详细设计

#### 硬件模型
```python
@dataclass
class BoardLoadConstraint:
    """板卡LOAD操作硬件约束"""
    board: Board
    max_concurrent_loads: int = 1  # 同时只能执行1个LOAD
    load_switching_overhead: int = 0  # LOAD切换开销(cycles)
    
    def can_parallel_load(self, load1: LogicalEvent, load2: LogicalEvent) -> bool:
        """检查两个LOAD是否可以并行 - 答案总是False"""
        return False
```

#### 调度算法核心逻辑
```python
def _pass3_schedule_and_optimize(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> Dict[OASMAddress, List[LogicalEvent]]:
    """Pass 3: 基于串行约束的调度优化"""
    print("Compiler Pass 3: Scheduling with serial load constraints...")
    
    optimized_events_by_board = {}
    
    for adr, events in events_by_board.items():
        # 1. 识别LOAD和PLAY操作
        load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
        play_events = [e for e in events if e.operation.operation_type == OperationType.RWG_UPDATE_PARAMS]
        
        # 2. 建立LOAD-PLAY对应关系
        load_play_pairs = identify_load_play_pairs(load_events, play_events)
        
        # 3. 计算每个LOAD的deadline
        load_deadlines = {}
        for pair in load_play_pairs:
            load_deadlines[pair.load_event] = pair.play_event.timestamp_cycles
        
        # 4. 按deadline排序LOAD操作
        sorted_loads = sorted(load_events, key=lambda x: load_deadlines.get(x, float('inf')))
        
        # 5. 串行调度LOAD操作
        scheduled_loads = schedule_loads_serially(sorted_loads, load_deadlines, play_events)
        
        # 6. 更新事件时间戳
        optimized_events = update_event_timestamps(events, scheduled_loads)
        optimized_events_by_board[adr] = optimized_events
        
    return optimized_events_by_board

def schedule_loads_serially(sorted_loads: List[LogicalEvent], 
                          load_deadlines: Dict[LogicalEvent, int],
                          play_events: List[LogicalEvent]) -> List[ScheduledLoad]:
    """串行调度LOAD操作，利用时间窗口优化"""
    
    scheduled_loads = []
    current_load_end_time = 0
    
    for load_event in sorted_loads:
        deadline = load_deadlines.get(load_event, float('inf'))
        load_duration = load_event.cost_cycles
        
        # 策略1：尝试在当前时间调度
        if current_load_end_time + load_duration <= deadline:
            # 可以在deadline前完成
            scheduled_loads.append(ScheduledLoad(
                event=load_event,
                start_time=current_load_end_time,
                end_time=current_load_end_time + load_duration
            ))
            current_load_end_time += load_duration
        else:
            # 策略2：寻找播放期间的时间窗口
            available_window = find_available_play_window(
                current_load_end_time, load_duration, deadline, play_events
            )
            
            if available_window:
                scheduled_loads.append(ScheduledLoad(
                    event=load_event,
                    start_time=available_window.start,
                    end_time=available_window.start + load_duration
                ))
                current_load_end_time = available_window.start + load_duration
            else:
                raise TimingViolationError(
                    f"无法为LOAD操作安排串行执行时间，deadline={deadline}, "
                    f"required_duration={load_duration}, current_time={current_load_end_time}"
                )
    
    return scheduled_loads

def find_available_play_window(current_time: int, required_duration: int, 
                             deadline: int, play_events: List[LogicalEvent]) -> Optional[TimeWindow]:
    """在其他通道的播放期间寻找可用时间窗口"""
    
    for play_event in play_events:
        play_start = play_event.timestamp_cycles
        play_duration = play_event.operation.duration_cycles
        play_end = play_start + play_duration
        
        # 检查播放期间是否有足够时间
        if (play_start >= current_time and 
            play_start + required_duration <= min(play_end, deadline)):
            return TimeWindow(start=play_start, duration=required_duration)
        
        # 检查播放期间的剩余时间
        if (play_start < current_time < play_end and
            current_time + required_duration <= min(play_end, deadline)):
            return TimeWindow(start=current_time, duration=required_duration)
    
    return None

@dataclass
class ScheduledLoad:
    """已调度的LOAD操作"""
    event: LogicalEvent
    start_time: int
    end_time: int

@dataclass  
class TimeWindow:
    """可用时间窗口"""
    start: int
    duration: int
```

### Pass 4约束验证详细设计

```python
def _pass4_validate_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """Pass 4: 调度后约束验证"""
    print("Compiler Pass 4: Validating constraints after scheduling...")
    
    for adr, events in events_by_board.items():
        # 1. 验证串行约束
        validate_serial_load_constraints(adr, events)
        
        # 2. 验证deadline满足
        validate_load_deadlines(adr, events)
        
        # 3. 验证时序一致性
        validate_timing_consistency(adr, events)
        
        # 4. 验证跨epoch边界
        validate_cross_epoch_boundaries(adr, events)

def validate_serial_load_constraints(adr: OASMAddress, events: List[LogicalEvent]):
    """验证LOAD操作确实被串行调度"""
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    
    for i in range(len(load_events) - 1):
        current_load = load_events[i]
        next_load = load_events[i + 1]
        
        current_end = current_load.timestamp_cycles + current_load.cost_cycles
        next_start = next_load.timestamp_cycles
        
        if next_start < current_end:
            raise ValueError(
                f"串行约束违规: 板卡{adr.value}上LOAD操作重叠, "
                f"load1结束于{current_end}, load2开始于{next_start}"
            )

def validate_load_deadlines(adr: OASMAddress, events: List[LogicalEvent]):
    """验证每个LOAD都在对应PLAY的deadline前完成"""
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    play_events = [e for e in events if e.operation.operation_type == OperationType.RWG_UPDATE_PARAMS]
    
    load_play_pairs = identify_load_play_pairs(load_events, play_events)
    
    for pair in load_play_pairs:
        load_end = pair.load_event.timestamp_cycles + pair.load_event.cost_cycles
        play_start = pair.play_event.timestamp_cycles
        
        if load_end > play_start:
            raise ValueError(
                f"Deadline违规: 板卡{adr.value}上LOAD操作未在PLAY开始前完成, "
                f"load结束于{load_end}, play开始于{play_start}"
            )
```

## 测试策略

### 单元测试
- 串行调度算法的各种场景测试
- 时间窗口查找算法测试
- 约束验证逻辑测试

### 集成测试  
- 多通道、多板卡复杂场景测试
- 跨epoch pipeline优化测试
- 边界条件和错误处理测试

### 性能测试
- 大规模序列编译性能测试
- 调度算法时间复杂度验证
- 内存使用优化验证