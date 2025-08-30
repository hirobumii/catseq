# CatSeq 多通道同时操作处理机制

## 问题回答

**问题**: 我们现在是如何处理同一张板卡上不同通道在同一时间做操作的？

## 核心处理机制

CatSeq 通过以下三步流程处理同一板卡上多通道的同时操作：

### 1. **时间戳合并** (`merge_board_lanes`)

```python
def merge_board_lanes(board: Board, board_lanes: Dict[Channel, Lane]) -> PhysicalLane:
    physical_ops: List[PhysicalOperation] = []
    
    for channel, lane in board_lanes.items():
        timestamp = 0
        for op in lane.operations:
            # 记录所有TTL状态变化操作
            if op.operation_type in [TTL_INIT, TTL_ON, TTL_OFF]:
                physical_ops.append(PhysicalOperation(op, timestamp))
            timestamp += op.duration_cycles
    
    # 按时间戳排序 - 关键步骤！
    physical_ops.sort(key=lambda pop: pop.timestamp_cycles)
    return PhysicalLane(board, tuple(physical_ops))
```

**作用**: 将同一板卡上所有通道的操作按**精确时间戳**排序，形成统一的时间轴。

### 2. **事件分组** (`_extract_ttl_events`)

```python
def _extract_ttl_events(physical_lane) -> Dict[int, Dict[int, int]]:
    ttl_events: Dict[int, Dict[int, int]] = {}
    
    for pop in physical_lane.operations:
        timestamp = pop.timestamp_cycles
        channel_id = pop.operation.channel.local_id
        state_value = 1 if pop.operation.end_state.value == 1 else 0
        
        if timestamp not in ttl_events:
            ttl_events[timestamp] = {}
        ttl_events[timestamp][channel_id] = state_value
    
    return ttl_events
```

**作用**: 将相同时间戳的操作分组，形成 `时间戳 -> {通道: 状态}` 的映射。

### 3. **位掩码编码** (`_compute_ttl_config`)

```python
def _compute_ttl_config(channel_states: Dict[int, int]) -> Tuple[int, int]:
    value = 0
    mask = 0
    
    for channel_id, state in channel_states.items():
        mask |= (1 << channel_id)  # 标记该通道需要配置
        if state:
            value |= (1 << channel_id)  # 标记该通道为高电平
    
    return value, mask
```

**作用**: 将同时刻的多个通道状态编码为单个 `(value, mask)` 对，用于硬件调用。

## 实际例子

### 输入: 三通道并行初始化

```python
rwg0 = catseq.Board("RWG_0")
ch0 = catseq.Channel(rwg0, 0)
ch1 = catseq.Channel(rwg0, 1) 
ch2 = catseq.Channel(rwg0, 2)

init_all = (catseq.initialize_channel(ch0) |
            catseq.initialize_channel(ch1) |
            catseq.initialize_channel(ch2))
```

### 处理过程

1. **时间戳合并**:
   ```
   t=0μs: 通道0 TTL_INIT -> OFF
   t=0μs: 通道1 TTL_INIT -> OFF  
   t=0μs: 通道2 TTL_INIT -> OFF
   ```

2. **事件分组**:
   ```python
   ttl_events = {
       0: {0: 0, 1: 0, 2: 0}  # 时间0: 所有通道都设为OFF
   }
   ```

3. **位掩码编码**:
   ```python
   mask  = 0b00000111  # 通道 0,1,2 需要配置
   value = 0b00000000  # 通道 0,1,2 都设为 LOW
   ```

### 输出: 单个OASM调用

```python
seq('rwg0', ttl_config, 0, mask=7)
```

**结果**: 一个硬件调用同时配置三个通道！

## 复杂时序例子

### 输入: 多通道不同时序操作

```python
# 初始化所有通道
init_all = catseq.initialize_channel(ch0) | catseq.initialize_channel(ch1)

# ch0和ch1同时开启，然后同时关闭
lasers_on = catseq.set_high(ch0) | catseq.set_high(ch1)
wait_time = catseq.hold(10.0)  # 等待10微秒
lasers_off = catseq.set_low(ch0) | catseq.set_low(ch1)

sequence = init_all >> lasers_on >> wait_time >> lasers_off
```

### 时序分析

```
t=0.0μs: 通道0,1 初始化 -> OFF
t=0.0μs: 通道0,1 开启    -> ON  
t=0.0μs: 通道0,1 关闭    -> OFF
```

### 生成的OASM调用

```python
seq('rwg0', ttl_config, 0, mask=3)  # 初始化: ch0=OFF, ch1=OFF
seq('rwg0', ttl_config, 3, mask=3)  # 开启:   ch0=ON,  ch1=ON
seq('rwg0', ttl_config, 0, mask=3)  # 关闭:   ch0=OFF, ch1=OFF
```

## 关键优势

### 🚀 **硬件效率**
- **问题**: 朴素方式需要每个通道单独调用
- **解决**: 同时刻操作合并为单个调用
- **收益**: N个通道同时操作只需1个OASM调用

### ⏱️ **时序精度** 
- **问题**: 多个串行调用有累积延迟
- **解决**: 单个调用真正实现硬件同时执行
- **收益**: 微秒级精确同步

### 📊 **资源优化**
- **问题**: 过多OASM调用占用通信带宽
- **解决**: 最小化调用数量
- **收益**: 减少硬件通信开销

## 技术限制

### 位数限制
- **当前**: 32位整数，支持最多32个TTL通道每板卡
- **扩展**: 可升级为64位或数组支持更多通道

### 同步要求
- **严格同步**: 并行操作(`|`)要求完全相同的持续时间
- **灵活性**: 可通过自动状态推断(`>>`)处理不同时序

### 板卡隔离
- **范围**: 每个板卡独立处理
- **跨板卡**: 需要多个OASM调用协调

## 设计哲学

CatSeq的多通道处理体现了**硬件抽象与效率平衡**的设计哲学：

1. **数学抽象**: 用户使用直观的并行操作符 `|`
2. **物理优化**: 系统自动合并为高效的硬件调用
3. **时序保证**: 确保量子实验所需的精确时序

这种设计让用户专注于**实验逻辑**，而不用担心**硬件优化细节**。