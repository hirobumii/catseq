# 5. API 参考 (API Reference)

CatSeq 当前正在迁移新的 registered-source frontend。这里区分“现有公开接口”与
“尚未公开的内部前端”，避免把已经删除的 0.4 编译路径误当成可用 API。

## 当前实现边界

内部前端从真实 `BaseExp` 对象和对应 `ExpParams` 开始，按注册对象 identity
收集入口与可达定义，调用固定版本的 NAC3 验证 `@compute`，并生成
target-independent、Python-free 的 Typed Source HIR、Compute identity 和源码位置。

这个适配层目前是私有迁移接口。CatSeq 当前没有公开的端到端
`Compiler`、`CompiledSequence`、`EthernetRuntime`、`catseqc` 或 standalone
compiler。后续分析、Canonical Program、target lowering、linking 与高层执行接口
完成前，不提供旧路径 fallback。

## Restricted-source DSL

包级公开接口保留用于描述源码的类型和装饰器，包括：

- 唯一的时序值类型 `Morphism`；
- `morphism`、`atomic_morphism`、`Id`、`Wait`、`repeat_morphism`；
- `compute`；
- `Board`、`Channel`、`ChannelType`；
- `Duration`、`s`、`ms`、`us`、`ns`、`cycles(...)`。

这些 compiler-only 定义由原生前端解释。把它们当普通 CPython 函数执行会快速
失败，而不会运行另一套兼容语义。

## 低层 RTMQ runtime

`catseq.compilation.runtime` 保留独立的 assembled-program 执行接口：

- `AssembledOASMBoard`；
- `AssembledOASMProgram`；
- `BoardEndpoint`；
- `LinuxRawEthernetRuntimeConfig`；
- `execute_oasm_program(program, config)`；
- `CatSeqRuntimeError`。

它接收已经组装好的 OASM program 和显式物理路由，不接受 CatSeq source 或
Typed Source HIR，也不承担编译器 fallback。

## 宿主实验控制

`catseq.experiment` 只用于组织宿主侧实验领域，不从包级 `__init__` 批量重导出
类型。调用方应从定义概念的模块直接 import：

| 模块 | 公开概念 |
| --- | --- |
| `catseq.experiment.base_exp` | `BaseExp`，registered-source 实验定义 owner |
| `catseq.experiment.base_module` | `BaseModule`、`BaseService` 及其组合字段 |
| `catseq.experiment.params` | `ExpParam`、`ExpParams`、`ScanPoint` |
| `catseq.experiment.descartes` | `DescartesGenerator` 的 repeat/scan 遍历 |
| `catseq.experiment.para_dict` | append-only 的 `ParaDict` |
| `catseq.experiment.device` | 设备基类、字段与 `DeviceList` |
| `catseq.experiment.result` | `BaseResult` 与结果字段 |
| `catseq.experiment.analyzer` | `BaseAnalyzer`、`AnalyzerConfig` |
| `catseq.experiment.indexer` | analyzer 依赖查询使用的 `Indexer` |
| `catseq.experiment.panel` | `PanelUpdate`、`PanelPublisher` 与空 publisher |
| `catseq.experiment.h5` | 可选 `catseq[h5]` 依赖提供的 `H5Writer` |
| `catseq.experiment.run_control` | pause、resume、stop checkpoint |

`BaseExp` 当前只保留为 registered-source 实验定义 owner；它不再接受已经删除的
旧 `Compiler` 或 runtime facade。`BaseExp.run()` 会在启动 panel、H5、设备或源码
执行前明确报错，直到新的公开端到端路径完成。
