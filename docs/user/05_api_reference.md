# 5. API 参考 (API Reference)

CatSeq 0.4 的接口分为时序编译/执行与宿主实验控制两层。实验控制代码不会被
CatSeq 编译器编译；每个 scan point 只有 `build_sequence` 和对应的不可变
`ExpParams` 会进入编译器。

## 时序编译与执行

- `catseq.Compiler`：持有 source root、通道、opaque call、target profile 与
  incremental cache，并通过 `compile(entry, *arguments)` 返回
  `CompiledSequence`。
- `catseq.CompiledSequence`：Rust 持有的不可变编译结果，包含 OASM Call Plan、
  逻辑时长、目标时钟、诊断与 incremental evidence。
- `catseq.EthernetRuntime`：持有物理网卡与机箱路由，通过 `run(compiled)` 执行
  一个 `CompiledSequence`。

### 时间 API

- `catseq.time_utils.Duration`：编译器识别的硬件 duration 注解。用户模板中把
  传给 `pulse`、`hold`、`rf_pulse` 或 `linear_ramp` 的参数标为该类型。
- `s`、`ms`、`us`、`ns`：source-language SI 单位。编译器按照选中 target 的
  `clock_hz` 换算，并要求结果是精确的非负 Cycle Count。
- `cycles(count)`：编译器专用构造器，显式声明非负整数 `count` 已经是目标周期
  数；它不能作为普通 CPython 宿主函数执行。
- `time_to_cycles(..., clock_hz=...)`、`us_to_cycles(..., clock_hz=...)`、
  `cycles_to_time(..., clock_hz=...)` 和 `cycles_to_us(..., clock_hz=...)`：宿主侧
  换算函数，必须显式传入正整数时钟。它们不使用全局默认时钟，也不会隐式舍入。

无单位数字不会隐式转换成 `Duration`。通过局部变量、模块常量或函数参数传递
也不会改变这条规则；如果 duration 是 target-relative 周期数，必须在 source
中写成 `cycles(...)`。

## 宿主实验控制

`catseq.experiment` 只用于组织领域，不从包级 `__init__` 批量重导出类型。
调用方应从定义该概念的模块直接 import：

| 模块 | 公开概念 |
| --- | --- |
| `catseq.experiment.base_exp` | `BaseExp`，完整实验生命周期 |
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

`BaseExp.run()` 是唯一完整实验编排入口。首个 scan point 同步编译；运行点 N
时预编译点 N+1，到达 N+1 时若尚未完成则等待。预编译本身不会将点写入
`ParaDict`，只有 Descartes 真正遍历到该点时才记录 attempted execution。

Compiler、runtime、具体设备、硬件锁、runner identity、MQTT publisher 和部署
策略由消费项目提供；CatSeq 不负责发现或构造这些平台对象。
