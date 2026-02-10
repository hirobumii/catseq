# RTLink 数据帧 Barrier 同步协议

基于 RTLink 数据帧和指令帧实现 master 控制的多板卡 barrier 同步。

## 问题描述

分布式量子控制系统中，多个 slave 板卡各自等待一个时间不确定的外部触发。
Master 需要在**所有**板卡都接收到触发之后，给每个板卡同时发出 trigger，
确保此时刻之后整个系统保持时钟级别的同步。

```
Slave0: ──────[ext_trig]──ready────────────────[sync_trig]══ synchronized ══>
Slave1: ──[ext_trig]──ready────────────────────[sync_trig]══ synchronized ══>
Slave2: ──────────────────[ext_trig]──ready────[sync_trig]══ synchronized ══>
Master: ──────────────────────────collect_all──[broadcast ]══ synchronized ══>
                                                ↑
                                      此刻之后所有板卡同步
```

## 协议总览

协议分三个阶段，使用两种 RTLink 帧类型：

| 阶段 | 方向 | 帧类型 | 用途 |
|:---:|:---:|:---:|:---|
| Phase 1 | slave → master | 数据帧 | 就绪通知（不需要精确时序） |
| Phase 2 | master 本地 | — | 收集所有就绪通知 |
| Phase 3 | master → slaves | 指令帧(广播) | 同步触发（cycle-accurate） |

### 为什么 Phase 1 用数据帧、Phase 3 用指令帧

| 特性 | 数据帧 (TYP=0) | 指令帧 (TYP=1) |
|:---|:---|:---|
| TAG 字段含义 | payload 标签（索引 scratchpad） | **延迟补偿值**（时钟周期数） |
| 中继时 TAG 处理 | 原样转发 | **自动扣减通信延迟和处理开销** |
| 消费方式 | 存入 scratchpad，可触发 TGM | **waiting pool 等待剩余延迟归零后注入 RT-Core** |
| 时序精度 | 不同 slave 收到时间不同 | **所有 slave 在同一时钟周期执行** |

Phase 1 的就绪通知不需要精确时序，数据帧即可。Phase 3 的同步触发
必须 cycle-accurate，只有指令帧的延迟补偿机制能满足。

---

## Phase 1: Slave 等待外部触发并发送就绪通知

每个 slave（如 RWG 板卡）执行以下流程：
1. 配置 GPIO 为外部触发输入
2. 使能对应 resume channel，`NOP H` 等待触发
3. 触发到达后，向 master 发送就绪数据帧
4. 配置 CDM，`NOP H` 等待 master 同步触发

### Slave 汇编

```asm
% ============================================================
% Phase 1: 等待外部触发
% ============================================================
% RWG GPIO trigger → resume channel #7 (mask: 2.3)

% 配置 GPIO 端口 0 为上升沿输入
SFS - DIO DIR
AMK - DIO 1.0 $01          % 端口 0 → 输入
SFS - DIO POS
AMK - DIO 1.0 $01          % 上升沿敏感
AMK - TTL 1.0 $01          % 使能端口 0 事件检测

% 等待外部触发
AMK - RSM 2.3 $01          % RSM[7] = 1, 使能 channel #7
NOP H                       % ===== 阻塞 =====

% --- 外部触发到达，RT-Core 恢复 ---

% ============================================================
% 发送就绪数据帧给 Master
% ============================================================
% 数据帧: TYP=0, SRF=00 (normal), TAG=SLAVE_TAG, ADR=0x0000 (master)
% Payload = 0xFFFFFFFF_FFFFFFFF (就绪标记)
%
% 每个 slave 使用唯一的 TAG 值 (slave #1 → TAG=1, #2 → TAG=2, ...)
% Master 通过 TAG 索引 scratchpad 区分各 slave。

SFS - FRM DST
CHI - FRM 0                % CHN = 0 (master local channel #0)
CLO - FRM 0                % ADR = 0x0000 (master 地址)

SFS - FRM TAG
CHI - FRM 0                % TYP=0, SRF=00
CLO - FRM SLAVE_TAG         % TAG = 本 slave 的唯一标识

SFS - FRM PL0
CHI - FRM -1
CLO - FRM -1               % PL0 = 0xFFFFFFFF

SFS - FRM PL1
CHI - FRM -1
CLO - FRM -1               % PL1 = 0xFFFFFFFF → 写 PL1 触发帧发送

% ============================================================
% 准备接收 Master 同步触发
% ============================================================
% 配置 CDM 监控 coded trigger = 0xFACE

SFS - SCP CDM
CHI - SCP 0x80000000
CLO - SCP 0x8000FACE        % CDM[31]=1 (enable), CDM[19:0]=0xFACE

AMK - RSM 2.0 $01           % RSM[1] = 1, 使能 channel #1 (coded trigger)
NOP H                        % ===== 阻塞，等待同步触发 =====

% --- Master 触发到达，所有 Slave 同时恢复 ---
% ========== 此处开始同步执行 ==========
```

### 关键设计说明

**FRM 寄存器写入顺序**：写 `FRM.PL1` 的副作用是组装并发送帧，因此 PL1 必须最后写。

**TAG 分配**：每个 slave 使用唯一 TAG（1, 2, 3, ...），master 通过
`SCP.MEM[TAG*2]` 和 `SCP.MEM[TAG*2+1]` 访问对应 payload。

**CDM/COD 配对**：所有 slave 使用相同的 CDM 监控码（如 `0xFACE`），
master 的广播指令帧会同时向所有 slave 写入匹配的 COD 值。

---

## Phase 2: Master 收集就绪通知

### 收集策略选择

| 方案 | 机制 | 优点 | 缺点 |
|:---|:---|:---|:---|
| TGM 顺序等待 | 依次监控每个 TAG | 零 CPU 开销 (NOP H) | 可能错过已到达的帧 |
| SCP.MEM 轮询 | 循环读 scratchpad | 不遗漏 | 持续消耗 CPU |
| **TGM + SCP.MEM** | **先建 TGM，再查 MEM** | **无竞态、零遗漏** | 逻辑稍复杂 |

**采用方案：TGM 先行建立 + SCP.MEM 回查兜底**。

### 正确的操作顺序

对每个 slave_i，Master 执行：

```
Step 1: 建立 TGM → Step 2: 使能 RSM → Step 3: 回查 SCP.MEM → Step 4: 条件 NOP H
```

这个顺序是唯一正确的。下面分析为什么。

### Master 汇编

```asm
% ============================================================
% Master 初始化
% ============================================================
% 设置 NEX.ADR[31]=1: master 只转发广播帧，不自己消费
% （避免 Phase 3 的广播指令帧干扰 master 自身执行流）

SFS - NEX ADR
CHI - NEX 0x80000000
CLO - NEX 0x80000000        % ADR[31]=1, ADR[15:0]=0x0000

% ============================================================
% Phase 2: 逐个确认 slave 就绪
% ============================================================
% 以 slave #1 (TAG=1) 为例

% --- Step 1: 建立 TGM 捕获 ---
SFS - SCP TGM
CHI - SCP 0x80000000
CLO - SCP 0x80000001        % TGM[31]=1 (enable), TGM[19:0]=1 (TAG=1)

% --- Step 2: 使能 RSM channel #1 ---
AMK - RSM 2.0 $01           % RSM[1] = 1, 副作用: 清除所有 pending

% --- Step 3: 回查 SCP.MEM ---
SFS - SCP MEM
CLO - SCP 3                 % 地址 = TAG*2+1 = 1*2+1 = 3 (PL1)
NOP P                        % 等待 7 cycles
CSR - $03 SCP               % $03 = scratchpad 值

% --- Step 4: 条件跳转 ---
NOP -                        % TCS read-after-write gap
NEQ - $04 $03 $00           % $04 = ($03 != 0) ? -1 : 0
AMK P PTR $04 2              % 已到达 ($04=-1): 跳过 NOP H
NOP H                        % 未到达: 阻塞等待 TGM 触发

% --- Slave #1 已确认，处理 Slave #2 (TAG=2) ---
SFS - SCP TGM
CHI - SCP 0x80000000
CLO - SCP 0x80000002        % 监控 TAG=2

AMK - RSM 2.0 $01           % 使能 ch#1, 清除 stale pending

SFS - SCP MEM
CLO - SCP 5                 % 地址 = 2*2+1 = 5
NOP P
CSR - $03 SCP

NOP -
NEQ - $04 $03 $00
AMK P PTR $04 2
NOP H

% --- Slave #3 (TAG=3) 同理 ---
% ...

% ============================================================
% 所有 slave 已就绪，进入 Phase 3
% ============================================================
```

### 条件跳转说明

`AMK P PTR $04 2` 利用 PTR 作为 numeric CSR 的 AMK 语义：

- `$04 = -1` (0xFFFFFFFF): R0\[1:0\] = 0b11 → PTR = PTR + 2（跳过 NOP H）
- `$04 = 0`: R0\[1:0\] = 0b00 → PTR 不变（落入 NOP H）

P flag 确保流水线正确刷新，无论是否发生跳转。

---

## Phase 2 竞态条件分析

### 精确时序

```
Cycle  0: SFS - SCP TGM           ─┐
Cycle  1: CHI - SCP 0x800...       │ TGM 建立
Cycle  2: CLO - SCP 0x800...TAG   ─┘ TGM 生效
Cycle  3: AMK - RSM 2.0 $01         RSM 使能 + 清 pending
Cycle  4: SFS - SCP MEM           ─┐
Cycle  5: CLO - SCP addr           │
Cycle 6-12: NOP P (7 cycles)       │ SCP.MEM 读取
Cycle 13: CSR - $03 SCP            ─┘
Cycle 14: NOP -                      TCS gap
Cycle 15: NEQ - $04 $03 $00         比较
Cycle 16: AMK P PTR $04 2           条件跳转 (+7~10 cycles)
Cycle ~24: NOP H (仅未到达时)
```

单次 check 快速路径: **~24 cycles (96 ns)**。

### 竞态窗口覆盖证明

数据帧可能在任意时刻 T 到达。以下逐窗口证明不存在死锁：

#### 场景 1: T < cycle 2（TGM 建立之前）

```
帧已存入 scratchpad           ✓
TGM 未配置，不会触发          —
Cycle 13: SCP.MEM 读到数据    ✓  ← MEM 兜底
Cycle 16: 跳过 NOP H          ✓
```

#### 场景 2: cycle 2 ≤ T < cycle 3（TGM 已建立，RSM 尚未写入）

```
帧存入 scratchpad              ✓
TGM 触发 → pending on ch#1    ✓
Cycle 3: RSM 写入清除 pending  ✗  pending 丢失
Cycle 13: SCP.MEM 读到数据     ✓  ← MEM 兜底
Cycle 16: 跳过 NOP H           ✓
```

虽然 pending 被 RSM 写入的 "clear all pending" 副作用清除，
但 SCP.MEM 回查发现数据已存在，直接跳过等待。

#### 场景 3: cycle 3 ≤ T < cycle 13（RSM 已使能，MEM 读取进行中）

```
帧存入 scratchpad              ✓
TGM 触发 → pending on ch#1    ✓
RSM[1] 已使能，RT-Core 非 hold
→ pending 保持（RSM spec: "requests from enabled channels will stay"）

Cycle 13: SCP.MEM 可能读到数据
  如果读到 → 跳过 NOP H        ✓  ← MEM 兜底
  如果未读到（极端时序）→ NOP H → pending 立即恢复  ✓  ← TGM 兜底
```

双重保障：MEM 兜底 **或** TGM pending 立即恢复，两者互补。

#### 场景 4: cycle 13 ≤ T < NOP H（已判定"未到达"，正在跳转）

```
SCP.MEM 读到 0（帧尚未到达时的值）
进入条件跳转逻辑，准备 NOP H
帧到达 → TGM 触发 → pending on ch#1
NOP H → pending 立即恢复       ✓  ← TGM 兜底
```

#### 场景 5: T ≥ NOP H（标准等待路径）

```
NOP H 阻塞中
帧到达 → TGM 触发 → resume ch#1 → 恢复  ✓
```

### 覆盖总结

| 帧到达时刻 | TGM | MEM 回查 | 结果 |
|:---|:---:|:---:|:---|
| TGM 之前 | 未配置 | **读到数据** | 快速跳过 |
| TGM ~ RSM | 触发但 **pending 被清** | **读到数据** | MEM 兜底跳过 |
| RSM ~ MEM 读 | 触发，**pending 保持** | 可能读到 | MEM 兜底 或 pending 立即恢复 |
| MEM 读 ~ NOP H | 触发，**pending 保持** | 未读到 | NOP H 立即恢复 |
| NOP H 之后 | 触发 | — | 标准恢复 |

**结论：TGM 实时捕获与 SCP.MEM 历史查询互补覆盖全部时序窗口，协议无死锁。**

### 跨 slave 的 stale pending 清除

场景 3 中如果走了 MEM 兜底路径（跳过 NOP H），channel #1 上残留一个
stale pending request。处理下一个 slave 时：

```asm
AMK - RSM 2.0 $01    % 为 slave_{i+1} 使能 RSM
                       % 副作用: 清除 slave_i 的 stale pending  ✓
```

每轮开头的 RSM 写入自然清除上一轮残留，无需额外处理。

---

## Phase 3: Master 广播同步触发

### RTLink 指令帧延迟补偿原理

```
Master 发出指令帧, TAG = L

  ├──→ Slave #1 (通信延迟 d1)
  │      到达时 TAG 剩余 = L - d1
  │      waiting pool 等待 (L - d1) cycles
  │      执行时刻 = 发出时刻 + L  ────┐
  │                                    │ 相同
  ├──→ Slave #2 (通信延迟 d2 > d1)    │
  │      到达时 TAG 剩余 = L - d2      │
  │      waiting pool 等待 (L - d2)    │
  │      执行时刻 = 发出时刻 + L  ────┘
  │
  └──→ 所有 slave 在同一时钟周期执行
```

RTLink 每经过一个中继节点，自动从 TAG 中扣减该段通信延迟和处理开销
（延迟值由 `NEX.&00` ~ `NEX.&1F` 配置）。到达目标节点后，指令帧在
waiting pool 中等待剩余 TAG 归零，然后注入 RT-Core 执行。

### 广播指令帧 payload 设计

帧携带两条 RTMQ 机器码，在每个 slave 的 RT-Core 上依次执行：

| 指令 | 汇编 | 机器码 | 作用 |
|:---:|:---|:---|:---|
| PL0 (先执行) | `SFS - SCP COD` | `0x0E880003` | 选择 SCP 子文件的 COD 寄存器 |
| PL1 (后执行) | `CLO - SCP 0xFACE` | `0x0E90FACE` | 写入 COD = 0xFACE |

执行后 `COD[19:0] == CDM[19:0] == 0xFACE` 且 `CDM[31] == 1`，
触发 resume channel #1，恢复 slave 的 RT-Core。

**机器码编码验证**：

```
SFS - SCP COD:
  SF = 0x0E (SCP 地址)
  opc = 0x8, mode = 0x8 (direct), CSR = 0x03 (COD)
  → |0E|8|8|00|03| = 0x0E880003  ✓

CLO - SCP 0xFACE:
  RD = 0x0E (SCP 地址)
  opc = 0x9 (CLO, flag '-')
  imm[19:0] = 0xFACE
  → |0E|9|FACE| → 0x0E90FACE  ✓
```

### Master 汇编

```asm
% ============================================================
% Phase 3: 广播同步触发
% ============================================================

% 设置目标: 广播到所有节点
SFS - FRM DST
CHI - FRM 0
CLO - FRM 0x0000FFFF       % CHN=0 (local ch#0), ADR=0xFFFF (wildcard)

% 设置帧类型: 广播指令帧 + 延迟补偿
%   TAG[22]    = 1  (TYP = instruction)
%   TAG[21:20] = 01 (SRF = broadcast)
%   TAG[19:0]  = 延迟值 (cycles)
SFS - FRM TAG
CHI - FRM 0x00500000        % TYP=1, SRF=01
CLO - FRM 0x00500100        % TAG = 0x100 = 256 cycles (~1 μs)

% 写入 payload: 两条触发指令
SFS - FRM PL0
CHI - FRM 0x0E880003        % SFS - SCP COD
CLO - FRM 0x0E880003

SFS - FRM PL1
CHI - FRM 0x0E90FACE        % CLO - SCP 0xFACE
CLO - FRM 0x0E90FACE        % 写 PL1 → 帧组装并发送

% ============================================================
% 广播已发出
% 所有 slave 将在 TAG 延迟后同一时钟周期恢复
% Master 自身不受影响 (NEX.ADR[31]=1)
% ============================================================
```

### NEX.ADR[31] 的作用

Master 发出广播帧时，路由逻辑对 `ADR=0xFFFF` (wildcard):
- 匹配当前节点 → 投递到 local channel **且**转发到所有广播使能的 remote channel

如果 master 也消费该帧，注入的 `SFS + CLO` 指令会干扰 master 的执行流
（中断当前的 SFS 上下文、修改 SCP.COD 等）。

设置 `NEX.ADR[31] = 1` 后，master **只转发、不消费**广播帧，避免干扰。

### TAG 延迟值选取

TAG 必须 **≥ 网络中 master 到最远 slave 的单程延迟**。

| 拓扑 | 典型单程延迟 | 建议 TAG |
|:---|:---|:---|
| 同机箱 backplane | 10-20 cycles (40-80 ns) | 256 cycles (1 μs) |
| 跨机箱 10GbE | 1000-5000 cycles | 根据 echo 帧校准 |

- TAG 偏大：仅增加触发延迟（256 cycles = 1 μs，可忽略），不影响同步精度
- TAG 偏小：部分 slave 剩余延迟为负 → 指令立即执行 → **同步失败**

延迟校准值存储在各节点的 `NEX.&00` ~ `NEX.&1F`（per-remote-channel），
在网络建立阶段通过 echo 帧自动校准。

---

## 完整时序图

```
              ext_trig
Slave0  ════════╗═══════════════════════════════════════════════════
                ▼
          wait GPIO trig
          NOP H ──resume──┐
                          ▼
                    send data frame ──→ Master SCP[TAG=1]
                    setup CDM=0xFACE
                    NOP H (等待 sync)
                                                          ┌─ COD=0xFACE
                                                          ▼   CDM match
                                                      resume ═══════>
                                                               同步执行

              ext_trig
Slave1  ══╗═════════════════════════════════════════════════════════
          ▼
    NOP H ──resume──┐
                    ▼
              send data frame ──→ Master SCP[TAG=2]
              setup CDM=0xFACE
              NOP H (等待 sync)
                                                          ┌─ COD=0xFACE
                                                          ▼
                                                      resume ═══════>
                                                               同步执行
              ext_trig
Slave2  ══════════════╗═════════════════════════════════════════════
                      ▼
                NOP H ──resume──┐
                                ▼
                          send data frame ──→ Master SCP[TAG=3]
                          setup CDM=0xFACE
                          NOP H (等待 sync)
                                                          ┌─ COD=0xFACE
                                                          ▼
                                                      resume ═══════>
                                                               同步执行

Master  ════════════════════════════════════════════════════════════
          setup NEX.ADR[31]=1

          TGM←TAG=1, RSM, check MEM[1]
            ├─ found → skip
            └─ not found → NOP H → TGM resume
          TGM←TAG=2, RSM, check MEM[2]    ← RSM 写入清除 stale pending
            ├─ found → skip
            └─ not found → NOP H → TGM resume
          TGM←TAG=3, RSM, check MEM[3]
            ├─ found → skip
            └─ not found → NOP H → TGM resume

          所有 slave 就绪!
                    │
                    ▼
          broadcast instruction frame
          PL0 = SFS - SCP COD   (0x0E880003)
          PL1 = CLO - SCP 0xFACE (0x0E90FACE)
          TAG = 256 cycles
                    │
          ┌────────┼────────┐
          ▼        ▼        ▼
        Slave0   Slave1   Slave2
        pool等待  pool等待  pool等待
        (L-d0)   (L-d1)   (L-d2) cycles
          │        │        │
          ▼        ▼        ▼
        ████ 同一时钟周期执行 ████
```

---

## 设计要点总结

1. **数据帧用于通知（slave→master）**：不需要精确时序，TAG 作为 slave
   唯一标识索引 master 的 scratchpad memory。

2. **指令帧用于触发（master→slaves）**：广播指令帧携带 2 条机器码直接
   注入所有 slave 的 RT-Core，TAG 延迟补偿机制保证 cycle-accurate 同步。

3. **TGM 先行 + SCP.MEM 回查**：消除 Phase 2 收集逻辑中的所有竞态窗口。
   TGM 捕获实时到达的帧，SCP.MEM 回查捕获历史到达的帧，两者互补。

4. **RSM 写入的 "clear all pending" 副作用**：每轮 RSM 写入自然清除上一
   轮残留的 stale pending request，不需要额外处理。

5. **NEX.ADR\[31\]=1**：master 只转发广播帧不自己消费，避免注入指令
   干扰 master 的执行流。

6. **CDM/COD 配对**：所有 slave 预设相同的 CDM 监控码，master 广播的
   指令帧统一写入匹配 COD 值，触发 resume。比直接写 RSM 更安全
   （不触发 RSM 的 "clear all pending" 副作用）。

7. **TAG 延迟值宁大勿小**：偏大只增加延迟（μs 级可忽略），偏小会导致
   部分 slave 的指令帧剩余延迟为负从而立即执行，破坏同步。
