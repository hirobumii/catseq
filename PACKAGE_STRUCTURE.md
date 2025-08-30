# CatSeq 包结构文档

## 概述

CatSeq 已重构为模块化的包结构，提高了代码的可维护性和可扩展性。新的结构将原来单一的 `ttl_minimal.py` 文件（1000+ 行）拆分为多个专门的模块。

## 包结构

```
catseq/
├── __init__.py              # 主要公共 API 导出
├── types.py                 # 核心类型：Board, Channel, TTLState, OperationType  
├── time_utils.py            # 时间转换工具：us_to_cycles, cycles_to_us
├── atomic.py                # 原子操作：AtomicMorphism, ttl_init, ttl_on, ttl_off, wait
├── morphism.py              # Morphism 类和组合逻辑：@, >>, | 操作符
├── lanes.py                 # Lane 和物理操作：Lane, PhysicalOperation, PhysicalLane
├── oasm/
│   ├── __init__.py          # OASM 接口导出
│   ├── types.py             # OASM 类型：OASMAddress, OASMFunction, OASMCall
│   ├── functions.py         # OASM DSL 函数：ttl_config, wait_us, etc.
│   └── compiler.py          # OASM 编译器：compile_to_oasm_calls, execute_oasm_calls
└── hardware/
    ├── __init__.py          # 硬件抽象导出  
    └── ttl.py               # TTL 硬件抽象：pulse, initialize_channel, etc.
```

## 模块说明

### 核心模块

#### `types.py`
- **职责**: 定义框架的基础数据类型
- **内容**: `Board`, `Channel`, `TTLState`, `OperationType`
- **依赖**: 无（基础层）

#### `time_utils.py`  
- **职责**: 时间单位转换工具
- **内容**: `us_to_cycles()`, `cycles_to_us()`, 时钟频率常量
- **依赖**: 无

#### `atomic.py`
- **职责**: 原子操作的定义和工厂函数
- **内容**: `AtomicMorphism` 类，`ttl_init()`, `ttl_on()`, `ttl_off()`, `wait()`
- **依赖**: `types`, `time_utils`

#### `lanes.py`
- **职责**: 物理层操作管理
- **内容**: `Lane`, `PhysicalOperation`, `PhysicalLane`, `merge_board_lanes()`
- **依赖**: `types`, `atomic`, `time_utils`

#### `morphism.py`
- **职责**: 高级组合逻辑和 Morphism 类
- **内容**: `Morphism` 类，组合操作符 `@`, `>>`, `|`，状态推断逻辑
- **依赖**: `types`, `atomic`, `lanes`, `time_utils`

### OASM 接口模块

#### `oasm/types.py`
- **职责**: OASM 接口类型定义
- **内容**: `OASMAddress`, `OASMFunction`, `OASMCall` 
- **依赖**: `functions` (for enum values)

#### `oasm/functions.py`
- **职责**: 实际的 OASM DSL 函数实现
- **内容**: `ttl_config()`, `wait_us()`, `my_wait()`, `trig_slave()`
- **依赖**: 无

#### `oasm/compiler.py`
- **职责**: Morphism 到 OASM 的编译逻辑
- **内容**: `compile_to_oasm_calls()`, `execute_oasm_calls()`
- **依赖**: `types`, `morphism`, `lanes`, `oasm.types`

### 硬件抽象模块

#### `hardware/ttl.py`
- **职责**: TTL 设备的高级抽象接口
- **内容**: `pulse()`, `initialize_channel()`, `set_high()`, `set_low()`, `hold()`
- **依赖**: `types`, `atomic`, `morphism`

## 公共 API

通过 `catseq` 包的主 `__init__.py` 导出的公共接口：

```python
import catseq

# 核心类型
catseq.Board, catseq.Channel, catseq.TTLState, catseq.OperationType

# 时间工具
catseq.us_to_cycles, catseq.cycles_to_us

# 原子操作
catseq.AtomicMorphism, catseq.ttl_init, catseq.ttl_on, catseq.ttl_off, catseq.wait

# Morphism 系统
catseq.Morphism, catseq.from_atomic

# 硬件抽象
catseq.pulse, catseq.initialize_channel, catseq.set_high, catseq.set_low, catseq.hold

# OASM 接口
catseq.compile_to_oasm_calls, catseq.execute_oasm_calls, catseq.OASMCall
```

## 使用示例

### 基本使用

```python
import catseq

# 创建硬件对象
rwg0 = catseq.Board("RWG_0")
laser_switch = catseq.Channel(rwg0, 0)
repump_switch = catseq.Channel(rwg0, 1)

# 使用高级接口
init_lasers = (catseq.initialize_channel(laser_switch) | 
               catseq.initialize_channel(repump_switch))

laser_pulse = catseq.pulse(laser_switch, 50.0)  # 50μs 脉冲
repump_pulse = catseq.pulse(repump_switch, 30.0) # 30μs 脉冲

# 组合序列
sequence = init_lasers @ (laser_pulse | repump_pulse)

# 编译为 OASM
oasm_calls = catseq.compile_to_oasm_calls(sequence)
```

### 低级接口使用

```python
import catseq

# 直接使用原子操作
rwg0 = catseq.Board("RWG_0")
ch0 = catseq.Channel(rwg0, 0)

# 构建原子操作序列
init_op = catseq.ttl_init(ch0)
on_op = catseq.ttl_on(ch0) 
wait_op = catseq.wait(10.0)
off_op = catseq.ttl_off(ch0)

# 组合为 Morphism
pulse_seq = (catseq.from_atomic(init_op) @ 
             catseq.from_atomic(on_op) >>
             catseq.from_atomic(wait_op) >>
             catseq.from_atomic(off_op))
```

## 优势

### 模块化收益
1. **可维护性**: 每个模块职责单一，便于理解和修改
2. **可测试性**: 可以独立测试每个模块的功能
3. **可扩展性**: 新的硬件类型可以添加到 `hardware/` 目录
4. **重用性**: 模块间依赖清晰，便于在不同场景下重用

### 依赖管理
- **层次化依赖**: 核心模块不依赖高级模块，避免循环依赖
- **最小依赖**: 每个模块只导入必要的依赖
- **清晰接口**: 通过 `__init__.py` 明确定义模块的公共接口

### 开发工作流
- **渐进开发**: 可以独立开发和测试每个功能模块
- **并行开发**: 多人可以同时在不同模块上工作
- **版本控制**: Git 历史更清晰，冲突更少

## 兼容性

新的模块化结构完全保持了与原 `ttl_minimal.py` 的功能兼容性：

- ✅ 所有原有 API 都可以通过 `catseq` 包访问
- ✅ 组合操作符行为完全一致（`@`, `>>`, `|`）
- ✅ OASM 编译结果相同
- ✅ 时序计算精确度保持不变
- ✅ 状态管理和验证逻辑相同

## 迁移指南

从 `ttl_minimal.py` 迁移到新结构：

```python
# 旧代码
from ttl_minimal import *

# 新代码
import catseq
# 或者
from catseq import Board, Channel, pulse, compile_to_oasm_calls
```

所有函数名和参数保持不变，只需要更改导入语句。