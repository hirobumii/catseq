# RTMQv2 Reference \#4 - Developing SoC in RTMQ Framework

by Zhang Junhua

Rev.0.4 - 2025.02.27

## Introduction

In *RTMQv2 Reference \#3 - Standard Coherent Node*, a functional description of the StdCohNode is given. So this reference is focused on the ports and timing of the interface modules in the library. The RTL implementation of the StdCohNode is designed to be self-contained and highly decoupled. There are just 4 modules that are exposed as interfaces:

- `RTMQ_StdCohNode`: the all-in-one wrapper, with the RT-Core, the caches and the RTLink nexus inside
- `RTMQ_CSR_Flag`: the flag CSR module
- `RTMQ_CSR_Num`: the numeric CSR module
- `RTMQ_CSR_Subfile`: the CSR subfile module

## CSR Modules

### `RTMQ_CSR_Flag`

#### Parameters

| Name    | Width | Function |
|:-------:|:-----:|:---------|
| `ADDR`  |   8   | address of the CSR |
| `F_RLD` |  32   | auto-reload flag for each bit, 1 for auto-reload |
| `D_RLD` |  32   | power-up / reload state for each bit |

#### Ports

| Name       | Dir | Width   | Function | Comment |
|:----------:|:---:|:-------:|:---------|:--------|
| `clk`      | IN  |    1    | system clock |     |
| `sys_rstn` | IN  |    1    | global async. reset | active low |
| `csr_ctl`  | IN  | `B_CCB` | CSR control bus |  |
| `acs_prt`  | IN  |    1    | access protect  | 1 for prohibiting write as well as read side effect |
| `reg_dat`  | OUT | `W_REG` | CSR written value output | |
| `trg_rd`   | OUT |    1    | CSR read trigger | 1-cycle positive pulse |
| `trg_wr`   | OUT |    1    | CSR write trigger | 1-cycle positive pulse |

#### Timing Diagrams

- CSR Write

```RTMQ
CHI - LED 0xBADCAFEE
CLO - LED 0xBADCAFEE
AMK - LED F.6 0.6
```

```wavedrom
{ signal: [
  { name: "clk"    , wave: "P...." },
  { name: "reg_dat", wave: "x===.", data: ["0xBADxxxxx", "0xBADCAFEE", "0xBADC0FEE"] },
  { name: "trg_wr" , wave: "0.1.0" }
  ],
  config: { hscale: 3, skin:"dark" }
}
```

</br>

- CSR Read

```RTMQ
AMK - AUX $01 LED
```

```wavedrom
{ signal: [
  { name: "clk"    , wave: "P.." },
  ["LED",
    { name: "reg_dat", wave: "=..", data: ["0xBADC0FEE"] },
    { name: "trg_rd" , wave: "010" }
  ],
  ["AUX",
    { name: "reg_dat", wave: "x=.", data: ["0xBADC0FEE"] },
    { name: "trg_wr" , wave: "010" }
  ],
  ],
  config: { hscale: 3 }
}
```

</br>

- Reset and CSR Write with Auto-Reload

Suppose the CSR `FLG` is instantiated as follows:

```verilog
RTMQ_CSR_Flag #(.ADDR(R_FLG), .F_RLD(32'h0000FFFF), .D_RLD(32'h0000ABCD)) iFLG(...);
```

That is, the 16 LSBs have auto-reload feature enabled. If it is written with:

```RTMQ
CHI - FLG 0x12345678
CLO - FLG 0x12345678
```

```wavedrom
{ signal: [
  { name: "clk"     , wave: "P..|..." },
  { name: "sys_rstn", wave: "101|...", phase: 0.5 },  
  { name: "reg_dat" , wave: "x=.|===", data: ["0x0000ABCD", "0x1230ABCD", "0x12345678", "0x1234ABCD"] },
  { name: "trg_wr"  , wave: "x0.|.10" }
  ],
  config: { hscale: 3 }
}
```

</br>

### `RTMQ_CSR_Num`

#### Parameters

| Name    | Width | Function |
|:-------:|:-----:|:---------|
| `ADDR`  |   8   | address of the CSR |

#### Ports

| Name       | Dir | Width   | Function | Comment |
|:----------:|:---:|:-------:|:---------|:--------|
| `clk`      | IN  |    1    | system clock |     |
| `sys_rstn` | IN  |    1    | global async. reset | active low |
| `csr_ctl`  | IN  | `B_CCB` | CSR control bus |  |
| `acs_prt`  | IN  |    1    | access protect  | 1 for prohibiting write as well as read side effect |
| `reg_dat`  | OUT | `W_REG` | CSR written value output | |
| `trg_rd`   | OUT |    1    | CSR read trigger | 1-cycle positive pulse |
| `trg_wr`   | OUT |    1    | CSR write trigger | 1-cycle positive pulse |

#### Timing Diagrams

- Self-Increment

```RTMQ
CHI - DAT 0x76543210
CLO - DAT 0x76543210
AMK - DAT 3.0 0x24     % DAT += 0x24
```

```wavedrom
{ signal: [
  { name: "clk"    , wave: "P...." },
  { name: "reg_dat", wave: "x===.", data: ["0x765xxxxx", "0x76543210", "0x76543234"] },
  { name: "trg_wr" , wave: "0.1.0" }
  ],
  config: { hscale: 3 }
}
```

</br>

### `RTMQ_CSR_Subfile`

#### Parameters

| Name      | Width | Function |
|:---------:|:-----:|:---------|
| `ADDR_RW` |   8   | read/write address of the subfile |
| `ADDR_SL` |   8   | SFS address of the subfile |
| `N_CSR`   |  32   | number of CSRs in the subfile, 2 <= N_CSR <= 256 |

#### Ports

| Name       | Dir | Width         | Function | Comment |
|:----------:|:---:|:-------------:|:---------|:--------|
| `clk`      | IN  |       1       | system clock |     |
| `sys_rstn` | IN  |       1       | global async. reset | active low |
| `csr_ctl`  | IN  |    `B_CCB`    | CSR control bus |  |
| `acs_prt`  | IN  |    `N_CSR`    | access protect for each CSR | 1 for prohibiting write as well as read side effect |
| `reg_dat`  | OUT |    `W_REG`    | selected CSR read value output | multiplexed from `sf_in` |
| `trg_rd`   | OUT |    `N_CSR`    | CSR read trigger, each bit for 1 CSR in the subfile | 1-cycle positive pulse |
| `trg_wr`   | OUT |    `N_CSR`    | CSR write trigger, each bit for 1 CSR in the subfile | 1-cycle positive pulse |
| `sf_in`    | IN  | `W_REG*N_CSR` | collective read value input of the CSRs | LSBs correspond to CSR with smaller address |
| `sf_out`   | OUT | `W_REG*N_CSR` | collective written value output of the CSRs |  LSBs correspond to CSR with smaller address |

#### Timing Diagrams

- Select and Write

```RTMQ
SFS - DAT &00
CHI - DAT 0xBAADF00D
CLO - DAT 0xBAADF00D
SFS - DAT &01
AMK - DAT $01 $03     % suppose $03 = 0x12344321
```

```wavedrom
{ signal: [
  { name: "clk"          , wave: "P....." },
  { name: "trg_wr[0]"    , wave: "0.10.." },
  { name: "trg_wr[1]"    , wave: "0...10" },
  { name: "sf_out[31:0]" , wave: "x==...", data: ["0xBAAxxxxx", "0xBAADF00D"] },
  { name: "sf_out[63:32]", wave: "x...=.", data: ["0x123442321"] }
  ],
  config: { hscale: 3 }
}
```

</br>

- Select and Read

```RTMQ
% suppose sf_in = {32'h12344321, 32'hBAADF00D}
SFS - DAT &01
NOP P           % pause for 7 cycles, but actually only 5 are required
CSR - $03 DAT   % $03 = 0x12344321
```

```wavedrom
{ signal: [
  { name: "clk"      , wave: "P...." },
  { name: "reg_dat"  , wave: "x=...", data: ["0x12344321"] },
  { name: "trg_rd[0]", wave: "0...." },
  { name: "trg_rd[1]", wave: "0..10" },
  { name: "trg_rd[2]", wave: "0...." },
  { name: "sf_in"    , wave: "=....", data: ["0x12344321_BAADF00D"] }
  ],
  config: { hscale: 3 }
}
```

</br>

## `RTMQ_StdCohNode` Module

### Parameters

Definitions of most of the parameters for the StdCohNode are in `RTMQDef_Node.vh`. The only exposed parameter is `ICH_INIT`, which is the path and name of the memory initialization file for the instruction cache.

### RT-Core Ports

These ports are the interface between the RT-Core and the peripherals.

| Name       | Dir | Width       | Function | Comment |
|:----------:|:---:|:-----------:|:---------|:--------|
| `clk`      | IN  |      1      | system clock |     |
| `sys_rstn` | IN  |      1      | global async. reset | active low |
| `csr_ctl`  | OUT |   `B_CCB`   | CSR control bus | connect this port directly to other CSR modules' `csr_ctl` inputs |
| `csr_dat`  | IN  |   `B_CDB`   | CSR data bus | collective read value input of the CSRs |
| `rsm_chn`  | IN  |   `W_REG`   | resume request input | active high |
| `exc_chn`  | IN  |   `W_REG`   | exception indicator input | active high |
| `halt`     | IN  |      1      | hardware halt request | should be 1-cycle positive pulse |
| `std_csr`  | OUT | `B_STD_CSR` | collective read value output of the CSRs internal to the StdCohNode | loop it back to the LSBs of `csr_dat` |
| `std_rsm`  | OUT | `N_STD_RSM` | resume request channels internal to the StdCohNode | loop it back to the LSBs of `rsm_chn` |
| `std_exc`  | OUT | `N_STD_EXC` | exception indicators internal to the StdCohNode | loop it back to the LSBs of `exc_chn` |

### DMA Ports for Caches

These ports are the interface to the secondary port of the caches, such that they can be filled or dumped by other modules like a SDRAM controller or a co-processor.

| Name       | Dir | Width     | Function | Comment |
|:----------:|:---:|:---------:|:---------|:--------|
| `ich_adr`  | IN  |  `W_ICH`  | address for the instruction cache | |
| `ich_wen`  | IN  |     1     | write enable for the instruction cache | active high |
| `ich_din`  | IN  |  `W_REG`  | write data input for the instruction cache | |
| `ich_dou`  | OUT |  `W_REG`  | read data output for the instruction cache | |
| `dch_adr`  | IN  | `W_DCH-2` | address for the data cache | DMA port of the data cache is addressed in words |
| `dch_wen`  | IN  |     1     | write enable for the data cache | active high |
| `dch_din`  | IN  |  `W_REG`  | write data input for the data cache | |
| `dch_dou`  | OUT |  `W_REG`  | read data output for the data cache | |
| `dch_sti`  | IN  |  `W_REG`  | data streaming input | |
| `dch_sto`  | OUT |  `W_REG`  | replica of CSR `DCD`, for data streaming output | |


#### Timing Diagrams

- Instruction cache write

Suppose that `CSR:ICF[31] == 1`, that is, the DMA port is enabled.

Write latency: 2 cycles

```wavedrom
{ signal: [
  { name: "clk"              , wave: "P...." },
  { name: "ich_adr"          , wave: "x==x.", data: ["0x1234", "0x5678"] },
  { name: "ich_wen"          , wave: "01.0." },
  { name: "ich_din"          , wave: "x==x.", data: ["0xDEADBEEF", "0xCAFEBEAD"] },
  { name: "ins_cache[0x1234]", wave: "x..=.", data: ["0xDEADBEEF"] },
  { name: "ins_cache[0x5678]", wave: "x...=", data: ["0xCAFEBEAD"] }
  ],
  config: { hscale: 3 }
}
```

</br>

- Instruction cache read

Read latency: 4 cycles

```wavedrom
{ signal: [
  { name: "clk"              , wave: "P......." },
  { name: "ich_adr"          , wave: "x==x....", data: ["0x1122", "0x3344"] },
  { name: "ins_cache[0x1122]", wave: "=.......", data: ["0xDEADBEEF"] },
  { name: "ins_cache[0x3344]", wave: "=.......", data: ["0xF000BAAA"] },
  { name: "ich_dou"          , wave: "x....==x", data: ["0xDEADBEEF", "0xF000BAAA"] },
  ],
  config: { hscale: 3 }
}
```

</br>

- Data cache write

Write latency: 1 cycles.

```wavedrom
{ signal: [
  { name: "clk"              , wave: "P..." },
  { name: "dch_adr"          , wave: "x==x", data: ["0x1414", "0x1732"] },
  { name: "dch_wen"          , wave: "01.0" },
  { name: "dch_din"          , wave: "x==x", data: ["0x14142136", "0x17320508"] },
  { name: "dat_cache[0x1414]", wave: "x.=.", data: ["0x14142136"] },
  { name: "dat_cache[0x1732]", wave: "x..=", data: ["0x17320508"] }
  ],
  config: { hscale: 3 }
}
```

</br>

- Data cache read

Read latency: 2 cycles

```wavedrom
{ signal: [
  { name: "clk"              , wave: "P....." },
  { name: "dch_adr"          , wave: "x==x..", data: ["0x2718", "0x3141"] },
  { name: "dat_cache[0x2718]", wave: "=.....", data: ["0x27182818"] },
  { name: "dat_cache[0x3141]", wave: "=.....", data: ["0x31415926"] },
  { name: "dch_dou"          , wave: "x..==x", data: ["0x27182818", "0x31415926"] },
  ],
  config: { hscale: 3 }
}
```

</br>

### RTLink Ports

These ports are the interface to the Nexus of RTLink. For each local channel, there shall be a corresponding PHY module to handle the consumption and generation of RTLink frames. Similarly for remote channels, there shall be PHY modules that serve as the interface between the Nexus and the physical media of the channels. Note that the *tx* and *rx* below is relative to the Nexus.

| Name         | Dir | Width       | Function | Comment |
|:------------:|:---:|:-----------:|:---------|:--------|
| `loc_tx_rdy` | OUT | `N_USR_LOC` | local channel Tx frame (to be consumed by PHY) ready flag | active high |
| `loc_tx_ack` | IN  | `N_USR_LOC` | local channel Tx frame acknowledged | from PHY to Nexus, 1-cycle positive pulse |
| `loc_tx_frm` | OUT | `B_LOC_TRF` | local channel Tx frame data | collective output, LSBs correspond to smaller channel number |
| `loc_rx_rdy` | IN  | `N_USR_LOC` | local channel Rx frame (generated from PHY) ready flag | 1-cycle positive pulse |
| `loc_rx_frm` | IN  | `B_LOC_TRF` | local channel Rx frame data | collective input, LSBs correspond to smaller channel number |
| `rmt_tx_rdy` | OUT | `N_CHN_RMT` | remote channel Tx frame (to be sent to the neighbor) ready flag | active high |
| `rmt_tx_ack` | IN  | `N_CHN_RMT` | remote channel Tx frame acknowledged | from PHY to Nexus, 1-cycle positive pulse |
| `rmt_tx_frm` | OUT | `B_RMT_TRF` | remote channel Tx frame data | collective output, LSBs correspond to smaller channel number |
| `rmt_rx_rdy` | IN  | `N_CHN_RMT` | local channel Rx frame (received from the neighbor) ready flag | 1-cycle positive pulse |
| `rmt_rx_frm` | IN  | `B_RMT_TRF` | local channel Rx frame data | collective input, LSBs correspond to smaller channel number |
| `guid`       | IN  |   `W_REG`   | global unique ID of the StdCohNode | used in the reply of echo data frame |

#### Timing Diagrams

- Local channel frame consumption
  - Each asserted bit of `loc_tx_rdy` indicates that its corresponding channel has a frame waiting to be consumed (i.e. a segment of `loc_tx_frm` is valid).
  - The PHY shall acknowledge with a 1-cycle positive pulse.
  - The latency between the acknowledgement and the actual consumption of the frame shall be deterministic, that is, there shall be no FIFO or buffer of similar kind.
  - The frame data from `loc_tx_frm` shall only be registered in the same clock cycle as the assertion of `loc_tx_ack`.
  - `loc_tx_ack` and `loc_tx_rdy` can be in the same clock cycle, that is, from `loc_tx_rdy` to `loc_tx_ack` can be combinatorial.

```wavedrom
{ signal: [
  { name: "clk"               , wave: "P...|....." },
  { name: "loc_tx_rdy[2]"     , wave: "010.|1.0.." },
  { name: "loc_tx_ack[2]"     , wave: "010.|.10.." },
  { name: "loc_tx_frm[Ch#2]"  , wave: "x=x.|=.x..", data: ["Frm.0", "Frm.1"] },
  { name: "(frame_buffer)"      , wave: "x.=.|..=..", data: ["Frm.0                                         ", "Frm.1"] },
  { name: "(consumption logic)", wave: "=..=|...=.", data: ["idle", "proc. Frm.0                   idle                                              ", "proc. Frm.1"] }
  ],
  config: { hscale: 2 }
}
```

</br>

- Local channel frame generation
  - Once a frame is generated in a local channel, its PHY module shall assert the corresponding bit in `loc_rx_rdy` for 1 clock cycle, and provide valid frame data in the corresponding segment of `loc_rx_frm` at the same time.
  - There are no dead time for Rx frame reception. Frames can be generated continuously, up to the limit of Rx FIFO capacity.

```wavedrom
{ signal: [
  { name: "clk"               , wave: "P......" },
  { name: "loc_rx_rdy[2]"     , wave: "010.1.0" },
  { name: "loc_rx_frm[Ch#2]"  , wave: "x=x.==x", data: ["Frm.0", "Frm.1", "Frm.2"] },
  { name: "(Rx FIFO #2)"      , wave: "=.==.==", data: ["idle", "Frm.0 rcvd.", "idle", "Frm.1 rcvd.", "Frm.2 rcvd."] }
  ],
  config: { hscale: 3 }
}
```

</br>

- Remote channel Tx frame transmission
  - Each asserted bit of `rmt_tx_rdy` indicates that its corresponding channel has a Tx frame waiting to be sent to the neighboring node (i.e. a segment of `rmt_tx_frm` is valid).
  - The PHY shall acknowledge with a 1-cycle positive pulse.
  - The latency between the acknowledgement and the actual transfer of the frame shall be deterministic, that is, there shall be no FIFO or buffer of similar kind.
  - The frame data from `rmt_tx_frm` shall only be registered in the same clock cycle as the assertion of `rmt_tx_ack`.
  - `rmt_tx_ack` and `rmt_tx_rdy` can be in the same clock cycle, that is, from `rmt_tx_rdy` to `rmt_tx_ack` can be combinatorial.

```wavedrom
{ signal: [
  { name: "clk"               , wave: "P...|....." },
  { name: "rmt_tx_rdy[2]"     , wave: "010.|1.0.." },
  { name: "rmt_tx_ack[2]"     , wave: "010.|.10.." },
  { name: "rmt_tx_frm[Ch#2]"  , wave: "x=x.|=.x..", data: ["Frm.0", "Frm.1"] },
  { name: "(frame_buffer)"      , wave: "x.=.|..=..", data: ["Frm.0                                         ", "Frm.1"] },
  { name: "(send logic)", wave: "=..=|...=.", data: ["idle", "send Frm.0                   idle                                              ", "send Frm.1"] }
  ],
  config: { hscale: 2 }
}
```

</br>

- Remote channel Rx frame reception
  - Once a frame is received from a remote channel, its PHY module shall assert the corresponding bit in `rmt_rx_rdy` for 1 clock cycle, and submit valid frame data in the corresponding segment of `rmt_rx_frm` at the same time.
  - There are no dead time for Rx frame reception. Frames can be submitted continuously, up to the limit of Rx FIFO capacity.

```wavedrom
{ signal: [
  { name: "clk"               , wave: "P......" },
  { name: "rmt_rx_rdy[2]"     , wave: "010.1.0" },
  { name: "rmt_rx_frm[Ch#2]"  , wave: "x=x.==x", data: ["Frm.0", "Frm.1", "Frm.2"] },
  { name: "(Rx FIFO #2)"      , wave: "=.==.==", data: ["idle", "Frm.0 rcvd.", "idle", "Frm.1 rcvd.", "Frm.2 rcvd."] }
  ],
  config: { hscale: 3 }
}
```

</br>

## Instantiation and Development Templates

### Instantiating `RTMQ_CSR_Flag`

```verilog
wire [W_REG-1 : 0] reg_dat;
wire acs_prt, trg_rd, trg_wr;
RTMQ_CSR_Flag #(.ADDR(   ), .F_RLD(32'h00000000), .D_RLD(32'h00000000))
  inst(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(acs_prt),
       .reg_dat(reg_dat), .trg_rd(trg_rd), .trg_wr(trg_wr));
```

### Instantiating `RTMQ_CSR_Num`

```verilog
wire [W_REG-1 : 0] reg_dat;
wire acs_prt, trg_rd, trg_wr;
RTMQ_CSR_Num #(.ADDR(   ))
  inst(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(acs_prt),
       .reg_dat(reg_dat), .trg_rd(trg_rd), .trg_wr(trg_wr));
```

### Instantiating `RTMQ_CSR_Subfile`

```verilog
wire [W_REG-1       : 0] reg_dat;
wire [N_CSR-1       : 0] acs_prt, trg_rd, trg_wr;
wire [W_REG*N_CSR-1 : 0] sf_in, sf_out;
RTMQ_CSR_Subfile #(.ADDR_RW(   ), .ADDR_SL(   ), .N_CSR(N_CSR))
  inst(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(acs_prt),
       .reg_dat(reg_dat), .trg_rd(trg_rd), .trg_wr(trg_wr),
       .sf_in(sf_in), .sf_out(sf_out));
```

### Instantiating `RTMQ_StdCohNode`

- Node instantiation

```verilog
wire [B_CCB-1     : 0] csr_ctl;
wire [B_CDB-1     : 0] csr_dat;
wire [W_REG-1     : 0] rsm_chn;
wire [W_REG-1     : 0] exc_chn;
wire                   halt;
wire [W_ICH-1     : 0] ich_adr;
wire                   ich_wen;
wire [W_REG-1     : 0] ich_din;
wire [W_REG-1     : 0] ich_dou;
wire [W_DCH-3     : 0] dch_adr;
wire                   dch_wen;
wire [W_REG-1     : 0] dch_din;
wire [W_REG-1     : 0] dch_dou;
wire [W_REG-1     : 0] dch_sti;
wire [W_REG-1     : 0] dch_sto;
wire [N_USR_LOC-1 : 0] loc_tx_rdy;
wire [N_USR_LOC-1 : 0] loc_tx_ack;
wire [B_LOC_TRF-1 : 0] loc_tx_frm;
wire [N_USR_LOC-1 : 0] loc_rx_rdy;
wire [B_LOC_TRF-1 : 0] loc_rx_frm;
wire [N_CHN_RMT-1 : 0] rmt_tx_rdy;
wire [N_CHN_RMT-1 : 0] rmt_tx_ack;
wire [B_RMT_TRF-1 : 0] rmt_tx_frm;
wire [N_CHN_RMT-1 : 0] rmt_rx_rdy;
wire [B_RMT_TRF-1 : 0] rmt_rx_frm;
wire [W_REG-1     : 0] guid;
wire [B_STD_CSR-1 : 0] std_csr;
wire [N_STD_RSM-1 : 0] std_rsm;
wire [N_STD_EXC-1 : 0] std_exc;
RTMQ_StdCohNode #("")
  iSTD(clk, sys_rstn, csr_ctl, csr_dat, rsm_chn, exc_chn, halt,
       ich_adr, ich_wen, ich_din, ich_dou,
       dch_adr, dch_wen, dch_din, dch_dou, dch_sti, dch_sto,
       loc_tx_rdy, loc_tx_ack, loc_tx_frm, loc_rx_rdy, loc_rx_frm,
       rmt_tx_rdy, rmt_tx_ack, rmt_tx_frm, rmt_rx_rdy, rmt_rx_frm,
       guid, std_csr, std_rsm, std_exc);
```

- RTLink connection

The signals from PHYs are concatenated as follows.

```verilog
// local channels
assign {..., loc_2_tx_rdy, loc_1_tx_rdy, loc_0_tx_rdy} = loc_tx_rdy;
assign loc_tx_ack = {..., loc_2_tx_ack, loc_1_tx_ack, loc_0_tx_ack};
assign {..., loc_2_tx_frm, loc_1_tx_frm, loc_0_tx_frm} = loc_tx_frm;
assign loc_rx_rdy = {..., loc_2_rx_rdy, loc_1_rx_rdy, loc_0_rx_rdy};
assign loc_rx_frm = {..., loc_2_rx_frm, loc_1_rx_frm, loc_0_rx_frm};

// remote channels
assign {..., rmt_2_tx_rdy, rmt_1_tx_rdy, rmt_0_tx_rdy} = rmt_tx_rdy;
assign rmt_tx_ack = {..., rmt_2_tx_ack, rmt_1_tx_ack, rmt_0_tx_ack};
assign {..., rmt_2_tx_frm, rmt_1_tx_frm, rmt_0_tx_frm} = rmt_tx_frm;
assign rmt_rx_rdy = {..., rmt_2_rx_rdy, rmt_1_rx_rdy, rmt_0_rx_rdy};
assign rmt_rx_frm = {..., rmt_2_rx_frm, rmt_1_rx_frm, rmt_0_rx_frm};
```

- CSR read value bus, resume request and exception indicator connection

The signals from peripherals are concatenated as follows. Note that the signals from inside StdCohNode (`std_csr`, `std_exc`, and `std_rsm`) shall also be put in the bus.

```verilog
assign csr_dat = {{N_MAX_CSR{D_NUL}},  // place-holder
  ...,
  reg_ext_2,
  reg_ext_1,   // other CSRs
  reg_ext_0,
  std_csr      // StdCohNode internal CSRs
};

assign exc_chn = {D_NUL, ..., exc_ext_2, exc_ext_1, exc_ext_0, std_exc};
assign rsm_chn = {D_NUL, ..., rsm_ext_2, rsm_ext_1, rsm_ext_0, std_rsm};
```

### Developing Peripherals

```verilog
module Peripheral(clk, sys_rstn, csr_ctl,        // global signals
                  reg_csr1, reg_csr2, reg_csr3,  // CSR read values
                  rsm_event1, rsm_event2,        // resume requests
                  exc_error1, exc_error2,        // exception indicators
                  in_1, in_2, in_3,              // peripheral logic input ports
                  out_1, out_2, out_3);          // peripheral logic output ports

parameter R_CSR1 = 0;                            // address of CSR1
parameter R_CSR2 = 0;                            // address of CSR2
parameter R_CSR3 = 0;                            // address of CSR3

parameter W_SIG = 0;                             // other related parameters
parameter PAR1 = 0;
parameter PAR2 = 0;

`include "RTMQDef_Core.vh"

// --- port declaration ---

input                clk;                        // system clock
input                sys_rstn;                   // global reset_n
input  [B_CCB-1 : 0] csr_ctl;                    // CSR control bus
output [W_REG-1 : 0] reg_csr1;                   // \
output [W_REG-1 : 0] reg_csr2;                   //  |-CSR read values
output [W_REG-1 : 0] reg_csr3;                   // /
output               rsm_event1;                 // resume requests
output               rsm_event2;
output               exc_error1;                 // exception indicators
output               exc_error2;
input  [W_SIG-1 : 0] in_1;                       // \
input  [W_SIG-1 : 0] in_2;                       //  |-peripheral logic input ports
input  [W_SIG-1 : 0] in_3;                       // /
output [W_SIG-1 : 0] out_1;                      // \
output [W_SIG-1 : 0] out_2;                      //  |-peripheral logic output ports
output [W_SIG-1 : 0] out_3;                      // /

// --- CSR instantiation ---

wire trg_rd_1, trg_wr_1;
RTMQ_CSR_Flag #(.ADDR(R_CSR1), .F_RLD(32'h00000000), .D_RLD(32'h00000000))
  iCSR1(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(1'b0),  // if no access protect is required
        // read value of CSR1 is the same as the written value
        .reg_dat(reg_csr1), .trg_rd(trg_rd_1), .trg_wr(trg_wr_1));

reg  [W_REG-1 : 0] reg_csr2;                     // read value of CSR2 is something else, to be assigned later
wire [W_REG-1 : 0] dat_csr2;                     // write value can be used in peripheral logic
wire               trg_rd_2, trg_wr_2;
RTMQ_CSR_Num #(.ADDR(R_CSR2))
  iCSR2(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(1'b0),
        .reg_dat(dat_csr2), .trg_rd(trg_rd_2), .trg_wr(trg_wr_2));

wire [W_REG-1 : 0] sf_in2, sf_in1, sf_in0;       // subfile CSR read values, from peripheral logic
wire [W_REG-1 : 0] sf_ou2, sf_ou1, sf_ou0;       // subfile CSR written values, to be used in peripheral logic
wire [ 2      : 0] trg_rd_3, trg_wr_3;
RTMQ_CSR_Subfile #(.ADDR_RW(R_CSR3), .ADDR_SL(R_CSR3), .N_CSR(3))
  iCSR3(.clk(clk), .sys_rstn(sys_rstn), .csr_ctl(csr_ctl), .acs_prt(3'b0),
        .reg_dat(reg_csr3), .trg_rd(trg_rd_3), .trg_wr(trg_wr_3),
        .sf_in({sf_in2, sf_in1, sf_in0}),
        .sf_out({sf_ou2, sf_ou1, sf_ou0}));

// --- peripheral logic implementation ---
// ......
// ......

endmodule
```

### Developing RTLink PHYs

```verilog
module RTLink_PHY_XXX(clk, sys_rstn,             // global signals
                      csr_ctl, reg_csr1,         // PHY may also contain CSRs
                      rsm_event1, exc_error1,    // resume requests and exception indicators
                      tx_rdy, tx_ack, tx_frm,    // RTLink Tx signals
                      rx_rdy, rx_frm,            // RTLink Rx signals
                      txd_out,                   // media-dependent Tx data output
                      rxd_in);                   // media-dependent Rx data input

parameter R_CSR1 = 0;                            // address of CSR1

parameter PAR1 = 0;                              // other related parameters
parameter PAR2 = 0;

`include "RTMQDef_Core.vh"
`include "RTMQDef_RTLink.vh"

// --- port declaration ---

input                    clk;                    // system clock
input                    sys_rstn;               // global reset_n
input  [B_CCB-1     : 0] csr_ctl;                // CSR control bus
output [W_REG-1     : 0] reg_csr1;               // CSR1 read values
output                   rsm_event1;             // resume request
output                   exc_error1;             // exception indicator
input                    tx_rdy;                 // Tx frame ready from the Nexus
output                   tx_ack;                 // Tx acknowledgement to the Nexus
input  [W_RTL_FRM-1 : 0] tx_frm;                 // Tx frame data from the Nexus
output                   rx_rdy;                 // Rx frame ready to the Nexus
output [W_RTL_FRM-1 : 0] rx_frm;                 // Rx frame data to the Nexus
output [ ......     : 0] txd_out;                // Tx data output to external logic / chip
input  [ ......     : 0] rxd_in;                 // Rx data input from external logic / chip

// --- PHY logic implementation ---
// ......
// ......

endmodule
```
