# RTMQv2 Reference \#3 - Standard Coherent Node

by Zhang Junhua

Rev.0.7 - 2025.05.19

## Introduction

Only an RT-Core by itself won't be very useful. At least some supporting peripherals like caches, timers, and RTLink interfaces are required for it to become a capable controller of a system. The *standard coherent node* (StdCohNode) is a standardized implementation of RTMQ framework with necessary supporting peripherals, serving as a starting point for developing a coherent node in RTMQ framework. The StdCohNode is provided as a black-box IP core library in obfuscated Verilog source code form, with parameterization disabled.

The provided files are:

- `RTMQ_StdCohNode.v`: The library, providing interface modules.
- `RTMQDef_Core.vh`: Definitions of parameters global to RTMQ framework.
- `RTMQDef_RTLink.vh`: Definitions of RTLink related parameters.
- `RTMQDef_Node.vh`: Definition of parameters that are specific to the node.

Note that the parameters in *DON'T CHANGE* area are hardcoded into the library, so changing them won't have any effect. They are provided just for the convenience of developing new modules.

For detailed description of the interfaces, design guidelines and instantiation templates, please refer to *RTMQv2 Reference \#4 - Developing SoC in RTMQ Framework*. In this reference, only a functional description of the StdCohNode regarding the built-in CSRs, resume request channels and exception channels is provided.

## Customizable Parameters

However, some of the *DON'T CHANGE* parameters are customizable when a copy of StdCohNode is requested, so that they can be changed and packed into the library.

### `RTMQDef_Core.vh`

- `T_EXT_MUL`: multiplier enable
  - `1'b0`: No multiplier, `PHI` and `PLO` instructions always yield `0x00000000`.
  - `1'b1`: With multiplier, `PHI` and `PLO` instructions are functional.
  - Impact: consumes extra logic resources when enabled.
- `T_EXT_DIV`: divider enable
  - `1'b0`: No divider, `DIV` and `MOD` instructions always yield `0x00000000`.
  - `1'b1`: With divider, `DIV` and `MOD` instructions are functional.
  - Impact: consumes extra logic resources when enabled.
- `T_EXT_SGN`: multiplier and divider signedness
  - `1'b0`: multiplier, divider operands and result are unsigned.
  - `1'b1`: multiplier, divider operands and result are signed.
- `W_ALU_STK`: TCS address width
  - The number of entries in the TCS is thus `1 << W_ALU_STK`.
  - Impact: consumes more memory resources with larger value.
- `W_INS_RBF`: instruction cache ring buffer address width
  - The address range of the buffer is thus `-1 << W_INS_RBF` to `-1`.
  - Note: the ring buffer is physically located at the end of the instruction cache.

### `RTMQDef_RTLink.vh`

- `N_CHN_LOC` / `N_CHN_RMT`: number of local / remote channels in the node, no larger than 32.
  - Impact: consumes more logic and memory resources with larger value.
- `W_RBF_ADR`: per-channel Rx buffer address width
  - The capacity of the buffer is thus `1 << W_RBF_ADR` frames for each type (instruction / data).
  - Impact: consumes more memory resources with larger value.
- `W_TBF_ADR`: per-channel Tx buffer address width, similar to `W_RBF_ADR`.
- `N_WPL_INS`: capacity of the waiting pool for instruction frame payloads, in number of instructions.
  - Impact: consumes more logic resources with larger value.
- `W_WPL_LTN`: width of the acceptable latency of the waiting pool, no larger than 19.
  - The maximum acceptable latency is `(1 << W_WPL_LTN) - N_WPL_INS - 1`.
  - Remaining latency of incoming instruction frames larger than the maximum value will be limited to the maximum.
  - Impact: consumes more logic resources and may degrade maximum clock frequency with larger value.
- `W_SCP_ADR`: address width of the scratchpad memory for data frame payloads, no larger than 20.
  - Impact: consumes more memory resources with larger value.

### `RTMQDef_Node.vh`

- `W_ICH`: Instruction cache address width
  - The number of instructions in the cache is thus `1 << W_ICH`.
  - Impact: consumes more memory resources with larger value.
- `W_DCH`: Data cache address width, note that the data cache is byte addressable.
  - The capacity of data cache is thus `1 << W_DCH` bytes.
  - Impact: consumes more memory resources with larger value.
- `W_DCC`: Data cache address auto-increment counter width

## CSR Specifications

### Core CSRs

There are 6 CSRs for controlling the RT-Core:

- `PTR` / `&00`: instruction pointer / jump register
- `LNK` / `&01`: link register
- `RSM` / `&02`: resume request control
- `EXC` / `&03`: exception control
- `EHN` / `&04`: exception handler routine entry
- `STK` / `&05`: TCS pointer

For detailed specifications, please refer to *RTMQv2 Reference \#1 - Instruction Set & Core Architecture*.

### CSRs for Caches

#### `ICF` Register

`ICF` register controls the access behavior of the instruction cache. Currently only `ICF[31]` is used, other bits are reserved.

- Address: `&06`
- Type: Flag CSR
- Read value: written value of `ICF`
- Read side effect: none
- Write value:
  - `ICF[31]`: access control of the secondary port of the cache, through which the cache can be dumped and populated
    - `0`: accessed through `ICA`, `ICD` interface
    - `1`: accessed through the DMA interface (for details of the DMA interface, please refer to *RTMQv2 Reference \#4 - Developing SoC in RTMQ Framework*)
- Write side effect: none

#### `ICA` Register

`ICA` is the address register of the instruction cache.

- Address: `&07`
- Type: Numeric CSR
- Read value: written value of `ICA`
- Read side effect: none
- Write value:
  - the target address of the read / write access through the secondary port of the cache
  - effective only when `ICF[31] == 0`
- Write side effect: none

#### `ICD` Register

`ICD` is the data register of the instruction cache.

- Address: `&08`
- Type: Flag CSR
- Read value:
  - data from the secondary port of the cache
  - for `ICF[31] == 0`, the address is from `ICD`
  - for `ICF[31] == 1`, the address is from the DMA interface
- Read side effect: none
- Write value:
  - the data to be written to the cache, at address `ICA`
- Write side effect: write to the instruction cache when `ICF[31] == 0`
- Example: write to the cache

```RTMQ
CHI - ICA 0x1234
CLO - ICA 0x1234
CHI - ICD 0x00E00000
CLO - ICD 0x00E00000   % write 0x00E00000 to address 0x1234
```

- Example: read from the cache

```RTMQ
CHI - ICA 0x1234
CLO - ICA 0x1234
NOP P                  % wait until data is available
CSR - $03 ICD          % $03 = 0x00E00000
```

#### `DCF` Register

`DCF` register controls the access behavior of the data cache.

- Address: `&09`
- Type: Flag CSR
- Read value: written value of `DCF`
- Read side effect: none
- Write value:
  - `DCF[W_DCC-1:0]`: address auto-increment count, see `DCA` register for details
  - `DCF[31:30]`: access type of the primary port of the cache
    - `00`: word access (4-byte)
    - `01`: byte access
    - `10`: half-word access (2-byte)
    - `11`: reserved
  - `DCF[29]`: write data source of the primary port of the cache
    - `0`: written value of `DCD` register
    - `1`: stream input port
- Write side effect: none

#### `DCA` Register

`DCA` is the address register of the data cache.

- Address: `&0A`
- Type: Numeric CSR
- Read value: final address after the auto-increment
- Read side effect: none
- Write value:
  - the target address of the read / write access through the primary port of the cache, if `DCF[W_DCC-1:0] == 0`
  - the start address of auto-increment, if `DCF[W_DCC-1:0] > 0`
  - the access shall be *aligned*:
    - for `DCF[31:30] == 00` (word access), `DCA[1:0]` shall be `00`
    - for `DCF[31:30] == 10` (half-word access), `DCA[0]` shall be `0`
- Write side effect:
  - start auto-increment, each clock cycle the address increases with 1 unit (4 bytes for word access, 2 bytes for half-word access and 1 byte for byte access), until the designated count exceeded
  - when address auto-increasing and `DCF[29] == 1`, data from the stream input port is written to the designated address range of the cache

#### `DCD` Register

`DCD` is the data register of the data cache.

- Address: `&0B`
- Type: Flag CSR
- Read value:
  - data from the primary port of the cache, at the designated address, with type determined by `DCF[31:30]`
  - for half-word and byte access, unused MSBs are filled with 0s
- Read side effect: raise *unaligned access* exception for unaligned read
- Write value:
  - the data to be written to the cache, at the designated address, with type determined by `DCF[31:30]`
  - for half-word and byte access, unused MSBs are ignored
- Write side effect:
  - write to the data cache
  - raise *unaligned access* exception for unaligned write
- Example: write to the cache

```RTMQ
CHI - DCA 0
CLO - DCF 0         % no auto-increment
AMK - DCF 3.F 1.F   % byte access
CLO - DCA 0
CLO - DCD 0xFE
CLO - DCA 1
CLO - DCD 0xCA
AMK - DCF 3.F 2.F   % half-word access
CLO - DCA 2
CLO - DCD 0xBAAD
```

- Example: read from the cache

```RTMQ
AMK - DCF 3.F 0.F   % word access
CLO - DCA 0
NOP P               % wait until data is available
NOP -
NOP -
CSR - $03 DCD       % $03 = 0xBAADCAFE
```

- Example: auto-increment write

```RTMQ
CHI - DCA 0
CLO - DCF 4         % auto-increment count: 4
AMK - DCF 3.F 2.F   % half-word access
CLO - DCA 0         % start auto-increment
CLO - DCD 0xBEEF    % addr: 0
CLO - DCD 0xDEAD    % addr: 2
CLO - DCD 0x5678    % addr: 4
CLO - DCD 0x1234    % addr: 6
```

- Example: auto-increment read

```RTMQ
CLO - DCF 2         % auto-increment count: 2
AMK - DCF 3.F 0.F   % word access
CLO - DCA 0
NOP P               % wait until data is available
NOP -
NOP -
CSR - $03 DCD       % addr: 0; $03 = 0xDEADBEEF
CSR - $04 DCD       % addr: 4; $04 = 0x12345678
```

### `NEX` Subfile

`NEX` subfile (address: `&0C`) configures the *nexus*, the RTLink routing module in the StdCohNode. For details regarding the RTLink protocol, refer to *RTMQv2 Reference \#2 - RTLink Network*

The CSRs in `NEX` are:

- `&00` ~ `&1F` (unnamed CSR): remote channel latency compensation
- `ADR`: current node address
- `BCE`: broadcast propagation enable
- `RTA`: local routing table address register
- `RTD`: local routing table data register

#### `&00` ~ `&1F` Registers

When an instruction frame is transferred through a remote channel, the communication latency of that channel shall be reduced from the TAG field. `NEX.&00` ~ `NEX.&1F` configures the latency compensation value for each remote channel. Note that regardless of the value of parameter `N_CHN_RMT` (the number of remote channels the StdCohNode actually has), there are always 32 latency compensation CSRs.

- Address: `&00` ~ `&1F` in `NEX`
- Read value:
  - `&xx[19:0]`: written value of `&xx`
  - `&xx[31:20]`: reserved to be 0
  - `&yy` without corresponding to actual remote channel: reserved to be 0
- Read side effect: none
- Write value:
  - `&xx[19:0]`: latency compensation value for remote channel #xx, in number of clock cycles
- Write side effect: none

#### `ADR` Register

`ADR` register stores the RTLink address of the current node.

- Address: `&20` in `NEX`
- Read value: written value of `ADR`
- Read side effect: none
- Write value:
  - `ADR[31]`: acceptance of broadcast frames for the current node
    - `0`: accept broadcast frames and forward them to the destination local channel
    - `1`: don't accept broadcast frames, only propagate them
  - `ADR[15:0]`: RTLink address of the current node
- Write side effect: none

#### `BCE` Register

`BCE` controls the broadcast propagation of the remote channels.

- Address: `&21` in `NEX`
- Read value: written value of `BCE`
- Read side effect: none
- Write value:
  - `BCE[31:0]`: broadcast propagation enable of each remote channel
    - `0`: disabled
    - `1`: forward broadcasting frames with wildcard destination address
- Write side effect: none

#### `RTA` Register

`RTA` is the address register for the local routing table configuration.

- Address: `&22` in `NEX`
- Read value: written value of `RTA`
- Read side effect: none
- Write value:
  - `RTA[19]`: target routing table selection
    - `0`: subnet routing table
    - `1`: cluster routing table
  - `RTA[11:0]`: if `RTA[19] == 0`, the subnet address of the target table entry to be configured
  - `RTA[3:0]`: if `RTA[19] == 1`, the cluster address of the target table entry to be configured
- Write side effect: none

#### `RTD` Register

`RTD` is the data register for the local routing table configuration.

- Address: `&23` in `NEX`
- Read value: the table entry at address `RTA` of the selected routing table
- Read side effect: none
- Write value: the data to be written to the table entry
  - `RTD[4:0]`: the index of the remote channel to which frames targeting the corresponding node / cluster to be relayed
  - `RTD[5]`: validity of this entry
    - `0`: this entry is invalid
    - `1`: this entry is valid
- Write side effect: write to the routing table

### `FRM` Subfile

`FRM` subfile (address: `&0D`) is the interface for assembling and sending RTLink frames from local channel #0.

The CSRs in `FRM` are:

- `PL1`: LSB half of the payload
- `PL0`: MSB half of the payload
- `TAG`: flags and tag of the frame
- `DST`: destination of the frame

#### `PL0` and `PL1` Register

`PL0` and `PL1` are used to set the PLD field of the RTLink frame.

- Address: `&01` for `PL0`, `&00` for `PL1` in `FRM`
- Read value: written value of each one
- Read side effect: none
- Write value:
  - `PL0[31:0]`: the MSB half of the PLD field
  - `PL1[31:0]`: the LSB half of the PLD field
- Write side effect:
  - `PL1`: assemble and send the RTLink frame according to the values of the registers

#### `TAG` Register

`TAG` is used to set the TYP, SRF and TAG fields of the RTLink frame.

- Address: `&02` in `FRM`
- Read value: written value of `TAG`
- Read side effect: none
- Write value:
  - `TAG[19:0]`: the TAG field
  - `TAG[21:20]`: the SRF field
    - `00`: normal frame
    - `01`: broadcast frame
    - `10`: echo frame
    - `11`: directed frame
  - `TAG[22]`: the TYP field
    - `0`: data frame
    - `1`: instruction frame
- Write side effect: none

#### `DST` Register

`DST` is used to set the CHN and ADR fields of the RTLink frame.

- Address: `&03` in `FRM`
- Read value: written value of `DST`
- Read side effect: none
- Write value:
  - `DST[15:0]`: the ADR field
  - `DST[24:20]`: the CHN field
- Write side effect: none

### `SCP` Subfile

`SCP` subfile (address: `&0E`) is the interface for the scratchpad memory that handles the data frames received in local channel #0.

The CSRs in `SCP` are:

- `MEM`: memory interface
- `TGM`: frame tag monitor
- `CDM`: coded trigger monitor
- `COD`: trigger code

#### `MEM` Register

`MEM` is the address / data register of the scratchpad memory that stores the payload of data frames.

- Address: `&00` in `SCP`
- Read value: data in the scratchpad memory, at the written address
- Read side effect: none
- Write value: target address to be read
- Write side effect: none
- Note: when a data frame with TAG field `T` is received, the MSB half of its payload is stored at address `T*2`, and the LSB half at `T*2+1`

#### `TGM` Register

`TGM` determines the target TAG field to be monitored. When a data frame with the designated TAG field is received, a resume request is generated in channel #1.

- Address: `&01` in `SCP`
- Read value: written value of `TGM`
- Read side effect: none
- Write value:
  - `TGM[19:0]`: target TAG field to be monitored
  - `TGM[31]`: monitor enable flag
    - `0`: disable
    - `1`: enable
- Write side effect: none

#### `CDM` Register

`CDM` is similar to `TGM`, but monitors instruction frames instead.

- Address: `&02` in `SCP`
- Read value: written value of `CDM`
- Read side effect: none
- Write value:
  - `CDM[19:0]`: target code to be monitored
  - `CDM[31]`: monitor enable flag
    - `0`: disable
    - `1`: enable
- Write side effect: none

#### `COD` Register

`COD` is the trigger code. When it is written and `COD[19:0] == CDM[19:0]`, a resume request is generated in channel #1.

- Address: `&03` in `SCP`
- Read value: written value of `COD`
- Read side effect: none
- Write value:
  - `COD[19:0]`: the trigger code
- Write side effect: generate a resume request in channel #1 if `COD[19:0] == CDM[19:0]` and `CDM[31] == 1`
- Note: in most cases it should be written by external instruction frames
- Example: issue trigger code `0xFACE` to node `0x12`

```RTMQ
SFS - FRM DST
CHI - FRM 0x12         % destination local channel: #0
CLO - FRM 0x12         % destination node address: 0x12
SFS - FRM TAG
CHI - FRM 0x00400000   % normal instruction frame
CLO - FRM 0x00400000   % TAG = 0 (no waiting in the pool)
SFS - FRM PL1
CHI - FRM 0xE90FACE
CLO - FRM 0xE90FACE    % machine code of "CLO - SCP 0xFACE"
SFS - FRM PL0
CHI - FRM 0xE880003
CLO - FRM 0xE880003    % machine code of "SFS - SCP COD"
```

### CSRs for Timers

#### `TIM` Register

`TIM` is the interface for the countdown timer peripheral. When the designated number of clock cycles elapsed, a resume request is generated in channel #2.

- Address: `&0F`
- Read value: written value of `TIM`
- Read side effect: none
- Write value:
  - `TIM[31:0]`: the duration of countdown, in number of clock cycles
- Write side effect:
  - enable the timer and start counting down
  - update the wall clock timestamps in `BGN` and `END` of subfile `WCL` and `WCH` (see below)
- Example: a structure like this takes exactly `T` clock cycles

```RTMQ
CLO - TIM T   % start counting down for T cycles
......
......        % whatever instructions, takes no more than T-2 cycles
......
NOP H         % hold the RT-Core, until the timer expires
```

#### `WCL` Subfile

`WCL` and `WCH` are the interfaces for the wall clock timer. The wall clock timer is a 64-bit timer, keep increasing regardless of the state of the RT-Core. `WCL` stores the LSB half of the wall clock time.

The CSRs in `WCL` are:

- `NOW` / `&00`: current wall clock time
- `BGN` / `&01`: start of a countdown
- `END` / `&02`: end of a countdown

For `WCL` subfile:

- Address: `&10`
- Read value:
  - `NOW[31:0]`: wall clock timestamp of the current instruction
  - `BGN[31:0]`: wall clock timestamp of the instruction immediately after `TIM` is written
  - `END[31:0]`: expected wall clock timestamp of the instruction immediately after the resuming of the RT-Core (updated when `TIM` is written)
- Read side effect: none
- Write value: write to any of the CSRs
  - `WCL[31:0]`: the LSB half of the initial offset of the wall clock
- Write side effect: reset the wall clock timer to the initial offset
- Example: timestamps in `BGN` and `END`

```RTMQ
CLO - TIM 123      % start counting down for 123 cycles
CLO - LED 0xF000   % BGN stores the timestamp of this instruction
......
......
NOP H              % hold the RT-Core, until the timer expires
CLO - LED 0xBAAA   % END stores the timestamp of this instruction
```

#### `WCH` Subfile

`WCH` stores the MSB half of the wall clock time. It has the same CSR structure as `WCL`.

- Address:
  - Read/Write address: `&11`
  - SFS address: `&10` (share the address of `WCL`)
- Read value: MSB half of each timestamp
- Read side effect: none
- Write value: write to any of the CSRs
  - `WCH[31:0]`: the MSB half of the initial offset of the wall clock
- Write side effect: none
- Example: get current time stamp

```RTMQ
SFS - WCL NOW
NOP P
CSR - $03 WCL      % read WCL first
CSR - $04 WCH      % then WCH
```

- Example: reset the wall clock timer

```RTMQ
CHI - WCH -1
CLO - WCH -1       % set WCH first
CHI - WCL -3
CLO - WCL -3       % then WCL
```

## Resume Request Channels

- #0: master resume request (see *RTMQv2 Reference \#1 - Instruction Set & Core Architecture*)
- #1: fire of tag monitor / coded trigger (see *`SCP` Subfile* subsection)
- #2: countdown timer expiration (see *CSRs for Timers* subsection)

## Exception Flags

- #0: halt request (see *RTMQv2 Reference \#1 - Instruction Set & Core Architecture*)
- #1: resume request misaligned
  - occurs when a resume request is generated in an enabled channel, but the RT-Core is not on hold.
- #2: TCS overflow
  - occurs when read / write access of TCS is out of bound.
- #3: division by zero
  - occurs when `DIV` or `MOD` is executed with `OP1 == 0`.
- #4: instruction fetch out of bound
  - occurs when the instruction fetch address is out of bound, due to an incorrect jump or program runaway.
- #5: data cache overflow
  - occurs when the address to the primary port of the data cache is out of bound.
- #6: data cache unaligned access
  - occurs when the address to the primary port of the data cache is not aligned to word (half-word) for word (half-word) access, and `DCD` is read or written.
- #7: RTLink FIFO overflow
  - occurs when any Tx/Rx FIFO in the nexus (RTLink routing module) overflows.

## Pipeline Latency

Due to the pipeline arrangement of the implementation, gap cycles shall be inserted between write and read operations, such that new value is available.

### Timing Facts

- `P` flag holds the RT-Core for 6 cycles, such that `NOP P` takes 7 cycles.
- A jump (write to `PTR` with `P` flag) takes 10 cycles to complete.
- The minimum allowed duration for the countdown timer (allowed written value of `TIM`) is 10.

### CSR Read after Write

Gap cycles: 3

```RTMQ
CLO - LED 0x1234
NOP -
NOP -
NOP -
CSR - $03 LED   % $03 = 0x1234
```

### Subfile Write after SFS

Gap cycles: 0

```RTMQ
SFS - SCP COD
CLO - SCP 0x6789   % write to COD in SCP
```

### Subfile Read after SFS / Write

Gap cycles: 5

```RTMQ
SFS - NEX ADR
CLO P NEX 0xBAAD   % in this case, use P flag to pause for 6 cycles is more convenient
CSR - $03 NEX      % $03 = 0xBAAD
```

### TCS Read after Write

Gap cycles: 1

```RTMQ
GLO - $03 0xABCD
NOP -
AMK - LED $01 $03   % LED = 0xABCD
```

### TCS Write after `STK` Write

Gap cycles: 1

```RTMQ
CLO - STK 0x10
NOP -
GLO - $25 0x1234   % write to TCS at 0x25+0x10 == 0x35
```

### TCS Read after `STK` Write

Gap cycles: 4

```RTMQ
CLO - STK 0
NOP -
GLO - $25 0x1234   % write to TCS at 0x25
CLO - STK 0x5      % set stack offset to 5
NOP -
NOP -
NOP -
NOP -
AMK - LED $01 $20  % read from TCS at 0x20+0x5 == 0x25
```

### `PHI`, `PLO` after `OPL`

Gap cycles: 7

```RTMQ
GLO - $03 0x12345678
GHI - $03 0x12345678
GLO - $04 0x9ABCDEF
GHI - $04 0x9ABCDEF
NOP -
OPL - $03 $04      % load $03 to OP0, $04 to OP1
NOP P
PHI - $05          % $05 = 0x00B00EA4
PLO - $06          % $06 = 0xE242D208
```

### `DIV`, `MOD` after `OPL`

Gap cycles: 35

```RTMQ
GLO - $03 324
GLO - $04 47
NOP -
OPL - $03 $04
NOP P              % \
NOP P              %  |
NOP P              %  |- altogether 35 cycles
NOP P              %  |
NOP P              % /
DIV - $05          % $05 = 6
MOD - $06          % $06 = 42
```

### Cache Access

- `DCD` write after `DCA` write: 0 gap cycles
- `ICD` write after `ICA` write: 0 gap cycles
- `DCD` read after `DCA` write: 9 gap cycles
- `ICD` read after `ICA` write: 7 gap cycles

For examples, please refer to subsections *`DCD` Register* and *`ICD` Register*.

### `SCP.MEM` Read after `SCP.MEM` Write

Gap cycles: 7

```RTMQ
SFS - SCP MEM
CLO - SCP 0x12
NOP P
CSR - $03 SCP   % read the scratchpad memory at 0x12
```
