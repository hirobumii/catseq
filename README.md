# CatSeq

![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)
![Tests](https://img.shields.io/badge/tests-49%20passed-brightgreen.svg)

> **一个基于范畴论的量子实验序列控制框架** - 为量子物理实验提供数学严谨的硬件时序编程抽象

<p align="center">
  <a href="docs/user/01_quickstart.md"><strong>快速开始</strong></a> ·
  <a href="docs/user/02_core_concepts.md"><strong>核心概念</strong></a> ·
  <a href="docs/dev/compiler_notes.md">开发者文档</a> ·
  <a href="https://github.com/hirobumii/catseq/issues">报告 Bug</a>
</p>

---

## 目录

- [项目简介](#项目简介)
- [核心功能](#核心功能)
- [快速开始](#快速开始)
  - [先决条件](#先决条件)
  - [安装](#安装)
  - [基本用法](#基本用法)
- [设计理念](#设计理念)
- [项目路线图](#项目路线图)
- [如何贡献](#如何贡献)
- [许可证](#许可证)

## 项目简介

**CatSeq** (Category Theory-based Quantum Experiment Sequencing) 是一个专为量子物理实验设计的硬件控制框架。它基于 **Monoidal Category** 数学理论，为复杂的量子控制序列提供严格的数学基础和直观的编程抽象。

在传统的量子实验控制中，复杂的时序协调、状态管理和并行操作往往导致代码难以理解和维护。CatSeq 通过范畴论的**组合性**和**类型安全**，将这些复杂性抽象为可预测、可验证的数学对象，使得量子实验的编程变得直观而强大。

该框架特别适合需要**精确时序控制**（ns级精度）、**多通道协调**和**复杂波形合成**的量子物理研究团队使用。

## 核心功能

* **🧮 数学严谨性**: 基于 Monoidal Category 理论，提供可证明正确的操作组合
* **⚡ 精确时序**: 支持 250MHz 时钟精度（4ns），满足量子实验的严格时序要求  
* **🔀 灵活组合**: 通过 `@`（串行）和 `|`（并行）操作符实现直观的序列组合
* **🎛️ 多硬件支持**: 统一控制 TTL 开关、RWG 波形发生器等量子实验硬件
* **🔧 类型安全**: 编译时状态验证，避免硬件配置错误和时序冲突
* **⚙️ OASM 编译**: 直接编译为 RTMQ 硬件指令，无需手写底层汇编代码

## 快速开始

### 先决条件

在开始之前，请确保你的开发环境中安装了以下软件：
* [Python](https://python.org/) (版本 >= 3.12)
* [uv](https://docs.astral.sh/uv/) 现代 Python 包管理器

### 安装

**方式一：使用提供的安装脚本（推荐）**
```bash
git clone https://github.com/hirobumii/catseq.git
cd catseq
chmod +x setup.sh
./setup.sh
```

**方式二：手动安装**
```bash
# 1. 克隆仓库
git clone https://github.com/hirobumii/catseq.git
cd catseq

# 2. 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 创建虚拟环境并安装依赖
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .[dev]

# 4. 验证安装
.venv/bin/pytest tests/ -v
```

### 基本用法

以下是一个创建 TTL 脉冲序列的基础示例：

```python
from catseq import ttl_init, ttl_on, ttl_off, identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation import compile_to_oasm_calls

# 定义硬件通道
board = Board("RWG_0")
ttl_ch = Channel(board, 0, ChannelType.TTL)

# 构建序列：初始化 → 开启10μs → 关闭
pulse_sequence = (
    ttl_init(ttl_ch) @ 
    ttl_on(ttl_ch) @ 
    identity(ttl_ch, 10e-6) @ 
    ttl_off(ttl_ch)
)

# 编译为硬件指令
oasm_calls = compile_to_oasm_calls(pulse_sequence)

# 执行序列（需要 RTMQ 硬件环境）
# execute_oasm_calls(oasm_calls)
```

**并行操作示例**：
```python
# 创建两个不同通道的脉冲
ch1_pulse = ttl_on(ch1) @ identity(ch1, 5e-6) @ ttl_off(ch1)
ch2_pulse = ttl_on(ch2) @ identity(ch2, 8e-6) @ ttl_off(ch2)

# 并行执行（自动时间对齐）
parallel_sequence = ch1_pulse | ch2_pulse  # 总时长为 8μs
```

如需了解更高级的用法和 RWG 波形控制，请参阅我们的 [快速开始文档](docs/user/01_quickstart.md)。

## 设计理念

CatSeq 的设计基于以下核心原则：

### 🧮 范畴论基础
- **Objects**: 完整的系统状态（所有通道的状态映射）
- **Morphisms**: 物理过程（随时间演化的状态转换）  
- **Composition**: 严格的函数复合，保证状态连续性

### 🔒 类型安全优先
- 编译时状态验证，防止非法状态转换
- 强类型通道管理，避免硬件地址错误
- 自动推导状态转换，减少手动错误

### 🎯 用户友好性
- 直观的操作符：`@` 表示时序连接，`|` 表示并行执行
- 声明式编程风格，专注于"做什么"而非"怎么做"  
- 丰富的错误提示和调试信息

## 项目路线图

我们对 CatSeq 的未来发展有清晰的规划：

**v0.2.0** (2025 Q2)
- [ ] **可视化工具**: 时序图生成和交互式调试界面
- [ ] **更多硬件支持**: 支持更多量子实验设备类型
- [ ] **性能优化**: 大规模序列的编译优化

**v0.3.0** (2025 Q3)  
- [ ] **云端编译**: 支持远程硬件的实时控制
- [ ] **机器学习集成**: 自动化参数优化和序列学习
- [ ] **标准库扩展**: 常用量子实验操作的预定义库

欢迎查看我们的 [Issues](https://github.com/hirobumii/catseq/issues) 页面，了解更多详情并参与讨论。

## 如何贡献

我们非常欢迎社区的贡献！如果你希望参与进来，请遵循以下步骤：

1. Fork 本仓库
2. 创建你的功能分支 (`git checkout -b feature/AmazingFeature`)
3. 运行测试确保代码质量 (`.venv/bin/pytest tests/ -v`)
4. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
5. 推送到分支 (`git push origin feature/AmazingFeature`)
6. 创建一个 Pull Request

**开发环境设置**：
```bash
# 使用脚本快速设置
./setup.sh

# 或手动设置
source .venv/bin/activate
uv pip install -e .[dev]

# 运行测试套件
.venv/bin/pytest tests/ -v

# 代码格式检查
ruff check catseq/
mypy catseq/
```

在贡献之前，请务必运行测试套件确保所有 49 个测试都通过。

## 许可证

本项目基于 **MIT** 许可证进行分发。详情请见 `LICENSE` 文件。

## 致谢

- **范畴论理论基础**: 感谢数学家们在 Monoidal Category 理论上的贡献
- **RTMQ 硬件平台**: 为量子实验控制提供了强大的硬件基础
- **Python 生态系统**: NumPy, pytest, uv 等优秀工具让开发变得高效
- **uv 包管理器**: 为项目提供了快速可靠的依赖管理

---

<p align="center">
  <strong>CatSeq - 让量子实验控制回归数学之美</strong>
</p>