# Cat-SEQ 架构设计讨论记录

## 背景
在实现 Cat-SEQ 到 RTMQ 编译器的过程中，我们需要重新设计整体架构以支持：
1. 类型安全的编译器识别
2. 优雅的组合操作 
3. 高性能的存储结构
4. 模板-实例化模式的延迟绑定
5. 范畴论正确的 Object-Morphism 关系

## 设计演进过程

### 1. 初始需求：类型化编译器
**问题**：编译器需要识别不同类型的 morphism 来生成对应的 OASM DSL 调用。

**讨论的方案**：
- `@primitive_handler(from_state=Uninitialized, to_state=RWGReady)` - 基于状态转换
- `@primitive_handler(primitive_type=RWGInitializePrimitive)` - 基于 primitive 类型
- `@primitive_handler(source_function=rwg.initialize)` - 基于来源函数

**结论**：使用 `primitive_type` 最合理，因为更直接且避免状态组合的复杂性。

### 2. 类 vs 函数设计
**问题**：是否将 `rwg.initialize()` 从函数改为类？

**优势**：
- 类型安全
- IDE 支持
- 编译器可以直接基于类型匹配

**设计思路**：
```python
class InitializeMorphism(MorphismBuilder):
    def __init__(self, carrier_freq: float, duration: float = 1e-6):
        self.carrier_freq = carrier_freq
        self.duration = duration
```

### 3. 继承层次设计
**问题**：`InitializeMorphism` 应该继承什么？

**讨论过程**：
1. 继承 `PrimitiveMorphism`？但 `PrimitiveMorphism` 是具体实例，不是抽象基类
2. 让 `PrimitiveMorphism` 成为半抽象对象？支持延迟求值
3. **最终方案**：`PrimitiveMorphism` 作为抽象基类

### 4. Dataclass 设计
**问题**：如何保持原有的 dataclass 设计？

**解决方案**：使用元类自动为所有 Morphism 子类添加 `@dataclass(frozen=True)`
```python
class DataclassMeta(ABCMeta):
    def __new__(cls, name, bases, namespace, **kwargs):
        new_class = super().__new__(cls, name, bases, namespace, **kwargs)
        if name != 'Morphism':
            new_class = dataclass(frozen=True)(new_class)
        return new_class
```

### 5. 延迟绑定问题
**问题**：`dom`/`cod` 需要 channel 信息，但 dataclass 字段是固定的。

**讨论的方案**：
1. 将 channel 作为 dataclass 字段？
   - **问题**：失去组合阶段的灵活性和重用性
2. **采用方案**：模板-实例化模式
   - Morphism 类是模板（无 channel 信息）
   - 调用 `morphism(channel)` 时实例化为 `LaneMorphism`

### 6. 组合性能问题
**问题**：`ComposedMorphism([self, other])` 在大量组合时会创建深度嵌套结构。

**解决方案**：扁平化组合
```python
def __matmul__(self, other):
    if isinstance(other, ComposedMorphism):
        return ComposedMorphism(self.morphisms + other.morphisms)
    else:
        return ComposedMorphism(self.morphisms + [other])
```

### 7. 分配律需求
**关键需求**：实现 `(A1(1μs) | B1(2μs)) @ (A2(3μs) | B2(2μs)) => (A1(1μs)@Identity(1μs)@A2(3μs))|(B1(2μs)@B2(2μs)@Identity(1μs))`

**设计目标**：
- 自动应用分配律
- 智能插入 Identity 进行时间同步
- 按 channel 重新分组

### 8. 标准化存储结构
**最终要求**：确保存储形式是每个通道的 `@` 组合 morphism 的 `|`

**标准化形式**：
```python
NormalizedMorphism(lanes={
    ChannelA: [M1, Identity(...), M2, M3, ...],
    ChannelB: [M4, M5, Identity(...), M6, ...]
})
```

**性能优势**：
- 扁平存储，无嵌套
- O(1) 访问每个通道的序列
- 支持任意复杂度的组合而不影响性能

## Object 设计讨论

### 1. **Object 架构需求**
范畴论中，Object 表示系统状态，Morphism 表示状态转换。我们需要设计正确的 Object 系统。

### 2. **Object 设计问题讨论**

#### 问题1：元类自动 dataclass 化
类似 Morphism，State/Object 是否也应该使用元类自动添加 `@dataclass(frozen=True)`？
**结论**：同意使用元类，保持设计一致性。

#### 问题2：组合状态 vs Object 并行
**讨论**：`TTLOutputOn() | RWGActive()` 这样的 State 组合语义不明确。
**结论**：不应该定义 State 的 `|`，而应该定义 Object 的 `|`。

#### 问题3：SystemObject 的使用场景
**使用场景**：
- 实验序列的状态检查点
- 状态转换的完整性验证
- 并行 morphism 的状态管理

**结论**：Morphism `|` 组合后，其 dom 与 cod 自动被 `|` 组合，形成 TensorObject。

#### 问题4：Pending 值的重新考虑
**当前问题**：使用 `Union[float, PendingType]` 实现状态传递，但可能有更好的方案。
**决定**：先聚焦其他设计，这个问题后续单独讨论。

#### 问题5：Object 并行的定义
**定义**：Object 并行 = 状态的合并（不同通道状态的组合）
**语义**：无通道冲突的状态合并，形成系统级对象。

### 3. **Object 架构设计**

#### 层次结构
```
State (不支持组合，使用元类自动 dataclass)
├── TTLState
│   ├── TTLOutputOn
│   └── TTLOutputOff  
└── RWGState
    ├── RWGReady
    └── RWGActive

Object (系统级概念，支持并行组合)
├── ChannelObject        # 单通道对象：(Channel, State) 对
└── TensorObject         # 多通道张量对象：Dict[Channel, State]
```

#### Object 设计细节
```python
class Object(ABC, metaclass=ObjectMeta):
    """范畴论中的 Object - 系统状态"""
    
    @abstractmethod
    def __or__(self, other: 'Object') -> 'Object':
        """并行组合 = 状态合并"""
        pass

class ChannelObject(Object):
    """单通道对象：(Channel, State) 对"""
    channel: Channel
    state: State

class TensorObject(Object):
    """多通道张量对象：无冲突的状态合并"""
    channel_states: Dict[Channel, State]
```

#### Morphism-Object 关系
```python
class Morphism(ABC):
    @property
    @abstractmethod
    def dom(self) -> Object:
        """域 - 起始对象"""
        pass
    
    @property 
    @abstractmethod
    def cod(self) -> Object:
        """值域 - 结束对象"""
        pass
```

## 最终架构设计

### 完整类层次结构
```
# Object 系统
State (ABC + StateMeta)
├── TTLState
│   ├── TTLOutputOn
│   └── TTLOutputOff
└── RWGState
    ├── RWGReady  
    └── RWGActive

CatObject (ABC + CatObjectMeta)  
├── ChannelObject
└── TensorObject

# Morphism 系统
Morphism (ABC + DataclassMeta)
├── PrimitiveMorphism (ABC)
│   ├── InitializeMorphism
│   ├── LinearRampMorphism  
│   ├── TTLPulseMorphism
│   └── IdentityMorphism
├── ComposedMorphism
├── ParallelMorphism
└── NormalizedMorphism (最终存储形式)
```

### 核心特性
1. **元类自动 dataclass 化**：所有子类自动获得 `@dataclass(frozen=True)`
2. **模板-实例化模式**：支持延迟绑定和重用
3. **自动标准化**：所有组合操作最终返回 `NormalizedMorphism`
4. **分配律支持**：智能应用代数规则和时间同步
5. **扁平存储**：保证高性能，支持大规模组合

### 使用模式
```python
# 定义 morphism 模板
init = InitializeMorphism(carrier_freq=100.0)
ramp = LinearRampMorphism(end_freq=20.0, duration=50e-6)
pulse = TTLPulseMorphism(duration=1e-6)

# 抽象组合（自动标准化）
sequence = init @ ramp                    # 串行组合
parallel = init | pulse                   # 并行组合，自动产生正确的 Object

# Object 自动组合示例
# parallel.dom = TensorObject({rwg_ch: Uninitialized, ttl_ch: TTLOff})
# parallel.cod = TensorObject({rwg_ch: RWGReady, ttl_ch: TTLOn})

# 应用到具体 channel
rwg0 = Channel("RWG_0", RWGDevice) 
ttl0 = Channel("TTL_0", TTLDevice)
concrete = parallel({rwg0: rwg0, ttl0: ttl0})  # 返回 LaneMorphism
```

### 编译器集成
```python
@primitive_handler(morphism_type="rwg_initialize")
def handle_rwg_initialize(morphism_instance, primitive, channel):
    return ('catseq_rwg_init', {
        'carrier_freq': morphism_instance.carrier_freq,
        'duration': morphism_instance.duration
    })
```

## 待实现任务
1. 实现元类系统 (DataclassMeta, ObjectMeta, StateMeta)
2. 实现 Object 系统 (Object, ChannelObject, SystemObject)
3. 重构 Morphism 抽象基类和 dom/cod 返回 Object
4. 创建具体 Morphism 类 (InitializeMorphism 等)
5. 实现标准化算法和分配律
6. 更新编译器以支持新的类型系统
7. 更新 LaneMorphism 以使用 ConcretePrimitive
8. 讨论和解决 Pending 值的替代方案

## 架构设计原则总结
- **范畴论正确性**：正确的 Object-Morphism 关系，dom/cod 返回 Object
- **类型安全**：基于具体类型而非字符串匹配，使用元类保证一致性
- **性能优先**：扁平化存储，避免深度嵌套，支持大规模组合  
- **代数正确性**：自动应用分配律等数学规则，智能时间同步
- **使用简洁**：保持简单的组合语法 `@` 和 `|`，自动标准化
- **语义清晰**：State 是单通道状态，Object 是系统状态，Morphism 是状态转换
- **向后兼容**：尽量保持现有 API 不变，渐进式重构

## 重要设计决策记录
1. **不为 State 定义组合操作**：避免语义混乱，组合在 Object 层面进行
2. **使用模板-实例化模式**：支持延迟绑定，提高重用性
3. **自动标准化存储**：所有组合操作最终返回扁平化的标准形式
4. **元类统一管理**：所有相关类自动获得 dataclass 装饰器，保持一致性
5. **分离关注点**：State 专注单通道状态，Object 处理系统级状态，Morphism 处理转换逻辑