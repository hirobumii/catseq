# RTMQv2 Reference \#1 - Instruction Set & Core Architecture

by Zhang Junhua

Rev.0.5 - 2025.05.19

## Introduction

**RTMQ** (Real-Time Microsystem for Quantum physics) is a 32-bit SoC (System-on-Chip) framework for quantum experiment control and other scenarios with nano-second timing precision requirements. The framework includes dedicated instruction set, micro-architecture and networking protocol, all to fulfill one goal: integrating scalability and flexibility with precise timing.

The design philosophy of RTMQ framework is that, *computation is part of the timing sequence*. Instead of a host running software to generate timing sequences and sending triggers here and there, the programs run by the RTMQ processor (RT-Core) by themselves have well defined timing. So not only triggers and flags, the data flow in the framework is also precisely timed.

Since the RTMQ framework is basically designed and optimized for control and light-weighted computation, peripheral I/O has higher priority than memory access. There are 2 address spaces that the RT-Core can directly access:

- **CSR** (Control-Status Register) space: CSRs are interfaces between the RT-Core and peripherals. Reading from or writing to a CSR will issue triggers of side effect to its corresponding peripheral. The address is 8-bit wide, so the maximum number of CSR is 256.
- **TCS** (Tightly-Coupled Stack) space: TCS is a special memory space with a similar role to a windowed general-purpose register (GPR) space, and is designed to reduce the frequent needs of data exchange between GPRs and memory. The capacity of TCS is limited by memory resources that is physically available for an implementation of the framework.

The instruction set of RTMQ framework is designed such that peripheral I/O operations have minimal overhead. The instruction set contains only I/O related instructions (Type-C) addressing CSRs and arithmetic-logic instructions (Type-A) addressing TCS. All other processor related operations, including flow control, exception handling, stack control and memory access, are realized through accessing special CSRs.

## Instruction Set

### Types of CSR

There are 3 types of CSR in RTMQ framework to fulfill different types of control requirements:

- **Numeric CSR**: CSRs that support self-increment. (see `AMK` instruction for details)
- **Flag CSR**: CSRs that support auto-reload. When a bit in a flag CSR is auto-reloadable, it will be reloaded with the designated default value immediately if it is not written to. It is handy for generating 1-cycle triggers.
- **CSR Subfile**: collections of rarely accessed or less timing-critical CSRs. CSR subfile is introduced to expand the limited CSR address space, with each one containing at most 256 CSRs. Note that the CSRs in a subfile have no special functions like self-increment and auto-reload. (see `SFS` instruction for details)

In assembly instructions, a CSR can be referenced either with its associated name (designated by the designer of the system) or with its address in `&xx` notation, in which `xx` is the hexadecimal representation of the address.

The CSRs in a subfile can also have associated names. However, there are situations that some CSRs in a subfile function as a sequence, and usually they are accessed in order. These CSR shall occupy the lower address space of the subfile, from `&00`. Assigning names to them is not necessary, and so they are *unnamed CSRs*.

### Accessing TCS

Though the capacity of TCS can be arbitrary, at any time only 256 entries can be directly accessed. That is, the field of TCS address in the machine code of an instruction is also 8-bit wide. In assembly instructions, a TCS entry can only be referenced with its address in `$xx` notation.

Note that:

- The first 32 entries, `$00` ~ `$1F`, serve as GPRs. They are always accessable, regardless of the stack pointer. They also occupy the 0x00 ~ 0x1F physical address range of the TCS space.
- The first 2 entries, `$00` and `$01`, shall always be `0x00000000` and `0xFFFFFFFF` respectively. They shall be initialized at the startup of the system and never be changed.
- The physical addresses of entries `$20` ~ `$FF` are offset with the stack pointer, which is controlled by a numeric CSR named `STK`. For example, the physical address of `$21` when `STK == 0x5678` is `0x21 + 0x5678 == 0x5699`.

### Syntax of Assembly Instructions

An assembly instruction takes the following form:

```RTMQ
OPC F RD R0 R1
```

- `OPC` is the opcode.
- `F` is the flow control flag, valid flags are `-`, `H` and `P`.
  - `-` flag has no effect.
  - `H` flag holds the instruction fetch from the cache, waiting for a resume request.
  - `P` flag pause the instruction fetch for a specific number of cycles that is determined by the implementation of the framework.
  - `H` and `P` flags are only for Type-C instructions.
- `RD` is the destination CSR / TCS entry, to which the result of the instruction is written.
- `R0` and `R1` are the operands.
- Depending on the opcode, any of `RD`, `R0` and `R1` may be omitted.

Labels for jump take the following form. Each one occupies 1 line, pointing to the instruction next to it.

```RTMQ
#label:
```

A label can be referenced in assembly instructions like this:

```RTMQ
CLO P PTR #label
```

A comment starts with a `%`, and either occupies 1 whole line, or follows an instruction:

```RTMQ
% whole line comment
CLO - LED 1  % comment after an instruction
```

### Type-C Instructions (`RD` is CSR)

#### CHI

Load higher 12 bits of `RD` with higher 12 bits of immediate.

- Effect: `RD[31:20] = imm[31:20]`
- Side effect: None.
- Syntax: `CHI - RD imm[31:00]`
- Valid flag: `-`
- Encoding:

| 31 - 24 | 23 - 12 | 11 - 00      |
|:-------:|:-------:|:------------:|
|  `RD`   |  0x800  | `imm[31:20]` |

#### CLO

Load lower 20 bits of `RD` with lower 20 bits of immediate.

- Effect: `RD[19:00] = imm[19:00]`
- Side effect: `RD` issues WRITE trigger.
- Syntax: `CLO F RD imm[31:00]`
- Valid flag: `-`, `H`, `P`
- Encoding:

| 31 - 24 | 23 - 20 | 19 - 00      |
|:-------:|:-------:|:------------:|
|  `RD`   |   opc   | `imm[19:00]` |

| Flag | opc |
|:----:|:---:|
| `-`  | 0x9 |
| `H`  | 0xA |
| `P`  | 0xB |

#### AMK

Masked assignment to `RD`.

- Effect:
  - If `RD` is a numeric CSR:
    - if `R0[1:0] == 0b11` then `RD = RD + R1`
    - else if `R0[1:0] == 0b10` then `RD = R1`
    - else `RD = RD`
  - If `RD` is a flag CSR or a CSR in a subfile: `RD[i] = (R0[i] == 1) ? R1[i] : RD[i]`
- Side effect:
  - If `RD` is a numeric CSR: `RD` issues WRITE trigger if `R0[1] == 1`.
  - If `RD` is a flag CSR or a CSR in a subfile: `RD` issues WRITE trigger if `R0 != 0`.
  - `R1` issues READ trigger if it is a CSR.
- Syntax: `AMK F RD R0 R1`
- Valid flag: `-`, `H`, `P`
- Valid `R0`:
  - immediate in `X.P` notation:
    - `X` and `P` are in single-digit unsigned hexadecimal notation
    - evaluated as `X << (P * 2)`
    - encoded in 8 bits as `(X << 4) + P`
  - TCS entry
- Valid `R1`:
  - immediate in `X.P` notation
  - 8-bit direct immediate, sign-extended to 32 bits
  - CSR
  - TCS entry
- Encoding:

| 31 - 24 | 23 - 20 | 19 - 18 |  17  |  16  | 15 - 08 | 07 - 00 |
|:-------:|:-------:|:-------:|:----:|:----:|:-------:|:-------:|
|  `RD`   |   opc   |  t_rs   | t_r0 | t_r1 |  `R0`   |  `R1`   |

| Flag | opc |
|:----:|:---:|
| `-`  | 0xD |
| `H`  | 0xE |
| `P`  | 0xF |

| `R0`      | t_r0 |
|:---------:|:----:|
| X.P imm.  |  0   |
| TCS entry |  1   |

| `R1`        | t_rs | t_r1 |
|:-----------:|:----:|:----:|
|  X.P imm.   |  00  |  0   |
| direct imm. |  00  |  1   |
| CSR         |  01  |  0   |
| TCS entry   |  01  |  1   |

- Example:
  - `AMK - CAT $01 FISH`: assign the value of CSR `FISH` to flag CSR `CAT`.
  - `AMK - ENA 6.2 4.2`: set bit `ENA[6]` and clear bit `ENA[5]` of flag CSR `ENA`.
  - `AMK - CNT 2.0 -2`: load numeric CSR `CNT` with -2 (`0xFFFFFFFE`).
  - `AMK - CNT 3.0 $13`: increase numeric CSR `CNT` with TCS entry `$13`.

#### SFS

Select a CSR in a subfile that can later be accessed with the address of the subfile. The selected CSR will issue triggers accordingly when accessed.

- Syntax
  - direct addressing: `SFS - SF CSR` (both `SF` and `CSR` support `&xx` notation)
  - indirect addressing: `SFS - SF $xx` (value of TCS entry `$xx` is used as the address)
- Valid flag: `-`
- Encoding:

| 31 - 24 | 23 - 20 | 19 - 16 | 15 - 08 | 07 - 00     |
|:-------:|:-------:|:-------:|:-------:|:-----------:|
|  `SF`   |   0x8   |  mode   |  0x00   | `CSR`/`TCS` |

| addressing | mode |
|:----------:|:----:|
|  direct    | 0x8  |
|  indirect  | 0x9  |

For example,

```RTMQ
SFS - KITCHEN OVEN
CHI - KITCHEN 0xBAADBEEF
CLO - KITCHEN 0xBAADBEEF
```

will load `0xBAADBEEF` to CSR `OVEN` of subfile `KITCHEN`.

Note that several different subfiles can share the same address as to `SFS` instruction. This feature is introduced to save the instruction overhead when accessing a group of related subfiles. Suppose we have 2 subfiles, `CAT` and `DOG`, each one contains 2 CSRs, `BIG` and `TINY`. And subfile `DOG` shares the address of subfile `CAT`, then,

```RTMQ
SFS - CAT TINY
CLO - CAT 0xF00D
CLO - DOG 0xF00D
```

will load `0xF00D` to the lower 20 bits of CSR `TINY` in both subfiles.

#### NOP

- Effect: No operation.
- Syntax: `NOP F`
- Valid flag: `-`, `H`, `P`
- Encoding:
  - `NOP -`: `0x00D00000` / `0x00000000`
  - `NOP H`: `0x00E00000`
  - `NOP P`: `0x00F00000`

### Type-A Instructions (`RD` is TCS entry)

#### CSR

Load value of CSR `R1` to TCS entry `RD`.

- Effect: `RD = R1(CSR)`
- Side effect: `R1` issues READ trigger.
- Syntax: `CSR - RD R1`
- Valid `R1`: CSR
- Encoding:

| 31 - 24 | 23 - 18 |  17  |  16  | 15 - 08 | 07 - 00 |
|:-------:|:-------:|:----:|:----:|:-------:|:-------:|
|  `RD`   |  0x04   |  0   |  0   |  0x00   |  `R1`   |

#### GHI

Load higher 12 bits of `RD` with higher 12 bits of immediate.

- Effect: `RD[31:20] = imm[31:20]`
- Syntax: `GHI - RD imm[31:00]`
- Encoding:

| 31 - 24 | 23 - 18 |  17  |  16  | 15 - 12 | 11 - 00      |
|:-------:|:-------:|:----:|:----:|:-------:|:------------:|
|  `RD`   |  0x05   |  0   |  0   |   0x0   | `imm[31:20]` |

#### GLO

Load `RD` with lower 20 bits of immediate and sign-extend to 32 bits.

- Effect: `RD = sign_ext(imm[19:00])`
- Syntax: `GLO - RD imm[31:00]`
- Encoding:

| 31 - 24 | 23 - 20 | 19 - 00      |
|:-------:|:-------:|:------------:|
|  `RD`   |   0x2   | `imm[19:00]` |

#### OPL

Load `R0` and `R1` to dedicated multiply/divide operand register `OP0` and `OP1` respectively.

- Effect: `OP0 = R0; OP1 = R1`
- Syntax: `OPL - R0 R1`
- Valid `R0`: TCS entry
- Valid `R1`:
  - TCS entry
  - 8-bit direct immediate, sign-extend to 32 bits
- Encoding:

| 31 - 24 | 23 - 18 |  17  |  16  | 15 - 08 | 07 - 00 |
|:-------:|:-------:|:----:|:----:|:-------:|:-------:|
|  0x00   |  0x07   |  1   | t_r1 |  `R0`   |  `R1`   |

| `R1`       | t_r1 |
|:----------:|:----:|
| immediate  |  0   |
| TCS entry  |  1   |

#### PLO, PHI, DIV, MOD

Arithmetic multiply / divide operations, signedness determined by implementation.

- Effect:
  - `PLO`: `RD = (OP0 * OP1)[31:00]`
  - `PHI`: `RD = (OP0 * OP1)[63:32]`
  - `DIV`: `RD = OP0 div OP1`
  - `MOD`: `RD = OP0 mod OP1`
- Syntax:
  - `PLO - RD`
  - `PHI - RD`
  - `DIV - RD`
  - `MOD - RD`
- Encoding:

| 31 - 24 | 23 - 18 |  17  |  16  | 15 - 08 | 07 - 00 |
|:-------:|:-------:|:----:|:----:|:-------:|:-------:|
|  `RD`   |  0x07   |  0   |  0   |  0x00   |   opc   |

| Opcode | opc |
|:------:|:---:|
| `PLO`  |  0  |
| `PHI`  |  1  |
| `DIV`  |  2  |
| `MOD`  |  3  |

#### Other Opcodes

- All other opcodes have the same syntax: `OPC - RD R0 R1`
- Valid `R0` and `R1`:
  - TCS entry
  - 8-bit direct immediate, sign-extend to 32 bits
- Encoding:

| 31 - 24 | 23 - 18 |  17  |  16  | 15 - 08 | 07 - 00 |
|:-------:|:-------:|:----:|:----:|:-------:|:-------:|
|  `RD`   |   opc   | t_r0 | t_r1 |  `R0`   |  `R1`   |

| `Rx`       | t_rx |
|:----------:|:----:|
| immediate  |  0   |
|    TCS     |  1   |

| Opcode |  opc   | Effect |
|:------:|:------:|:------ |
| `AND`  |  0x00  | Bitwise AND, `RD = R0 & R1` |
| `IAN`  |  0x01  | Bitwise AND with `R0` inverted, `RD = ~R0 & R1` |
| `BOR`  |  0x02  | Bitwise OR, `RD = R0 \| R1` |
| `XOR`  |  0x03  | Bitwise exclusive-OR, `RD = R0 ^ R1` |
| `SGN`  |  0x06  | Sign transfer, `RD = (R0 < 0) ? -R1 : R1` |
| `ADD`  |  0x0C  | Arithmetic addition, `RD = R0 + R1` |
| `SUB`  |  0x0D  | Arithmetic subtraction, `RD = R0 - R1` |
| `CAD`  |  0x0E  | Carry of addition, `RD = (R0 + R1 > 0xFFFFFFFF) ? -1 : 0` |
| `CSB`  |  0x0F  | Carry of subtraction / unsigned less than, `RD = (R0 < R1) ? -1 : 0` |
| `NEQ`  |  0x10  | Compare, non-equal, `RD = (R0 != R1) ? -1 : 0` |
| `EQU`  |  0x11  | Compare, equal, `RD = (R0 == R1) ? -1 : 0` |
| `LST`  |  0x12  | Compare, signed less than, `RD = (R0 < R1) ? -1 : 0` |
| `LSE`  |  0x13  | Compare, signed less-equal, `RD = (R0 <= R1) ? -1 : 0` |
| `SHL`  |  0x14  | Logic shift left with 0 padding LSB, `RD = R0 << R1[4:0]` |
| `SHR`  |  0x15  | Logic shift right with 0 padding MSB, `RD = R0 >> R1[4:0]` |
| `ROL`  |  0x16  | Rotate left, `RD = (R0 << R1[4:0]) \| (R0 >> (32 - R1[4:0]))` |
| `SAR`  |  0x17  | Arithmetic shift right, `RD = sign_ext(R0) >> R1[4:0]` |

### Special Notices

- For assembly instructions `CHI`, `CLO`, `GHI` and `GLO`, the whole immediate should be provided for readability.
- For assigning an immediate to a CSR, use `CHI` first, then `CLO`, for `CLO` will cause the write trigger to be issued.
- For assigning an immediate to a TCS entry, use `GLO` first, then `GHI`, for `GLO` will overwrite the whole entry.
- Writing to a subfile immediately after `SFS` instruction is OK. However, reading immediately following `SFS` will encounter a read-after-write (RAW) hazard. You should wait some cycles (depends on the implementation) for the correct data to be available.
- Multiplication and division takes multiple cycles to complete (depends on the implementation). So you should wait for some cycles between instruction `OPL` and `PLO`, `PHI`, `DIV`, `MOD`.

## Core Architecture

### Overview

As is mentioned, the instruction set contains only peripheral I/O and computation instructions. Processor related operations are realized though special CSR access. There are 6 such CSRs:

- `PTR`: instruction pointer / jump register
- `LNK`: link register
- `RSM`: resume request control
- `EXC`: exception control
- `EHN`: exception handler routine entry
- `STK`: TCS pointer

### `PTR` Register

`PTR` register stores the address of current instruction. Writing to it will initiate a jump.

- Address: `&00`
- Type: Numeric CSR
- Read value:
  - the address of the current instruction if it is from the instruction cache
  - the address of the last instruction from the instruction cache if the RT-Core is on hold / paused, or the current instruction is of other origin
- Read side effect: none
- Write value: target address of the jump
- Write side effect: jump to the designated address
- Note:
  - For self-increment `AMK` instructions, an increment of 0 jumps to the current instruction
  - Write to `PTR` always with `P` flag, so that instruction fetch pipeline is correctly flushed
  - A segment with configurable size in the negative address space is used as a ring buffer. Approaching address 0 from the negative side will round back to the beginning of the buffer. Use jump to enter and exit the buffer space. The buffer may be physically located at the end of the available memory space.
- Example: conditional relative jump

```RTMQ
AMK P PTR $03 -10  % jump backward if $03 == -1
```

### `LNK` Register

`LNK` register stores the return address of the last jump.

- Address: `&01`
- Type: N/A (`LNK` is read-only)
- Read value:
  - the return address of the last jump
  - That is, any time when `PTR` is about to be written, `LNK` is updated with `PTR + 1` first
- Read side effect: none
- Example: entry and return of a simple subroutine

```RTMQ
CSR - $20 LNK      % save the return address
...
...
...
AMK P PTR 2.0 $20  % return
```

### `RSM` Register

When the RT-Core is on hold after an `H` flag, resume requests from peripheral modules can resume the RT-Core if the corresponding channels are enabled in `RSM` register. If more than 1 channels are enabled, request from any one of them will suffice. While if the RT-Core is not currently on hold, the requests from enabled channels will stay until the RT-Core enters hold state.

- Address: `&02`
- Type: Flag CSR
- Read value:
  - `RSM[0]`: current state of the RT-Core
    - `0`: running
    - `1`: on hold
  - `RSM[31:1]`: written value of `RSM`
- Read side effect: none
- Write value:
  - `RSM[0]`: master resume request
    - `1`: resume the RT-Core immediately
    - auto-reload to `0`
  - `RSM[31:1]`: channel enable bit
    - `0`: disable
    - `1`: enable
- Write side effect: clear all pending resume requests

### `EXC` Register

When an exception occurs, the flag bit of the corresponding exception channel is asserted. If exception handling of that channel is enabled in `EXC` register, the RT-Core will jump to the exception handler routine entry stored in `EHN` register. Other than exception handling, `EXC` register is also related to a halt mechanism introduced for external intervention of the RT-Core. *Halt* is different from *hold* in that the RT-Core cannot be resumed with resume requests from peripherals.

- Address: `&03`
- Type: Flag CSR
- Read value:
  - `EXC[0]`: current state of the RT-Core
    - `0`: running
    - `1`: halted
  - `EXC[31:1]`: flag bit of each exception channel
    - `0`: no exception
    - `1`: exception occurred
- Read side effect: clear all exception flag bits.
- Write value:
  - `EXC[0]`: halt request
    - `0`: resume from halt
    - `1`: halt the RT-Core immediately
  - `EXC[31:1]`: exception handling enable bit for each channel
    - `0`: only register the exception, no handling
    - `1`: enable exception handling
- Write side effect: none

### `EHN` Register

`EHN` register stores the entry address of the exception handler routine. When an exception with enabled handling occurs, the exception handler routine is called automatically, and then exception handling is disabled to prevent re-entrance. Write to `EHN` to re-enable the mechanism with `AMK - EHN $01 EHN`.

- Address: `&04`
- Type: Flag CSR
- Read value: written value of `EHN`
- Read side effect: none
- Write value: the entry address of the exception handler routine
- Write side effect: re-enable exception handling
- Example: framework of the exception handler

```RTMQ
CHI - EHN #EXCHND
CLO - EHN #EXCHND  % assign the exception handler
...
...
#EXCHND:
CSR - $20 LNK      % save the return address
CSR - $21 EXC      % save the exception flags
...                % exception handling
...
AMK - EHN $01 EHN  % re-enable exception handling
AMK - PTR 2.0 $20  % return
```

### `STK` Register

`STK` register controls the address offset of the TCS. When TCS entries `$20` ~ `$FF` are accessed, their physical addresses are offset with the value of `STK`.

- Address: `&05`
- Type: Numeric CSR
- Read value: written value of `STK`
- Read side effect: none
- Write value: the address offset of the TCS
- Write side effect: none
- Example: push data into the TCS

```RTMQ
GLO - $20 0x1234
GLO - $21 0x5678
GLO - $22 0xABCD
AMK - STK 3.0 3   % advance the stack offset
```

- Example: pop data from the TCS

```RTMQ
AMK P STK 3.0 -3   % reduce the stack offset and wait for valid data
CSR - $20 &AB
CSR - $21 &CD
CSR - $22 &EF
```
