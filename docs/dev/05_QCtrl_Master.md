# Generic Quantum Experiment Control Platform - Master Module

by Zhang Junhua

Rev.0.3 - 2025.05.19

## Introduction

The master module is the communication and clock distribution hub of the chassis. It provides synchronized reference clocks and serves as an RTLink hub for the functional modules. The timing resolution of the master module, and also other functional modules, is **4 ns** (F_sys = 250 MHz).

## Ports

| Name   | Function |
|:------:|:---------|
| VHDCI  | 32 GPIO + 2 auxiliary trigger input port in VHDCI form |
| ETH    | Ethernet port of the ARM co-processor (currently unused) |
| RTLINK | RTLink over Ethernet, remote channel #0 of the node (currently unused) |
| USB    | USB 3.0 port to the host computer, local channel #1 of the node |
| OPT    | RTLink over 10GbE, remote channel #1 of the node (currently unused) |
| REFI   | External 10 MHz reference input |
| REFO   | 10 MHz reference output |
| DBG    | Debug port (reserved) |

## RTLink Channels

### Local Channels

| Number | Function |
|:------:|:---------|
|   #0   | RT-Core  |
|   #1   | USB 3.0 to the host computer |
|   #2   | UART debug port |
|   #3   | ARM co-processor |

### Remote Channels

| Number | Function |
|:------:|:---------|
|   #0   | RTLink over Ethernet |
|   #1   | RTLink over 10GbE |
|   #2   | To functional module slot #1 |
|   #3   | To functional module slot #2 |
|  ...   | ...      |
|   #13  | To functional module slot #12 |

**NOTE:** From left to right, the slots in the chassis are: 2 CPCI power source slots, functional module slots #1 ~ #6 (with default node address 1 ~ 6), master module slot (with default node address 0), and functional module slots #7 ~ #12 (with default node address 7 ~ 12).

## Node Parameters

| Parameter | Value | Comment |
|:---------:|:-----:|:--------|
| T_EXT_MUL |   1   | ALU multiplier enabled |
| T_EXT_DIV |   1   | ALU divider enabled |
| T_EXT_SGN |   0   | Multiplier and divider are unsigned |
| W_ALU_STK |   12  | TCS capacity: 4096 entries |
| W_INS_RBF |   12  | Instruction cache ring buffer capacity: 4096 entries |
| N_CHN_LOC |   4   | Number of RTLink local channels |
| N_CHN_RMT |   14  | Number of RTLink remote channels |
| W_RBF_ADR |   9   | RTLink Rx buffer capacity: 512 frames |
| W_TBF_ADR |   9   | RTLink Tx buffer capacity: 512 frames |
| N_WPL_INS |   64  | Waiting pool capacity: 64 instructions |
| W_WPL_LTN |   18  | Max latency: 262079 cycles |
| W_SCP_ADR |   13  | Scratchpad memory capacity: 8192 frames |
| W_ICH     |   17  | Instruction cache capacity: 131072 instructions |
| W_DCH     |   20  | Data cache capacity: 1 MB |
| W_DCC     |   20  | Data cache address auto-increment counter width |

## CSR Specifications

### `&12:LED`

`LED` register controls the state of the front panel LED D0 ~ D3.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `LED[3:0]`: state of LED D3 ~ D0
    - `0`: dark
    - `1`: bright
- Write side effect: none

### `&13:FAI`

Reserved CSR for firmware authentication.

### `&14:MAC` Subfile

`MAC` subfile controls the PHY module of the RTLink over Ethernet connection.

**WARNING:** In most cases the user should only access CSR `SRL`, `SRH`, `DSL` and `DSH`. Messing with the configurations may break the link and beyond recovery.

#### `&00:MDI`

`MDI` register handles the MDIO interface to the Ethernet PHY chip.

- Read value:
  - `MDI[31:16]`: written value
  - `MDI[15:0]`:
    - for write transaction, the transmitted data
    - for read transaction, the received data
- Read side effect: none
- Write value:
  - `MDI[31:30]`: ST field of the MDIO frame, should be `01`
  - `MDI[29:28]`: OP field of the MDIO frame
    - `10`: read transaction
    - `01`: write transaction
  - `MDI[27:23]`: PHY address field
  - `MDI[22:18]`: target register address field
  - `MDI[17:16]`: TA field, should be `10`
  - `MDI[15:0]`:
    - for write transaction, the transmitted data
    - for read transaction, ignored
- Write side effect: trigger MDIO frame send

#### `&01:DLY`

`DLY` register fine tunes the timing of the RGMII interface to the PHY chip.

- Read value: written value
- Read side effect: none
- Write value:
  - `DLY[7:4]`: Tx timing control
  - `DLY[3:0]`: Rx timing control
- Write side effect: none

#### `&02:CFG`

`CFG` register configures various parameters of the link.

- Read value: written value
- Read side effect: none
- Write value:
  - `CFG[31:28]`: gap bytes between RTLink Tx frames
  - `CFG[27:20]`: MDC clock divider
  - `CFG[19]`: PHY chip hardware reset
    - `0`: release reset
    - `1`: assert reset
  - `CFG[18]`: MDIO transaction type
    - `0`: write transaction
    - `1`: read transaction
  - `CFG[17]`: link type select
    - `0`: RTLink over Ethernet, the RTLink frame is wrapped as the payload of an Ethernet frame
    - `1`: bare RTLink, the RTLink frame is transmitted as-is
  - `CFG[16]`: link type switching mode
    - `0`: automatic switching, switches to the corresponding link type when a valid frame is received
    - `1`: manual switching, link type is selected according to `CFG[17]`
  - `CFG[15:0]`: EtherType field for RTLink over Ethernet
- Write side effect: none

#### `&03:SRL` and `&04:SRH`

`SRL` and `SRH` store the MAC address of the current node. Ignored if `CFG[17] == 1`.

- Read value: written value
- Read side effect: none
- Write value:
  - `SRH[15:0]`: higher 2 bytes of the MAC address
  - `SRL[31:0]`: lower 4 bytes of the MAC address
- Write side effect: none

#### `&05:DSL` and `&06:DSH`

`DSL` and `DSH` store the destination MAC address of RTLink over Ethernet frames. Ignored if `CFG[17] == 1`.

- Read value: written value
- Read side effect: none
- Write value:
  - `DSH[15:0]`: higher 2 bytes of the MAC address
  - `DSL[31:0]`: lower 4 bytes of the MAC address
- Write side effect: none

### `&15:CPR`

Not implemented yet, reserved for future.

### `&16:SPI` Subfile

`SPI` subfile handles the SPI configuration interface for external chips. For the master module, only the clock distribution chip is connected. When a transaction is finished, a resume request is generated in channel #6 (mask: "1.3").

#### `&00` to `&03` (unnamed CSR)

These are the SPI frame data registers, with `&03` storing the MSBs. Note that for write transaction, the data shall be MSB aligned, and the frame is shifted out from the MSB side. For read transaction, the received data is LSB aligned, that is, the frame is shifted in from the LSB side.

- Read value:
  - for write transaction, the content shall be ignored
  - for read transaction, the received data
- Read side effect: none
- Write value: the frame to be sent
- Write side effect: none

#### `&04:SLV`

`SLV` register controls the enable flags of the SPI slave channels. For write transaction, multiple slaves can be enabled, and the same frame is broadcasted to all of them, while for read transactions, each time only 1 slave can be enabled, or the data will be corrupted. For the master module, `SLV[0]` corresponds to the clock distribution chip.

- Read value: written value
- Read side effect: none
- Write value: enable flag for each channel
  - `0`: slave disabled
  - `1`: slave enabled
- Write side effect: none

#### `&05:CTL`

`CTL` register configures various parameters of the SPI interface.

- Read value: written value
- Read side effect: none
- Write value:
  - `CTL[31]`: SPI clock polarization (CPOL), i.e. idle state clock level
  - `CTL[30]`: SPI clock phase (CPHA), if `CPOL ^ CPHA == 0`, data shall be sampled at the pos-edge of the clock, and vise-versa
  - `CTL[29:20]`: SPI clock divider, `F_sck = F_sys / (CTL[29:20] + 1) / 2`
  - `CTL[19:16]`: MISO latency, in number of system clock cycles
  - `CTL[15:8]`: MOSI bit count, for read transaction, this is the length of the instruction part of the frame
  - `CTL[7:0]`: total bit count of the frame
- Write side effect: trigger SPI frame send

### `&17:RND`

`RND` register is the output of a true random number generator based on metastable states of the hardware. Each clock cycle the generator will generate 32 bits of random number.

- Type: Read-only CSR
- Read value: 32-bit random number
- Read side effect: none
- Write value: N/A
- Write side effect: none

### GPIO Subsystem

The GPIO subsystem provides digital output and input processing functions, including external trigger, event counter and time tagger.

The CSRs related to the GPIO subsystem are:

- `&18:TTL`: output level and input enable
- `&19:DIO`: port configuration subfile
  - `&00:DIR`: port direction
  - `&01:INV`: input inversion
  - `&02:POS`: pos-edge sensitivity
  - `&03:NEG`: neg-edge sensitivity
- `&1A:CTR`: counter array output/preload subfile
- `&1B:CSM`: counter sampling flags
- `&1C:TTS`: time tagger - time stamp
- `&1D:TEV`: time tagger - event flag

The data path of the GPIO subsystem is as illustrated below. The directions of the ports are controlled by `DIO.DIR`. For each input port, the registered input state is first inverted according to `DIO.INV` before proceeding to the sensitivity check (`DIO.POS` and `DIO.NEG`) and to the read value of `TTL`. Each time if the sensitivity criteria is met and the port is enabled (according to the written value of `TTL`), an event is registered for further processing. While for output ports, the output states are just the written value of `TTL`.

```TEXT
  DIO.DIR    DIO.INV    DIO.POS/NEG   TTL(wr)
      \          \            \           \
     Input ---> Invert ---> Sensitivity ---#---> Event
                   \
                 TTL(rd)

             DIO.DIR
                 \
  TTL(wr) ---> Output
```

For the external trigger logic, each time an event is registered in any enabled input port, a resume request is generated to channel #7 (mask: "2.3"). Specifically for the master module, there are 2 auxiliary trigger channels (TRG0 / TRG1), corresponding to resume request channel #8 and #9, and they are pos-edge sensitive.

```TEXT
  Port #00 Event --\
  Port #01 Event ---|
  ......         ---+=== Reduction OR ---> Rsm.Req #7
  Port #1E Event ---|
  Port #1F Event --/

  TRG0/1 ---> Pos.Edge ---> Rsm.Req #7/#8 (Master only)
```

For the event counter logic, each port has a dedicated counter channel. Each time an event is registered, the counter increases by 1. The counter can be preloaded by writing to its corresponding CSR in `CTR` subfile. Each time the corresponding bit in `CSM` is asserted, the value of the counter is sampled and the read value of `CTR` is updated.

```TEXT
           CTR(wr)   CSM
               \       \
  Event ---> Counter ---#---> CTR(rd)
```

For the time tagger logic, there is an associated timer and an event buffer (FIFO). When `TTS` is written, the timer is preloaded. Each time an event is registered in any enabled input port, a record is appended to the buffer, with time stamp from the timer and event flags of all the channels. If the buffer is full, new events will not be recorded. Each time `TEV` is read, the first record in the buffer is removed.

```TEXT
  TTS(wr) ---> Timer ---\
                         \                                /-- TTS(rd)
  Port #00 Event --\      +================#===> FIFO ===+
  Port #01 Event ---|    /                /       /       \-- TEV(rd)
  ......         ---+===+=== Reduc.OR ---+       /                \
  Port #1E Event ---|                           +----<<-----<<-----+
  Port #1F Event --/
```

Parameters of the GPIO subsystem:

- Number of GPIO ports: 32
- Counter width: 20 bits
- Time stamp width: 31 bits
- Time tagger event buffer capacity: 8192 entries

### `&18:TTL`

`TTL` register controls the output levels and input enables of the ports, each bit corresponds to 1 port.

- Type: Flag CSR
- Read value:
  - for output ports, the written value, i.e. current output level
  - for input ports, current input level after optional inversion
- Read side effect: none
- Write value:
  - for output ports, the output level, `1` for high (3.3V)
  - for input ports, the enable flag， `1` for enable
- Write side effect: none

### `&19:DIO` Subfile

`DIO` subfile controls the direction and sensitivity of the GPIO ports.

#### `&00:DIR`

`DIR` register controls the I/O direction of the ports, each bit corresponds to 1 port.

- Read value: written value
- Read side effect: none
- Write value: direction of each port
  - `0`: output
  - `1`: input
- Write side effect: none

**NOTE:** Specifically for the master module, the ports are organized in 4 groups of 8, the direction of the ports in a group shall be the same.

#### `&01:INV`

`INV` register controls the optional inversion of the input state, each bit corresponds to 1 port.

- Read value: written value
- Read side effect: none
- Write value: optional inversion of each port
  - `0`: input level is processed as-is
  - `1`: input level is first inverted then processed
- Write side effect: none

#### `&02:POS` and `&03:NEG`

`POS` and `NEG` register controls the edge sensitivity of the GPIO ports, each bit corresponds to 1 port.

- Read value: written value
- Read side effect: none
- Write value: for GPIO port #n, if `{POS[n], NEG[n]}` is:
  - `00`: high level sensitive
  - `01`: neg-edge sensitive
  - `10`: pos-edge sensitive
  - `11`: both-edge sensitive
- Write side effect: none

### `&1A:CTR` Subfile

`CTR` subfile contains the output and preload interfaces of the counter array, each counter corresponds to a GPIO port.

#### `&00` to `&1F` (unnamed CSR)

- Read value: counter output, 20-bit count value is sign-extended to 32 bits
- Read side effect: none
- Write value: counter preload value
- Write side effect: preload the corresponding counter with the written value

### `&1B:CSM`

`CSM` register controls the sampling of the counters, each bit corresponds to a counter.

- Type: Flag CSR
- Read value: irrelevant
- Read side effect: none
- Write value: sampling flag for each counter
  - `1`: sample the counter and update the corresponding `CTR.&xx`
  - auto-reload to `0`
- Write side effect: none
- **NOTE:** after writing to `CSM`, wait at least 6 cycles (write to `CSM` with `P` flag) before reading the corresponding CSR in `CTR` subfile.

### `&1C:TTS`

`TTS` register is the time stamp interface of the time tagger.

- Type: Flag CSR
- Read value:
  - `TTS[31]`: event buffer empty flag
    - `0`: the event buffer is not empty, current event record is valid
    - `1`: the event buffer is empty, `TTS[30:0]` is invalid, and `TEV` shall not be read
  - `TTS[30:0]`: time stamp of the first record in the event buffer
- Read side effect: none
- Write value: timer preload value
- Write side effect: preload the timer

### `&1D:TEV`

`TEV` register is the event flag interface of the time tagger.

- Type: Flag CSR
- Read value: event flag of the first record in the event buffer, each bit corresponds to a GPIO port. `1` indicates that an event is registered in this port. Note that events may be registered simultaneously in multiple ports.
- Read side effect: remove the first record from the event buffer
- Write value: irrelevant
- Write side effect: flush the event buffer

### `&1E:BPL`

`BPL` register controls the timing of communication to the functional modules. Messing with it may break the link to the functional modules.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `BPL[8]`: Tx clock synchronization flag
  - `BPL[7:4]`: Tx timing control
  - `BPL[3:0]`: Rx timing control
- Write side effect: none

## Resume Request Channels

- #0 ~ #2: StdCohNode channels
- #3: reserved
- #4: debug port idle
- #5: co-processor resume request (currently unused)
- #6: SPI transaction complete
- #7: GPIO external trigger
- #8: auxiliary trigger #0
- #9: auxiliary trigger #1

## Exception Flags

- #0 ~ #7: StdCohNode flags
- #8: PLL lock lost
