# RTMQ 和 OASM 参考

## RTMQ 硬件平台

### 基本信息
- **架构**: 32 位 SoC 框架
- **目标应用**: 量子实验控制
- **时序精度**: 纳秒级（250 MHz = 4ns/周期）
- **设计哲学**: 计算即时序，程序具有明确的时序定义

### 地址空间

#### CSR (Control-Status Register)
- **大小**: 8 位地址空间（最多 256 个寄存器）
- **用途**: RT-Core 与外设之间的接口
- **类型**:
  - Numeric CSR: 数值寄存器，支持自增
  - Flag CSR: 标志寄存器，支持自动重载
  - CSR Subfile: 子文件寄存器，扩展地址空间

#### TCS (Tightly-Coupled Stack)
- **类似**: 窗口化的 GPR
- **可直接访问**: `$00-$1F` (32 个 GPR)
  - `$00`: 固定为 `0x00000000`
  - `$01`: 固定为 `0xFFFFFFFF`
- **栈相对访问**: `$20-$FF` (通过 STK CSR 偏移)

### 指令类型

#### Type-C (I/O 操作)
- 访问 CSR 寄存器
- 语法: `<opcode> - <csr_name> <mask> <value>`
- 示例: `AMK - TTL 1.0 $01` (设置 TTL 位 0)

#### Type-A (算术逻辑)
- 访问 TCS 栈
- 语法: `<opcode> <dst> <src1> <src2>`
- 示例: `ADD $02 $03 $04` (TCS[$02] = TCS[$03] + TCS[$04])

### 关键指令

| 指令 | 类型 | 功能 | 周期成本 |
|-----|------|------|---------|
| AMK | Type-C | 掩码操作（AND-MASK-OR） | 1 |
| SFS | Type-C | 子文件选择 | 1 |
| CHI/CLO | Type-C | Timer 高/低位设置 | 1 |
| NOP | Type-A | 空操作 | 1 |
| NOP H | - | 暂停等待恢复信号 | 可变 |

## OASM DSL 抽象

### 核心库
- `oasm.rtmq2`: RTMQ2 基础指令
- `oasm.dev.rwg`: RWG 专用函数

### CatSeq OASM 函数

#### TTL 控制
```python
def ttl_config(mask, dir):
    """TTL 初始化和方向配置"""
    rtmq_mask = binary_to_rtmq_mask(mask)
    dir_reg = '$00' if dir == 0 else '$01'
    sfs('dio', 'dir')
    amk('dio', rtmq_mask, dir_reg)

def ttl_set(mask, state, board_type="main"):
    """TTL 状态设置"""
    rtmq_mask = binary_to_rtmq_mask(mask)
    rtmq_state = binary_to_rtmq_mask(state)
    amk('ttl', rtmq_mask, rtmq_state)
```

#### 时序控制
```python
def wait_mu(cycles):
    """等待指定机器周期"""
    if cycles <= 4:
        nop(cycles)  # 短延迟优化
    else:
        wait(cycles)  # Timer 机制

def wait_us(duration):
    """等待指定微秒数"""
    cycles = round(duration * 250)
    wait_mu(cycles)
```

**wait() 时序分析**:
```
wait(128) 生成:
  Cycle 1: CHI-TIM (timer=0)
  Cycle 2: CLO-TIM 0x7F (timer=127, 启动倒计数)
  Cycle 3: AMK-EXC (timer=126)
  Cycle 4: AMK-RSM (timer=125)
  Cycle 5+: NOP H 暂停，timer 倒计数 125→0
  总计: 4 + 124 = 128 cycles ✓
```

#### 同步控制
```python
def wait_master(cod=None):
    """等待主机触发信号"""
    wait_rtlk_trig('c', cod or id(asm.intf))

def trig_slave(wait_time, cod=None):
    """触发从机同步"""
    wait(wait_time)
    send_trig_code('ib', 0, 0, cod or id(asm.intf))
```

#### RWG 控制
```python
def rwg_init(sca=(0,0,0,0), mux=(32,32,32,32)):
    """RWG 板卡初始化"""
    rwg.rsm.on(spi=1)
    rwg.pdm.source(1, 1, 1, 1)
    rwg.cds.mux(sca, [((1<<mux[i])-1)<<sum(mux[:i]) for i in range(4)])
    rwg.rst_cic(0xF)

def rwg_set_carrier(chn: int, carrier_mhz: float):
    """设置 RWG 载波频率"""
    rwg.carrier(1<<chn, carrier_mhz, upd=True)

def rwg_rf_switch(ch_mask: int, state_mask: int):
    """RF 开关控制
    
    Args:
        ch_mask: 通道掩码 (0b0101 = RF0 和 RF2)
        state_mask: 状态掩码 (0 = RF 使能, 1 = RF 禁用)
    """
    for rf_port in range(4):
        if ch_mask & (1 << rf_port):
            rf_state = 1 if (state_mask & (1 << rf_port)) else 0
            rtmq_mask = f"7.{rf_port * 2}"
            rtmq_value = f"{rf_state}.{rf_port * 2}"
            amk('PDM', rtmq_mask, rtmq_value)

def rwg_load_waveform(params: WaveformParams):
    """加载波形参数"""
    pha_rld: int = 1 if params.phase_reset else 0
    fte.cfg(params.sbg_id, 0, 0, pha_rld=pha_rld)
    rwg.frq(None, params.freq_coeffs, params.initial_phase)
    rwg.amp(None, params.amp_coeffs)

def rwg_play(pud_mask: int, iou_mask: int):
    """触发波形播放"""
    sbg.ctrl(iou=0, pud=pud_mask, mrk=0)
```

## 硬件模块

### Main 板卡
- **功能**: GPIO 和系统协调
- **TTL 通道**: 通过 GPIO 子系统控制
- **寄存器**: `TTL`, `DIO`

### RWG 板卡
- **功能**: RF 波形生成
- **通道数**: 4 个 RF 输出（0.1-400 MHz）
- **采样率**: 1 GSps
- **特性**: 多音调合成、频率/幅度斜坡、相位重置
- **关键寄存器**:
  - `PDM`: 功率控制和 RF 开关
  - `CDS`: 码流选择和复用
  - `FTE`: SBG 配置
  - `SBG`: 播放控制（IOU, PUD, MRK）

### RSP 板卡（未完全支持）
- **功能**: 可重构信号处理
- **特性**: DSP 工具箱、模拟 I/O、RF 输出

## 位掩码转换

### Binary to RTMQ Mask
```python
def binary_to_rtmq_mask(binary_mask: int) -> str:
    """
    0b0001 → "1.0"  (位 0)
    0b0010 → "1.1"  (位 1)
    0b0011 → "3.0"  (位 0-1)
    0b1111 → "F.0"  (位 0-3)
    """
    if binary_mask == 0:
        return "0.0"
    
    # 找到最高位和最低位
    lsb = (binary_mask & -binary_mask).bit_length() - 1
    msb = binary_mask.bit_length() - 1
    
    # 计算宽度和偏移
    width = msb - lsb + 1
    offset = lsb
    
    # 生成掩码值
    mask_value = (1 << width) - 1
    return f"{mask_value:X}.{offset}"
```

## RTMQ 汇编示例

### TTL Pulse (10μs)
```asm
# 初始化
SFS - DIO DIR
AMK - DIO 1.0 $00          # 设置通道 0 为输出

# 打开 TTL
AMK - TTL 1.0 $01          # TTL[0] = 1

# 等待 10μs = 2500 cycles
CHI - TIM 0x000_00000
CLO - TIM 0x000_009C3      # 2500 - 1 = 0x9C3
AMK - EXC 2.0 $01
AMK - RSM 1.1 $01
NOP H

# 关闭 TTL
AMK - TTL 1.0 $00          # TTL[0] = 0
```

### 双通道并行 TTL
```asm
# 同时开启通道 0 和 1
AMK - TTL 3.0 $01          # mask=0b11, state=0b11

# 等待...

# 同时关闭
AMK - TTL 3.0 $00          # mask=0b11, state=0b00
```

## 时序约束

### Timer 开销
- `wait(N)` 总周期 = N（OASM 已处理开销）
- Timer 设置: 2 个周期（CHI + CLO）
- 恢复配置: 2 个周期（AMK-EXC + AMK-RSM）
- NOP H: 剩余等待时间

### 指令执行时序
- 大多数指令: 1 个周期
- 跨板卡通信: 多个周期（取决于 RTLink 延迟）

## 参考文档

CatSeq 使用的 RTMQ skill 提供以下参考文档：
- `isa.md` - ISA 和汇编生成
- `qctrl_master.md` - Master 模块 CSR
- `qctrl_rwg.md` - RWG 模块 CSR
- `qctrl_rsp.md` - RSP 模块 CSR
- `rtlink.md` - RTLink 网络协议
- `devguide.md` - SoC 开发指南

## 调试技巧

### 查看生成的汇编
```python
from oasm.dev import sequence
seq = sequence('rwg0')
# ... 调用 OASM 函数 ...
print(seq.asm)  # 查看生成的汇编代码
```

### 验证时序
使用 OASM 的时序分析工具验证实际执行时间与预期是否一致。

### 硬件仿真
如果可能，使用 RTMQ 仿真器验证编译结果再部署到硬件。
