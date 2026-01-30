# Plan: 使用 pliron 为 v2 Arena 编写 MLIR 编译器 Pass

## 目标

在 `catseq-rust` crate 中引入 pliron，将 v2 的两个 Arena（Morphism Arena + Program Arena）转换为 MLIR IR，经过三层 dialect lowering 最终生成 RTMQ 汇编。

## 三层 Dialect 架构

```
Morphism Arena (arena.rs)  ──┐
                              ├─→ catseq dialect ──→ qctrl dialect ──→ rtmq dialect
Program Arena (program/)   ──┘
      (arena 结构)            (板卡级指令流)        (RTMQ ISA 指令)
```

### Layer 1: catseq dialect — Arena 结构映射

直接映射 Arena 中的数据结构:

**Morphism ops:**
- `catseq.atomic` { channel_id: u32, duration: u64, opcode: u16, data: bytes }
- `catseq.sequential` { region: [lhs, rhs] }
- `catseq.parallel` { region: [lhs, rhs] }

**Program ops:**
- `catseq.lift` { morphism_ref: u64, params }
- `catseq.chain` { left, right }
- `catseq.loop` { count: Value, body: region }
- `catseq.match` { subject: Value, cases: region[], default: region? }
- `catseq.delay` { duration: Value, max_hint? }
- `catseq.set` { target: Value, value: Value }
- `catseq.measure` { target: Value, source: u32 }
- `catseq.func_def` { name, params, body: region }
- `catseq.apply` { func, args }
- `catseq.identity`

**Value ops:**
- `catseq.literal`, `catseq.variable`, `catseq.binary_expr`, `catseq.unary_expr`, `catseq.condition`, `catseq.logical_expr`

### Layer 2: qctrl dialect — 板卡级指令流

对应 `catseq/compilation/functions.py` 中的 OASM DSL 函数。每个 op 代表一个高层硬件操作:

- `qctrl.board_sequence` { board_id } — region 容器，单板卡指令序列
- `qctrl.ttl_config` { mask: int, dir: int }
- `qctrl.ttl_set` { mask: int, state: int, board_type: str }
- `qctrl.wait_mu` { cycles: int }
- `qctrl.rwg_init` { sca, mux }
- `qctrl.rwg_set_carrier` { channel: int, freq_mhz: f64 }
- `qctrl.rwg_rf_switch` { ch_mask: int, state_mask: int }
- `qctrl.rwg_load_waveform` { sbg_id, freq_coeffs, amp_coeffs, ... }
- `qctrl.rwg_play` { pud_mask: int, iou_mask: int }
- `qctrl.sync_master` { wait_time, code }
- `qctrl.sync_slave` { code }

### Layer 3: rtmq dialect — RTMQ ISA 指令

1:1 映射 RTMQ 汇编指令（参考 isa.md）:

**Type-C (CSR I/O):**
- `rtmq.chi` { rd: CSR, imm: u32 } — 加载 CSR 高 12 位
- `rtmq.clo` { rd: CSR, imm: u32, flag: Flag } — 加载 CSR 低 20 位
- `rtmq.amk` { rd: CSR, r0: Operand, r1: Operand, flag: Flag } — 掩码赋值
- `rtmq.sfs` { sf: CSR, csr: CSR } — 子文件选择
- `rtmq.nop` { flag: Flag } — 空操作

**Type-A (TCS ALU):**
- `rtmq.add`, `rtmq.sub`, `rtmq.and`, `rtmq.bor`, `rtmq.xor`, etc.
- `rtmq.ghi`, `rtmq.glo` — TCS 立即数加载
- `rtmq.opl`, `rtmq.plo`, `rtmq.phi`, `rtmq.div`, `rtmq.mod` — 乘除
- `rtmq.csr_read` — CSR 读取到 TCS
- 比较: `rtmq.equ`, `rtmq.neq`, `rtmq.lst`, `rtmq.lse`
- 移位: `rtmq.shl`, `rtmq.shr`, `rtmq.sar`, `rtmq.rol`

## Lowering Passes

### Pass 1: catseq → qctrl (Flatten + Board Group + OpCode Interpret)

1. 展平 Sequential/Parallel 树为带时间戳的事件列表（复用现有 `compile()` 逻辑）
2. 按 channel_id 高 16 位分组到 `qctrl.board_sequence`
3. 解释 opcode 语义：TTL_ON → `qctrl.ttl_set(mask, state=1)`，RWG_SET_CARRIER → `qctrl.rwg_set_carrier` 等
4. **合并同时刻同板卡的同类操作**（TTL 位掩码合并）：
   - 同时刻 `ttl_set(0x01, 0x01)` + `ttl_set(0x02, 0x02)` → `ttl_set(0x03, 0x03)`
5. 在事件间插入 `qctrl.wait_mu(delta_cycles)`
6. Program 节点: `catseq.loop` → `qctrl.*` with hardware loop pattern, `catseq.match` → branch pattern

### Pass 2: qctrl → rtmq (指令选择)

每个 qctrl op 展开为 RTMQ 指令序列:

- `qctrl.ttl_config(mask, dir)` → `sfs('dio','dir')` + `amk('dio', mask, dir)`
- `qctrl.ttl_set(mask, state)` → `rtmq.amk { rd: TTL, r0: mask_xp, r1: state_xp }`
- `qctrl.wait_mu(N)`:
  - N ≤ 4 → `rtmq.nop` × N
  - N > 4 → `rtmq.chi{TIM, 0}` + `rtmq.clo{TIM, N-1}` + `rtmq.amk{EXC, ...}` + `rtmq.amk{RSM, ...}` + `rtmq.nop{H}`
- `qctrl.rwg_set_carrier(ch, freq)` → rwg CSR 操作序列
- `qctrl.rwg_play(pud, iou)` → `rtmq.amk` on SBG CSR

### 值系统 (mask 格式转换)

需要 `binary_to_rtmq_xp(mask: u32) -> (u8, u8)` 将二进制掩码转为 RTMQ `X.P` 格式（参考 `mask_utils.py`）。

## 实现步骤

### Step 1: 添加 pliron 依赖
**File**: `catseq-rust/Cargo.toml`
```toml
pliron = "0.13"
pliron-derive = "0.13"
```

### Step 2: 定义 catseq dialect
**File**: `catseq-rust/src/mlir/catseq_dialect.rs` (新建)

### Step 3: 定义 qctrl dialect
**File**: `catseq-rust/src/mlir/qctrl_dialect.rs` (新建)

### Step 4: 定义 rtmq dialect
**File**: `catseq-rust/src/mlir/rtmq_dialect.rs` (新建)

### Step 5: Arena → catseq IR 导入
**File**: `catseq-rust/src/mlir/import.rs` (新建)
- `fn import_morphism(ctx, arena, root) -> Operation`
- `fn import_program(ctx, program_arena, root) -> Operation`

### Step 6: catseq → qctrl lowering pass
**File**: `catseq-rust/src/mlir/passes/lower_catseq.rs` (新建)

### Step 7: qctrl → rtmq lowering pass
**File**: `catseq-rust/src/mlir/passes/lower_qctrl.rs` (新建)

### Step 8: PyO3 接口
**File**: `catseq-rust/src/lib.rs` (修改)
- `compile_to_mlir(node_id, level) -> String` — 返回指定层级的 MLIR 文本
- `compile_to_rtmq_asm(node_id) -> Dict[board_id, String]` — 完整编译到汇编文本

### 文件结构
```
catseq-rust/src/
├── mlir/
│   ├── mod.rs
│   ├── catseq_dialect.rs    # catseq dialect (arena 映射)
│   ├── qctrl_dialect.rs     # qctrl dialect (板卡指令流)
│   ├── rtmq_dialect.rs      # rtmq dialect (ISA 指令)
│   ├── import.rs            # Arena → catseq IR
│   ├── mask_utils.rs        # binary_to_rtmq_xp 等工具
│   └── passes/
│       ├── mod.rs
│       ├── lower_catseq.rs  # catseq → qctrl (含合并优化)
│       └── lower_qctrl.rs   # qctrl → rtmq (指令选择)
├── arena.rs                 # (existing)
├── compiler.rs              # (existing, 保持兼容)
├── program/                 # (existing)
└── lib.rs                   # (modify: add mlir mod + PyO3)
```

## 验证

1. `cargo test` — 所有现有测试通过
2. 新增单元测试:
   - catseq IR 导入: Arena 树正确映射为 ops
   - catseq → qctrl: 时间戳正确、TTL 掩码合并正确
   - qctrl → rtmq: 指令序列与 `functions.py` 生成的 OASM 一致
   - 端到端: Arena → rtmq → 汇编文本，验证 TTL pulse 示例
3. 与现有 `compile()` 函数输出做对比验证
4. `maturin develop` 后 Python 端 `compile_to_mlir()` 验证

## 关键参考文件

- `catseq-rust/src/arena.rs` — Morphism Arena 定义
- `catseq-rust/src/program/` — Program Arena 定义
- `catseq-rust/src/compiler.rs` — 现有编译器（flatten 逻辑参考）
- `catseq/compilation/functions.py` — qctrl 层语义参考
- `catseq/compilation/mask_utils.py` — 掩码转换参考
- `catseq/v2/opcodes.py` — OpCode 定义
- RTMQ skill `references/isa.md` — RTMQ 指令集参考
