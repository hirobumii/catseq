# CatSeq 代码风格和约定

## Python 版本
- **最低要求**: Python 3.12+
- **类型提示**: 广泛使用类型注解（PEP 484）
- **数据类**: 使用 `@dataclass(frozen=True)` 实现不可变数据结构

## 代码格式化

### Ruff 配置
```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F"]
ignore = ["E501", "E701"]  # 暂时忽略行长度和单行多语句
```

### 命名约定
- **模块名**: 小写下划线 `compiler.py`, `mask_utils.py`
- **类名**: 大驼峰 `Morphism`, `AtomicMorphism`, `PhysicalLane`
- **函数名**: 小写下划线 `compile_to_oasm_calls()`, `merge_board_lanes()`
- **常量**: 全大写下划线 `TIMING_CRITICAL_OPERATIONS`, `WAIT_TIME_PLACEHOLDER`
- **私有函数**: 前缀下划线 `_pass1_extract_and_translate()`

### 类型提示规范
```python
# ✅ 推荐：完整的类型注解
def compile_to_oasm_calls(
    morphism: Morphism, 
    assembler_seq=None, 
    _return_internal_events: bool = False,
    verbose: bool = False
) -> Union[Dict[OASMAddress, List[OASMCall]], Dict[OASMAddress, List[LogicalEvent]]]:
    ...

# ✅ 推荐：数据类使用 frozen=True
@dataclass(frozen=True)
class Morphism:
    lanes: Dict[Channel, Lane]
    
# ✅ 推荐：使用类型别名提高可读性
EventsByBoard = Dict[OASMAddress, List[LogicalEvent]]
```

## 文档字符串

### Docstring 风格
使用 Google 风格的 docstring：

```python
def merge_board_lanes(board: Board, board_lanes: Dict[Channel, Lane]) -> PhysicalLane:
    """将同一板卡的多个通道 Lane 合并为 PhysicalLane
    
    Args:
        board: 目标板卡
        board_lanes: 该板卡上的通道-Lane映射
        
    Returns:
        合并后的物理Lane，包含所有操作的时间戳
    """
```

### 中英文混用
- 用户文档和注释可以使用中文
- 函数名、变量名必须使用英文
- Docstring 可以使用中文（如上例）

## 数据不可变性

### Frozen Dataclasses
所有核心数据结构使用 `frozen=True`：
```python
@dataclass(frozen=True)
class Board:
    id: str

@dataclass(frozen=True)
class Channel:
    board: Board
    local_id: int
    channel_type: ChannelType
```

**原因**:
- 函数式编程风格
- 支持安全的并发和缓存
- 所有组合操作创建新对象，不修改原对象

## 操作符重载

### Morphism 组合操作符
```python
# @ - 严格串行组合
seq = ttl_on(ch) @ ttl_off(ch)

# >> - 自动状态推导组合
seq = ttl_init(ch) >> wait(10e-6) >> ttl_on(ch)

# | - 并行组合
parallel = pulse1 | pulse2
```

**实现方式**: 通过魔术方法 `__matmul__`, `__rshift__`, `__or__`

## 错误处理

### 编译时错误
使用描述性的 `ValueError` 和 `RuntimeError`：
```python
if overlapping_channels:
    channel_names = [ch.global_id for ch in overlapping_channels]
    raise ValueError(f"Cannot compose: overlapping channels {channel_names}")
```

### 调试输出
使用 `verbose` 参数控制详细输出：
```python
def compile_to_oasm_calls(morphism, verbose: bool = False) -> ...:
    if verbose:
        print("Compiler Pass 1: Extracting events...")
```

## 测试约定

### 测试文件组织
```
tests/
├── unit/              # 单元测试
│   ├── test_morphism.py
│   ├── test_lanes.py
│   └── test_compiler.py
└── integration/       # 集成测试
    ├── test_ttl_sequence.py
    └── test_rwg_sequence.py
```

### 测试命名
```python
def test_parallel_compose_different_channels():
    """测试不同通道的并行组合"""
    ...

def test_parallel_compose_overlapping_channels_raises_error():
    """测试重叠通道的并行组合应抛出错误"""
    ...
```

## Import 组织

### 标准顺序
1. 标准库导入
2. 第三方库导入
3. 本地模块导入

```python
# 标准库
from dataclasses import dataclass
from typing import Dict, List

# 第三方库
import numpy as np
from oasm.rtmq2 import amk, sfs

# 本地模块
from ..types.common import Channel, Board
from ..lanes import Lane, merge_board_lanes
```

## Mypy 配置

```toml
[tool.mypy]
namespace_packages = true
exclude = ["build/"]
```

确保代码通过 mypy 类型检查。

## 常见模式

### Pattern Matching (Python 3.10+)
```python
match op.operation_type:
    case OperationType.RWG_INIT:
        # 处理 RWG 初始化
        pass
    case OperationType.TTL_ON:
        # 处理 TTL 开启
        pass
    case _:
        # 默认情况
        pass
```

### 字典推导和解包
```python
# 合并字典
result_lanes = {**left.lanes, **right.lanes}

# 字典推导
events_by_ts = {ts: [e for e in events if e.timestamp == ts] 
                for ts in unique_timestamps}
```

### 链式方法调用
```python
# 支持的链式调用
morphism = (
    ttl_init(ch1) 
    >> ttl_on(ch1) 
    >> identity(ch1, 10e-6) 
    >> ttl_off(ch1)
)
```
