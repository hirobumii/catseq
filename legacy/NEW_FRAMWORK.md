### CatSeq框架改进与演进计划

**目标**：将CatSeq从一个具有坚实理论基础的核心框架，演进为一个**可扩展、高容错、表达力强且开发者友好**的工业级量子实验设计与控制平台。本计划旨在解决当前设计中的潜在瓶颈，并为未来功能扩展铺平道路。

---

### 路线图总览

本计划分为三个阶段，遵循“**稳固核心 -> 完善工具链 -> 扩展能力**”的演进路径。

* **阶段一：核心模型重构 (Foundational Enhancements)**
    * **目标**：解决状态管理的刚性和可扩展性问题，提升框架的灵活性和性能。
    * **关键成果**：引入部分状态管理，解耦通道依赖，实现确定性的序列构建。

* **阶段二：编译器与开发者体验优化 (Compiler & Tooling Maturity)**
    * **目标**：提升编译器的物理真实性和可靠性，并为开发者提供强大的调试工具。
    * **关键成果**：资源感知的编译器、高保真错误报告、序列可视化工具。

* **阶段三：高级功能与表达力扩展 (Advanced Capabilities & Expressiveness)**
    * **目标**：支持更复杂的实验逻辑，赋能用户构建可复用的高级时序库。
    * **关键成果**：动态控制流原型、参数化子序列（宏）功能。

---

### 阶段一：核心模型重构 (Foundational Enhancements)

#### 1.1. 实施部分状态（Partial State）管理模型
* **问题**：当前的`SystemState`是全局的，导致通道间不必要的耦合，且在大规模系统中存在性能瓶颈。
* **行动计划**：
    1.  **修改`Morphism`定义**：`dom`和`cod`中的`channel_states`仅需包含该`Morphism`直接影响的通道。
    2.  **重构组合逻辑 (`@`)**：
        * 验证时，仅对两个`Morphism`共同涉及的通道进行`cod`与`dom`的匹配检查。
        * 组合后的新`Morphism`的状态，通过合并两个`Morphism`的状态来计算。对于只在`m1`中出现、未在`m2`中改变的通道，其状态从`m1`的`cod`继承。
    3.  **更新并行逻辑 (`|`)**：合并`lanes`时，`dom`和`cod`也进行相应的合并，而不是填充所有通道的`IdentityMorphism`。

#### 1.2. 引入显式的序列构建器 (SequenceBuilder)
* **问题**：依赖隐式的全局`channel.get_current_state()`使序列构建过程不确定，不利于代码复用和测试。
* **行动计划**：
    1.  **创建`SequenceBuilder`类**：
        ```python
        class SequenceBuilder:
            def __init__(self, initial_state: SystemState):
                # ...
            
            def append(self, morphism: Morphism) -> None:
                # 在内部进行状态匹配和演化
                # ...
                
            def build(self) -> Morphism:
                # 返回最终组合好的、经过完全验证的Morphism
                # ...
        ```
    2.  **废弃隐式状态查询**：移除`channel.get_current_state()`方法，强制所有序列都在`SequenceBuilder`的上下文中构建。
    3.  **更新用户工作流**：
        * **之前 (隐式)**: `seq = ttl_pulse(...) @ identity(rwg0, ...)`
        * **之后 (显式)**:
            ```python
            # 定义初始条件
            initial_state = SystemState(channel_states={...})
            
            # 建立序列
            builder = SequenceBuilder(initial_state)
            builder.append(ttl_pulse(ttl0, 1e-6))
            builder.append(rwg_sweep(rwg0, 100, 200, 10e-3))
            
            # 生成最终序列
            final_sequence = builder.build()
            ```
        此举可确保序列的构建是**确定性**和**可移植**的。

---

### 阶段二：编译器与开发者体验优化 (Compiler & Tooling Maturity)

#### 2.1. 实现资源感知的编译器调度器
* **问题**：编译器的时间模型未考虑硬件总线竞争等共享资源冲突。
* **行动计划**：
    1.  **定义资源模型**：在硬件定义层 (`HardwareDevice`) 中声明其使用的共享资源（如`bus='FPGA_BUS_1'`）。
    2.  **增强编译器**：`RTMQCompiler`在调度`generate_write_instructions`时，必须检查目标资源是否被占用。
    3.  **冲突处理**：如果检测到总线冲突，编译器应采取策略，如自动插入等待指令 (`NOP`) 来序列化写入操作，并重新计算时序。如果无法在给定时间内解决冲突，则抛出详细的`CompilerResourceError`。

#### 2.2. 开发高保真错误报告系统
* **问题**：`CompositionError`等通用异常信息不足以帮助用户快速定位代码错误。
* **行动计划**：
    1.  **追踪元数据**：在`Morphism`创建时，记录其来源（如工厂函数名和参数）。
    2.  **提供上下文**：当组合失败时，错误信息应包含：
        * 哪两个高层操作 (`Morphism`) 无法组合。
        * 具体是哪个`Channel`的状态不匹配。
        * 期望的状态 (`expected`) 和实际遇到的状态 (`got`)。
        * **示例**：`CompositionError: Failed to compose 'rwg_sweep(rwg0, ...)' after 'hold(rwg0, ...)'. Reason: State mismatch on channel 'rwg0'. Expected initial frequency 200.0 MHz, but got 150.0 MHz.`

#### 2.3. 构建序列可视化与调试工具
* **问题**：复杂的`Morphism`对象内部结构不透明，难以调试。
* **行动计划**：
    1.  **实现`__repr__`和`_repr_html_`**：为`Morphism`提供丰富的文本和（在Jupyter中）HTML表示，清晰地展示每个`lane`的时序和总时长。
    2.  **开发`.visualize()`方法**：生成一个ASCII或图形化的时序图，直观展示多通道的并行与串行关系。
        ```
        Channel | 0ms      5ms      10ms     15ms
        --------|----------|--------|--------|------>
        ttl0    |--PULSE---|--HOLD--|
        rwg0    |--HOLD----|--SWEEP----------|
        ```

---

### 阶段三：高级功能与表达力扩展 (Advanced Capabilities & Expressiveness)

#### 3.1. 设计参数化子序列（宏）功能
* **问题**：缺乏官方支持来创建和复用带有参数的复杂子序列。
* **行动计划**：
    1.  **推广工厂函数模式**：鼓励用户编写返回`Morphism`的函数。
    2.  **支持函数式组合**：确保可以自然地将这些函数组合起来。
        ```python
        def ramsey_sequence(channel, freq_detuning, pulse_time, wait_time) -> Morphism:
            pi_half_pulse = rwg_pulse(channel, duration=pulse_time, freq_offset=0)
            wait = identity(channel, duration=wait_time)
            # 假设detuning通过phase实现
            final_pi_half = rwg_pulse(channel, duration=pulse_time, phase_offset=freq_detuning*wait_time)
            
            return pi_half_pulse @ wait @ final_pi_half
        
        # 使用
        exp_seq = ramsey_sequence(rwg1, 1e6, 1e-7, 5e-6)
        ```

#### 3.2. 探索动态控制流的原型设计
* **问题**：框架目前仅支持静态序列，无法响应实验过程中的实时反馈。
* **行动计划（研究性）**：
    1.  **定义`BranchMorphism`**：这是一个特殊的`Morphism`，它包含多个可能的执行路径和一个外部触发条件。
    2.  **编译器支持**：编译器需要能将这种`BranchMorphism`编译为特定的硬件指令，如“跳转-如果-触发器A为高”。
    3.  **硬件抽象**：在`HardwareDevice`协议中添加与实时触发和条件执行相关的接口。
    4.  **目标**：首先实现一个简单的`if/else`结构，例如，根据一个TTL输入信号的值，在两个预编译的`AtomicOperation`序列之间进行选择。
