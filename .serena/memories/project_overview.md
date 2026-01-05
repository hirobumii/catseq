# CatSeq 项目概述

## 项目名称
**CatSeq** - Category Theory-based Quantum Experiment Sequencing

## 项目目的
CatSeq 是一个基于范畴论（Category Theory）的量子实验序列控制框架，专为量子物理实验设计。它提供了从高层数学抽象（Monoidal Category）到底层硬件控制（RTMQ/OASM 汇编）的完整编译工具链。

## 核心价值
- **数学严谨性**: 基于 Monoidal Category 理论，提供可证明正确的操作组合
- **精确时序**: 支持 250MHz 时钟分辨率（4ns），满足量子实验的严格时序要求
- **灵活组合**: 使用 `@` (串行) 和 `|` (并行) 操作符实现直观的序列组合
- **多硬件支持**: 统一控制多种量子实验硬件（TTL 开关、AWG 波形生成器等）
- **类型安全**: 编译时状态验证，防止硬件配置错误和时序冲突
- **OASM 编译**: 直接编译到 RTMQ 硬件指令，无需手写底层汇编代码

## 目标平台
- **RTMQ**: 专为量子实验控制设计的 32 位 SoC 框架
- **OASM**: RTMQ 汇编的 Python DSL 抽象
- **时钟频率**: 250 MHz (1 个时钟周期 = 4ns)

## 技术栈
- **语言**: Python 3.12+
- **核心依赖**:
  - `oasm.dev` - OASM DSL 库
  - `numpy` - 数值计算
  - `h5py`, `scipy` - 数据处理
  - `matplotlib` - 可视化
  - `dataclasses-json` - 数据类序列化
- **开发工具**:
  - `pytest`, `pytest-mock` - 测试框架
  - `ruff` - 代码格式化和 linting
  - `mypy` - 静态类型检查
  - `uv` - 现代 Python 包管理器

## 项目状态
- **版本**: 0.2.1 (xDSL/MLIR Integration)
- **测试**: 全部通过 (包括 19 个新的 xDSL 相关测试)
- **许可证**: MIT
- **新特性**: 
  - Program API (函数式编程接口)
  - xDSL/MLIR 编译器基础设施
  - 非递归设计（支持 10,000+ 层嵌套）

## 主要模块结构
```
catseq/
├── types/          # 类型定义（Board, Channel, State, OperationType）
├── atomic.py       # 原子操作定义（ttl_init, ttl_on, ttl_off, etc.）
├── morphism.py     # Morphism 抽象和组合操作
├── lanes.py        # Lane 和 PhysicalLane 实现
├── ast/            # 🆕 Program AST 和 IR 转换
│   ├── variables.py     # 运行时变量和编译时参数
│   ├── expressions.py   # 条件表达式 AST
│   ├── program_ast.py   # Program AST 节点定义
│   └── ast_to_ir.py     # AST → xDSL IR 非递归转换器
├── dialects/       # 🆕 xDSL/MLIR Dialects
│   ├── program_dialect.py  # Program dialect 操作定义
│   └── program_utils.py    # 非递归遍历工具
├── program.py      # 🆕 Program Monad API（函数式编程）
├── compilation/    # 五阶段编译器实现
│   ├── compiler.py      # 主编译流程
│   ├── functions.py     # OASM DSL 函数实现
│   ├── mask_utils.py    # 掩码转换工具
│   └── types.py         # 编译器类型定义
├── visualization/  # 时间线和调试可视化
└── hardware/       # 硬件抽象层
```

## 关键设计理念
基于 Monoidal Category 的数学结构：
- **Objects**: 完整系统状态（Channel→State 映射）
- **Morphisms**: 物理过程（时间演化）
- **串行组合** (`@`): 严格的函数复合，状态必须连续
- **并行组合** (`|`): 张量积，通道独立执行
- **Identity**: 自动时长补齐和状态保持
