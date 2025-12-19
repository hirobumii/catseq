# Generic Quantum Experiment Control Platform - Reconfigurable Signal Processor

by Zhang Junhua

Rev.0.0 - 2025.11.21

## Introduction

The reconfigurable signal processor (RSP) module is a general-purpose DSP tool box, that is designed to fulfill various DSP needs in the lab, like PID, lock-in amp, digital filter, digital FM/AM/PM, I/Q modulation / demodulation, etc. The RSP module consists of a variety of DSP units that are connected with a crossbar matrix, and the processing of the signal is fully pipelined.

One of the highlights of the RSP module is that, the reconfiguration overhead can be as low as dozens of nano-seconds. And with the power of RTMQ framework, the functioning of the module can be in precise synchronization with the experiment timing sequence.

## Ports

| Name     | Function |
|:--------:|:---------|
| AI0, AI1 | 2 analog input ports, 125 MSps, 2 Vpp with optional -10 ~ +10 V DC offset |
| AO0, AO1 | 2 analog output ports, 250 MSps, 2 Vpp with -10 ~ +10 V DC offset |
| RF0, RF1 | 2 RF output ports, 1 GSps, 0.1 ~ 400 MHz, +10 dBm max. |
| IO0, IO1 | 2 digital I/O ports, 3.3 V TTL |
| DBG      | Debug port (reserved) |

## RTLink Channels

### Local Channels

| Number | Function |
|:------:|:---------|
|   #0   | RT-Core  |
|   #1   | 10 Mbps UART to the host computer (for standalone chassis only) |
|   #2   | UART debug port |
|   #3   | ARM co-processor |

### Remote Channels

| Number | Function |
|:------:|:---------|
|   #0   | To master module (6U chassis) / RTLink over Ethernet (standalone chassis) |

## Node Parameters

| Parameter | Value | Comment |
|:---------:|:-----:|:--------|
| T_EXT_MUL |   1   | ALU multiplier enabled |
| T_EXT_DIV |   1   | ALU divider enabled |
| T_EXT_SGN |   0   | Multiplier and divider are unsigned |
| W_ALU_STK |   12  | TCS capacity: 4096 entries |
| W_INS_RBF |   12  | Instruction cache ring buffer capacity: 4096 entries |
| N_CHN_LOC |   4   | Number of RTLink local channels |
| N_CHN_RMT |   1   | Number of RTLink remote channels |
| W_RBF_ADR |   9   | RTLink Rx buffer capacity: 512 frames |
| W_TBF_ADR |   9   | RTLink Tx buffer capacity: 512 frames |
| N_WPL_INS |   64  | Waiting pool capacity: 64 instructions |
| W_WPL_LTN |   18  | Max latency: 262079 cycles |
| W_SCP_ADR |   13  | Scratchpad memory capacity: 8192 frames |
| W_ICH     |   17  | Instruction cache capacity: 131072 instructions |
| W_DCH     |   19  | Data cache capacity: 512 kB |
| W_DCC     |   20  | Data cache address auto-increment counter width |

## DSP Units and Module Options

| Name  | Amount |  -C1  |  -C2  |  -C3  |  -C4  |  -C5  |  -P   |  -U   | Function |
|:-----:|:------:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|:---------|
| `MON` |    2   |   2   |   2   |   2   |   2   |   2   |   2   |   2   | Monitor, for probing the signal |
| `MUX` |    4   |   0   |   0   |   0   |   0   |   0   |   2   |   4   | Multiplexer |
| `RBF` |    4   |   2   |   2   |   2   |   2   |   2   |   2   |   4   | Ring buffer, for recording and playback |
| `FUN` |    4   |   0   |   0   |   0   |   0   |   0   |   2   |   4   | Arbitrary function, OUT = F(IN) |
| `DDS` |    8   |   2   |   2   |   2   |   3   |   4   |   6   |   8   | Direct digital synthesizer, with FM/PM |
| `MUA` |    8   |   4   |   4   |   6   |   6   |   6   |   8   |   8   | Mult-adder, with output hold and clamp |
| `MIX` |    8   |   0   |   1   |   0   |   1   |   2   |   4   |   8   | Arithmetic mixer, with +, -, *, min, max, abs, and delay line |
| `CNV` |    8   |   1   |   2   |   3   |   3   |   5   |   6   |   8   | Convolution, support FIR / IIR |
| `ACU` |    8   |   1   |   1   |   2   |   2   |   3   |   4   |   8   | Accumulator, with saturation clamp |
| `CKG` |    4   |   2   |   2   |   2   |   2   |   2   |   2   |   4   | Clock generator, for multi-rate application and pulse width modulation |
| `DGT` |   15   |  10   |  10   |  10   |  10   |  10   |  15   |  15   | Digital channel, for multiplexer and clock enable |
| `LGF` |    6   |   4   |   4   |   4   |   4   |   4   |   6   |   6   | Logical function, for digital channels |
| `HST` |    2   |   0   |   0   |   0   |   0   |   0   |   0   |   2   | Histogram |

- Add-on options:
  - **-X**: enable the instruction cache of the node, and so the precisely-timed reconfiguration ability, otherwise the module can only be configured with RTLink instruction frames.

## Architecture Overview

### DSP Unit

The RSP module is basically a network-on-chip (NoC) consists of various types of DSP units. A DSP unit has:

- 1 or more signal input ports
- 1 signal output port
- maybe some digital output ports, which can be processed with digital channels, `DGT`

The input signal of a signal input port is selected from a bus, which consists of:

- constant value from the dedicated configuration CSR for that port
- random number generator
- 2 analog input ports
- output signals of all the DSP units

For each signal input port, there is a signal valid flag, which can be selected from:

- write side effect trigger of the dedicated configuration CSR for that port
- 1 of 15 digital channels, `DGT0` ~ `DGTE`

For some types of DSP unit, the signal valid flag serves as the clock enable for that unit, please refer to the section for each type for details.

Each type of DSP unit is controlled with a series of CSR subfiles (exceptions will be mentioned later). Within each subfile, each unnamed CSR corresponds to an instance of the DSP unit. All these subfiles share the SFS address with the **FIRST** input port configuration subfile. Each input port configuration CSR has the following bit-field structure:

- `xxx[31:28]`: signal valid flag select
  - `0x0`: write side effect trigger of this CSR
  - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
- `xxx[25:20]`: input signal select
  - `0x00`: constant value `xxx[19:0]`, denoted as `REG`
  - `0x01`: 20-bit random number per clock cycle, denoted as `RND`
  - `0x02`: signal from AI0 port, denoted as `ADC0`
  - `0x03`: signal from AI1 port, denoted as `ADC1`
  - `0x04` ~ `0x07`: output of `MUX0` ~ `MUX3`
  - `0x08` ~ `0x0B`: output of `RBF0` ~ `RBF3`
  - `0x0C` ~ `0x0F`: output of `FUN0` ~ `FUN3`
  - `0x10` ~ `0x17`: output of `DDS0` ~ `DDS7`
  - `0x18` ~ `0x1F`: output of `MUA0` ~ `MUA7`
  - `0x20` ~ `0x27`: output of `MIX0` ~ `MIX7`
  - `0x28` ~ `0x2F`: output of `CNV0` ~ `CNV7`
  - `0x30` ~ `0x37`: output of `ACU0` ~ `ACU7`
- `xxx[19:0]`: constant input value

### Signal Format

Within the RSP module, the signal is represented with signed 20-bit fixed-point numbers, with 1 sign bit, 0 integer bit and 19 decimal bits. That is, `0x80000` ~ `0x7FFFF` corresponds to dimensionless interval `[-1, 1)`. But there are exceptions, for `RFG` and `CKG` units, the required signal is unsigned. So the input range `0x80000` ~ `0x7FFFF` corresponds to `[0, 2)`. Internally, the MSB of the input signal is first inverted before further processing. The reference Python code for converting dimensionless signal value to RSP format fixed-point number is as follows.

```Python
def rsp_signal(sig):
    sig = max(min(sig, 1), -1)
    ret = round(sig * 0x80000) & 0xFFFFF
    if (sig > 0) and (ret == 0x80000):
        return 0x7FFFF
    else:
        return ret
```

Moreover, the gains and coefficients that appear in DSP algorithms are represented with a simpler version of floating point numbers, as `{4-bit unsigned exponent, 16-bit signed mantissa}`. The coefficient is evaluated simply as `mantissa / (2**exponent)`. The reference Python code for converting the coefficient to RSP format is as follows.

```Python
def rsp_gain(gain):
    gain = max(min(gain, 0x7FFF), -0x8000)
    if gain == 0:
        return 0
    elif gain < 0:
        exp = min(15 - np.ceil(np.log2(-gain)), 15)
    elif gain > 0:
        exp = min(14 - np.floor(np.log2(gain)), 15)
    mts = round(gain * (2 ** exp)) & 0xFFFF
    exp = int(exp) & 0xF
    if mts == 0:
        return 0
    return (exp << 16) | mts
```

The reference Python code for converting RSP format signal and gain back to floating point number is as follows.

```Python
def rsp_signed(val, wid):
    msk = 1 << (wid - 1)
    return -(val & msk) | (val & (msk - 1))

def rsp_decode(val, typ="signal"):
    if typ == "signal":
        return rsp_signed(val, 20) / 0x80000
    elif typ == "gain":
        return rsp_signed(val, 16) / (2 ** (val >> 16))
```

## I/O Ports

### Analog Input

The analog frontend of an analog input port is as illustrated below. The 2 relays select the input coupling of the port. For AC coupling, the AC component of the input signal is directly sampled by the ADC, which has a maximum range of 2 Vpp. The sampled signals of both ADCs are then fed to the signal input bus as `ADC0` and `ADC1`. For DC coupling, an adjustable DC offset is subtracted from the signal before being sampled by the ADC. The DC offset can be set with DAC channels `DAC4` and `DAC5`, as will be detailed later.

Note that for the protection of the hardware, once the input signal exceeds the maximum range of 2 Vpp, the input path will be cut automatically by switching relay #1 to DC side and #2 to AC side. And the LED D3 and D2 would light up to indicate the out-of-range issue of port AI0 and AI1 respectively.

```TEXT
               +--> AC Cpl. ---------------+
              /                             \
AI0/1 --> Relay #1 <-- Sel.1    Sel.2 --> Relay #2 --> ADC0/1
              \                             /
               +--> DC Cpl. ---> DC Ofs. --+
                                  /
                               DAC4/5
```

### Analog Output

The output signal of an analog output port is the summation of 2 channels. The high bandwidth channel has a range of 2 Vpp, generated by `DAC0` or `DAC1`. And the DC offset channel has a range from -10 V to +10 V, generated by `DAC2` or `DAC3`.

### RF Output

The DDS used for the RF output port is AD9910 from Analog Device Inc., which is capable of flexible FM/AM/PM with a 16-bit parallel data port. In RSP module, the modulation signal comes from the DSP network. However, AD9910 takes the parallel port data as **UNSIGNED**, so the signal is converted from `[-1, 1)` to `[0, 2)` by inverting the MSB before output to the parallel data port.

For more information about the function and configuration of the DDS, please refer to the official documentations.

### Digital I/O

The digital I/O ports are in 3.3 V TTL standard. The input and output signals of the ports are connected to the DSP network through the digital channels (see **DSP Unit - Digital Channel** for details).

## CSR Specifications

### Platform CSR: `&12:LED` to `&17:RND`

These CSRs are common to all the modules in the platform, please refer to *Generic Quantum Experiment Control Platform - Master Module*. However, there are some minor differences:

- `LED[3:2]` controls the state of front panel LED D0 ~ D1.
- `MAC` subfile is functional only in the standalone chassis form.
- The SPI slaves:
  - `SPI.SLV[0]`: clock distribution chip
  - `SPI.SLV[1]`: user FLASH
  - `SPI.SLV[2]`: DDS chip for RF0 port
  - `SPI.SLV[3]`: DDS chip for RF1 port
  - `SPI.SLV[4]`: high speed DAC chip for AO1, AO0 port
  - `SPI.SLV[5]`: low speed DAC chip for DC offset of AO1, AO0 port
  - `SPI.SLV[6]`: low speed DAC chip for DC offset of AI1, AI0 port
  - `SPI.SLV[7]`: high speed ADC chip for AI1, AI0 port

### External Peripheral Control: `&18:LED_SRC` to `&1D:EXT_ADC`

#### `&18:LED_SRC`

`LED_SRC` register controls the signal source of the LEDs.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `LED_SRC[15:12]`: signal source of LED D0
    - `0x0`: `LED[3]`
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
  - `LED_SRC[11:8]`: signal source of LED D1
    - `0x0`: `LED[2]`
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
  - `LED_SRC[7:4]`: signal source of LED D2
    - `0x0`: out of range indicator for AI1 port
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
  - `LED_SRC[3:0]`: signal source of LED D3
    - `0x0`: out of range indicator for AI0 port
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
- Write side effect: none

#### `&19:EXT_DIO`

`EXT_DIO` register controls the behavior of IOx ports.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `EXT_DIO[13]`: direction of IO1
    - `0`: input
    - `1`: output
  - `EXT_DIO[12]`: optional output level of IO1
  - `EXT_DIO[11:8]`: output signal source select of IO1
    - `0x0`: `EXT_DIO[12]`
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
  - `EXT_DIO[5]`: direction of IO0
    - `0`: input
    - `1`: output
  - `EXT_DIO[4]`: optional output level of IO0
  - `EXT_DIO[3:0]`: output signal source select of IO0
    - `0x0`: `EXT_DIO[4]`
    - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
- Write side effect: none

#### `&1A:EXT_DDS`

`EXT_DDS` register contains the control signals for AD9910.

- Type: Flag CSR
- Read value:
  - `EXT_DDS[31]`: SYNC_SAMP_ERR state of RF1
  - `EXT_DDS[30]`: SYNC_SAMP_ERR state of RF0
  - `EXT_DDS[29:0]`: written value
- Read side effect: none
- Write value:
  - `EXT_DDS[27:20]`: fine delay tap of signals, **for developers only**
  - `EXT_DDS[19]`: MASTER_RESET signal for RF1
  - `EXT_DDS[18]`: MASTER_RESET signal for RF0
  - `EXT_DDS[17]`: I/O_RESET signal for RF1
  - `EXT_DDS[16]`: I/O_RESET signal for RF0
  - `EXT_DDS[15]`: SYNC_IN signal for RF1
  - `EXT_DDS[14]`: TxENABLE signal for RF1
  - `EXT_DDS[13:12]`: F signal for RF1
  - `EXT_DDS[11]`: I/O_UPDATE signal for RF1, auto-reload to 0
  - `EXT_DDS[10:8]`: PROFILE signal for RF1
  - `EXT_DDS[7]`: SYNC_IN signal for RF0
  - `EXT_DDS[6]`: TxENABLE signal for RF0
  - `EXT_DDS[5:4]`: F signal for RF0
  - `EXT_DDS[3]`: I/O_UPDATE signal for RF0, auto-reload to 0
  - `EXT_DDS[2:0]`: PROFILE signal for RF0
- Write side effect: none

#### `&1B:DDS_MON`

`DDS_MON` register is the clock signal monitor for AD9910.

- Type: Flag CSR
- Read value:
  - `DDS_MON[31:24]`: PDCLK of RF1
  - `DDS_MON[23:16]`: SYNC_CLK of RF1
  - `DDS_MON[15:8]`: PDCLK of RF0
  - `DDS_MON[7:0]`: SYNC_CLK of RF0
- Read side effect: none
- Write value: (READ-ONLY)
- Write side effect: none

#### `&1C:EXT_DAC`

`EXT_DAC` register contains the control signals for the external DAC chips.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `EXT_DAC[24:20]`: fine delay tap of signals, **for developers only**
  - `EXT_DAC[3]`: reset signal for high bandwidth channel of AOx
  - `EXT_DAC[2]`: DAC clock synchronization
  - `EXT_DAC[1]`: reset signal for DC offset of AIx
  - `EXT_DAC[0]`: reset signal for DC offset of AOx
- Write side effect: none

#### `&1D:EXT_ADC`

`EXT_ADC` register contains the control signals for the external ADC chips.

- Type: Flag CSR
- Read value:
  - `EXT_ADC[31:20]`: written value
  - `EXT_ADC[19:10]`: clock signal monitor for AI1
  - `EXT_ADC[9:0]`: clock signal monitor for AI0
- Read side effect: none
- Write value:
  - `EXT_ADC[31:30]`: interpolation filter type of AI1
    - `00`: isolated, switch the relays to protection state
    - `01`: hold last value
    - `10`: raised cosine, filter tap: `[-0.03125, 0, 0.28125, 0.5, 0.28125, 0, -0.03125]`
    - `11`: sinc, filter tap: `[-0.09375, 0, 0.28125, 0.4375, 0.28125, 0, -0.09375]`
  - `EXT_ADC[29]`: channel coupling of AI1
    - `0`: AC coupling
    - `1`: DC coupling
  - `EXT_DAC[28:26]`: fine delay tap of signals, **for developers only**
  - `EXT_ADC[25:24]`: interpolation filter type of AI0
    - `00`: isolated, switch the relays to protection state
    - `01`: hold last value
    - `10`: raised cosine
    - `11`: sinc
  - `EXT_ADC[23]`: channel coupling of AI0
    - `0`: AC coupling
    - `1`: DC coupling
  - `EXT_DAC[22:20]`: fine delay tap of signals, **for developers only**
  - `EXT_ADC[1]`: ADC input protection override
    - `0`: enable protection, isolate the channel when input signal is out of range
    - `1`: disable protection, **USE AT YOUR OWN RISK**
  - `EXT_ADC[0]`: SYNC signal for the ADC
- Write side effect: none

### DSP Unit - External DAC: `&1E:DAC_INP`

This unit interfaces the internal signal to the external DACs. Input signal `[-1, 1)` corresponds to the full output range of each DAC channel.

- Name: `DAC`
- Number of instances: 6
- `&1E:DAC_INP`: input port configuration subfile
  - `DAC_INP.&00`: high bandwidth component of AO0, -1 ~ +1 V
  - `DAC_INP.&01`: high bandwidth component of AO1, -1 ~ +1 V
  - `DAC_INP.&02`: DC offset of AO0, -10 ~ +10 V
  - `DAC_INP.&03`: DC offset of AO1, -10 ~ +10 V
  - `DAC_INP.&04`: DC offset of AI0, -10 ~ +10 V
  - `DAC_INP.&05`: DC offset of AI1, -10 ~ +10 V

More specifically:

- `AO0 = DAC0 + DAC2`
- `AO1 = DAC1 + DAC3`
- `ADC0 = AI0 - DAC4`
- `ADC1 = AI1 - DAC5`

### DSP Unit - External DDS Modulation: `&1F:RFG_INP`

This DSP unit connects the internal signal to the parallel data port of the external DDS of the RFx port. So that the generated RF signal's frequency, amplitude or phase can be modulated. The input signal is first converted to unsigned interval `[0, 2)`, by inverting the MSB, then the 16 MSBs are output to the parallel data port.

- Name: `RFG`
- Number of instances: 2
- `&1F:RFG_INP`: input port configuration subfile
  - `RFG_INP.&00`: modulation signal for RF0
  - `RFG_INP.&01`: modulation signal for RF1

### DSP Unit - Monitor: `&20:MON_INP` to `&22:MON1`

As the name suggests, this unit is used to connect the output signal of a DSP unit to the CSR space, so that the RT-Core can easily access.

- Name: `MON`
- Number of instances: 2
- `&20:MON_INP`: input port configuration subfile
- `&21:MON0`: probed signal of unit `MON0`, sign-extended to 32 bits, READ-ONLY
- `&22:MON1`: probed signal of unit `MON1`, sign-extended to 32 bits, READ-ONLY

### DSP Unit - Multiplexer: `&23:MUX_IPA` to `&24:MUX_IPB`

Each multiplexer unit has 2 input ports, `IPA` and `IPB`, and the output signal is selected according to the signal valid flag of both ports. This unit can be used to implement various digital modulation, like FSK/PSK, or to generate rectangular wave with arbitrary level.

- Name: `MUX`
- Number of instances: 4
- `&23:MUX_IPA`: `IPA` port configuration subfile
- `&24:MUX_IPB`: `IPB` port configuration subfile
- Output of the unit regarding the signal valid flags:
  - `IPA.valid == 0, IPB.valid == 0`: `0`
  - `IPA.valid == 1, IPB.valid == 0`: `IPA`
  - `IPA.valid == 0, IPB.valid == 1`: `IPB`
  - `IPA.valid == 1, IPB.valid == 1`: `(IPA + IPB) / 2`

### DSP Unit - Ring Buffer: `&25:RBF_INP` to `&29:RBF_PBK`

The ring buffer is used for signal recording and playback. It can be used to implement oscilloscope or arbitrary waveform generator.

- Name: `RBF`
- Number of instances: 4
- `&25:RBF_INP`: input port configuration subfile
  - Signal valid flag of this port is used as write enable of the buffer.
- `&26:RBF_OUT`: output subfile of the buffers
  - Read value: current output of the buffer, sign-extended to 32 bits
  - Read side effect: read acknowledge of the buffer (optional)
  - Write value: (READ-ONLY)
  - Write side effect: none
- `&27:RBF_WRA`: write pointer subfile
  - Read value:
    - `RBF_WRA[15:0]`: current write pointer of the buffer
  - Read side effect: none
  - Write value:
    - `RBF_WRA[15:0]`: set value of the write pointer
  - Write side effect: set the write pointer to the written value
  - **NOTE:** each cycle when the write enable is asserted, the input signal is written to the current write pointer, and the pointer advances by 1. When the write pointer reaches `0xFFFF`, it wraps around to `0x0000`.
- `&28:RBF_RDA`: read pointer subfile
  - Read value:
    - `RBF_RDA[19:16]`: written value
    - `RBF_RDA[15:0]`: current read pointer of the buffer
  - Read side effect: none
  - Write value:
    - `RBF_RDA[19:16]`: read acknowledge select
      - `0x0`: `RBF_OUT` read side effect trigger
      - `0x1` ~ `0xF`: digital channel `DGT0` ~ `DGTE`
    - `RBF_RDA[15:0]`: set value of the read pointer
  - Write side effect: set the read pointer to the written value
  - **NOTE:** each cycle when the read acknowledge is asserted, the read pointer advances by 1, and the output signal is updated accordingly, with a fixed pipeline delay. For reading the content through `RBF_OUT`, wait at least **10** cycles between adjacent reads for the next sample to appear. When the read pointer reaches the playback higher bound, `RBF_PBK[31:16]`, it wraps around to the lower bound, `RBF_PBK[15:0]`.
- `&29:RBF_PBK`: playback bound subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `RBF_PBK[31:16]`: playback higher bound, inclusive
    - `RBF_PBK[15:0]`: playback lower bound, inclusive
  - Write side effect: none

### DSP Unit - Arbitrary Function: `&2A:FUN_INP` to `&2C:FUN_VAL`

The arbitrary function unit implements a function, `FUN = F(INP)`, from `[-1, 1)` to `[-1, 1)`, which can be used to realize special signal modulation or distortion. The function is evaluated with look-up table (LUT) and 1st order Taylor expansion. The 12 MSBs of the input signal are used as the index to the LUT, and the 8 LSBs are used as delta. Note that both the index and the delta are considered **signed**. The reference Python code for processing a user defined function is as follows. In order to load the function, successively write each element in `drv` and `val` into subfile `FUN_DRV` and `FUN_VAL` respectively.

```Python
def fun_load(func):
    sz = 4096  # number of entries in the LUT
    # delta=0 corresponds to the middle point of each interval
    val = list(func(np.linspace(-1, 1, sz, False) + 1/sz))
    # handle the signedness of the index
    val = val[sz//2:] + val[0:sz//2]
    itv = func(np.linspace(-1, 1, sz+1, True))
    drv = list((itv[1:] - itv[0:-1]) * sz / 2)
    drv = drv[sz//2:] + drv[0:sz//2]
    for i in range(sz):
        # values to be loaded to CSR FUN_DRV
        drv[i] = rsp_gain(drv[i])
        # values to be loaded to CSR FUN_VAL
        val[i] = (i << 20) | rsp_signal(val[i])
    return drv, val
```

- Name: `FUN`
- Number of instances: 4
- `&2A:FUN_INP`: input port configuration subfile
- `&2B:FUN_DRV`: function derivative input subfile
  - Read value: (WRITE-ONLY)
  - Read side effect: none
  - Write value:
    - `FUN_DRV[19:0]`: derivative, in gain format
  - Write side effect: none
- `&2C:FUN_VAL`: function value input subfile
  - Read value: (WRITE-ONLY)
  - Read side effect: none
  - Write value:
    - `FUN_VAL[31:20]`: address of the target LUT entry
    - `FUN_VAL[19:0]`: function value
  - Write side effect: write the derivative and the value to the target LUT entry

### DSP Unit - DDS: `&2D:DDS_IPF` to `&30:DDS_FTW`

The DDS unit generates sawtooth or sine waves with frequency modulation from `IPF` port and phase modulation from `IPP` port. The relation between the frequency tuning word `FTW` and the frequency `frq` in **MHz** is:

```TEXT
FTW = round( (frq / 250) * 2^32 )
```

And the final FTW into the DDS core, including modulation, is:

```TEXT
FTW_final = DDS_FTW[31:0] + (IPF << DDS_CFG[3:0])
```

For the phase modulation, input signal `[-1, 1)` from port `IPP` corresponds to phase offset `[-Pi, Pi)`.

- Name: `DDS`
- Number of instances: 8
- `&2D:DDS_IPF`: `IPF` port configuration subfile
  - Signal valid flag of this port is used as phase accumulator enable. Each cycle if the enable flag is high, the accumulator advances by `FTW_final`.
- `&2E:DDS_IPP`: `IPP` port configuration subfile
- `&2F:DDS_CFG`: DDS control subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `DDS_CFG[5]`: phase accumulator clear flag
      - `0`: normal operation
      - `1`: clear phase accumulator
    - `DDS_CFG[4]`: output waveform select
      - `0`: sine wave
      - `1`: sawtooth wave / phase
    - `DDS_CFG[3:0]`: exponent of the frequency modulation gain
  - Write side effect: none
- `&30:DDS_FTW`: base FTW subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `DDS_FTW[31:0]`: base FTW
  - Write side effect: none

### DSP Unit - Mult-adder: `&31:MUA_INP` to `&35:MUA_CPH`

As the name suggests, the mult-adder unit simply implements `MUA = A * INP + B`, but with additional features like output hold and clamp. The input signal valid flag is used for output hold. The output signal keeps updating if the valid flag is asserted, otherwise it holds the last value. The output clamp feature limits the output signal to a range defined by `MUA_CPL` and `MUA_CPH`. There are also 3 digital output ports, `MUA.LO`, `MUA.HI` and `MUA.MD`, each asserts when the output signal is below `MUA_CPL`, above `MUA_CPH` and in between (inclusive), respectively.

- Name: `MUA`
- Number of instances: 8
- `&31:MUA_INP`: input port configuration subfile
  - Signal valid flag of this port is used for output hold.
- `&32:MUA_GAN`: gain subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `MUA_GAN[19:0]`: coefficient `A`, in gain format
  - Write side effect: none
- `&33:MUA_OFS`: offset subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `MUA_OFS[19:0]`: offset `B`
  - Write side effect: none
- `&34:MUA_CPL`: low clamp subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `MUA_CPL[19:0]`: low output limit, lower output values are limited to this value, and `MUA.LO` asserts
  - Write side effect: none
- `&35:MUA_CPH`: high clamp subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `MUA_CPH[19:0]`: high output limit, higher output values are limited to this value, and `MUA.HI` asserts
  - Write side effect: none

### DSP Unit - Arithmetic Mixer: `&36:MIX_IPA` to `&38:MIX_CFG`

The arithmetic mixer unit implements arithmetic operations between 2 signals, `IPA` and `IPB`. Supported operations are `+`, `*`, `min` and `max`, and each signal can optionally take absolute value and/or be negated first. For `IPB` there is also an adjustable delay line, to compensate the processing latency difference between the 2 signals. There is also a digital output port `GT` for comparing the 2 signals. The function of the unit can be summarized as below. Note that in any case the output signal is limited to `[-1, 1)` and saturates at the boundary.

```TEXT
MIX_add = OPA + OPB
MIX_mul = OPA * OPB
MIX_min = min(OPA, OPB)
MIX_max = max(OPA, OPB)

MIX = MIX_xxx >> MIX_CFG[10:6]
MIX.GT = (OPA > OPB)

      / IPx
OPx = | abs(IPx)
      | -IPx
      \ -abs(IPx)
```

- Name: `MUA`
- Number of instances: 8
- `&36:MIX_IPA`: `IPA` port configuration subfile
- `&37:MIX_IPB`: `IPB` port configuration subfile
- `&38:MIX_CFG`: mixer control subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `MIX_CFG[19:12]`: input delay tap of `IPB`, in clock cycles
    - `MIX_CFG[10:6]`: output attenuation, in number of right shift bits
    - `MIX_CFG[5:4]`: arithmetic operation select
      - `00`: `OPA + OPB`
      - `01`: `OPA * OPB`
      - `10`: `min(OPA, OPB)`
      - `11`: `max(OPA, OPB)`
    - `MIX_CFG[3:2]`: negation option of `IPB`
      - `00`: `OPB = IPB`
      - `01`: `OPB = abs(IPB)`
      - `10`: `OPB = -IPB`
      - `11`: `OPB = -abs(IPB)`
    - `MIX_CFG[1:0]`: negation option of `IPA`
      - `00`: `OPA = IPA`
      - `01`: `OPA = abs(IPA)`
      - `10`: `OPA = -IPA`
      - `11`: `OPA = -abs(IPA)`
  - Write side effect: none

### DSP Unit - Convolution: `&39:CNV_INP` to `&3B:CNV_KRN`

The convolution unit is used to implement FIR or IIR filter. Its function can be summarized as:

```TEXT
S = K[0]*Y[n-p-1] + K[1]*Y[n-p-2] + ... + K[A-1]*Y[n-p-A]
  + K[A]*X[n] + K[A+1]*X[n-1] + ... + K[A+B-1]*X[n-B+1]
  
Y[n] = S >> CNV_CFG[12:8]
```

In the above expression, `X[*]` are the input signal terms, `Y[*]` are the output signal feedback terms and `K[*]` are the coefficients of the kernel. The input signal valid flag is used as sampling enable. Each cycle when it is asserted, `X[*]` and `Y[*]` both shift in 1 sample. Note that:

- `A` is the feedback order, `A == 0` yields no feedback.
- The total length of the kernel, `A + B`, shall not be larger than **64**.
- Due to the pipeline latency, the feedback terms start from `Y[n-p-1]` instead of `Y[n-1]`, and `p = floor( 14 * F_samp / F_sys )`, in which `F_samp` is the sampling rate, and `F_sys = 250 MHz`.
- In any case, the output signal, `Y[n]`, is limited to `[-1, 1)` and saturates at the boundary.

The CSR specification is as follows.

- Name: `CNV`
- Number of instances: 8
- `&39:CNV_INP`: input port configuration subfile
  - Signal valid flag of this port is used as sampling enable.
- `&3A:CNV_CFG`: convolution unit control subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `CNV_CFG[17]`: kernel reset
      - `0`: normal operation
      - `1`: reset all kernel coefficients to 0
    - `CNV_CFG[16]`: signal path clear
      - `0`: normal operation
      - `1`: clear the signal path pipeline
    - `CNV_CFG[12:8]`: output attenuation, in number of right shift bits
    - `CNV_CFG[5:0]`: feedback order, `A`
  - Write side effect: none
- `&3B:CNV_KRN`: kernel coefficient input subfile
  - Read value: (WRITE-ONLY)
  - Read side effect: none
  - Write value:
    - `CNV_KRN[19:0]`: coefficient, in gain format
  - Write side effect: push the written value into the coefficient array
  - **NOTE:** the coefficient array should be input in reversed order, that is, `K[A+B-1]` the first, `K[0]` the last.

### DSP Unit - Accumulator: `&3C:ACU_INP` to `&3E:ACU_PRH`

The accumulator unit computes the summation of the input signal. Internally, the accumulator range is `[-1048576, 1048576)`, and saturates at the boundary. The accumulator can be preloaded, and the input signal valid flag serves as the accumulator enable. The accumulated value is attenuated according to `ACU_PRH[24:20]`, and then limited to `[-1, 1)` as output signal.

- Name: `ACU`
- Number of instances: 8
- `&3C:ACU_INP`: input port configuration subfile
  - Signal valid flag of this port is used as accumulator enable.
- `&3D:ACU_PRL`: subfile for lower segment of accumulator preload value
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `ACU_PRL[31:0]`: lower segment of accumulator preload value
  - Write side effect: preload the accumulator with `{ACU_PRH[7:0], ACU_PRL[31:0]}`
- `&3E:ACU_PRH`: subfile for higher segment of accumulator preload value
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `ACU_PRH[24:20]`: output attenuation, in number of right shift bits
    - `ACU_PRH[7:0]`: higher segment of accumulator preload value
  - Write side effect: none

### DSP Unit - Clock Generator: `&3F:CKG_IPI` to `&42:CKG_PRE`

The clock generator unit generates digital signal for multi-rate application of other DSP units like DDS or ACU. It can also be used for pulse-width modulation. This unit has only a digital output, `TH`. The function of the unit can be summarized as below.

```TEXT
ACC = ( sum(INC) + CKG_PRE[19:0] ) mod CKG_MAX[19:0]
CKG.TH = (ACC >= THR)

INC = IPI xor 0x80000
THR = IPT xor 0x80000
```

That is, the input signal `IPI` is first converted to unsigned interval `[0, 2)`, by inverting the MSB, then be accumulated and modulo `CKG_MAX`. If the result `ACC` is not less than `THR`, which is also unsigned, the digital output `CKG.TH` is high. By tuning the `IPI` signal, the frequency of the clock / PWM can be changed dynamically, and the duty cycle can be controlled through `IPT` signal.

- Name: `CKG`
- Number of instances: 4
- `&3F:CKG_IPI`: `IPI` port configuration subfile
  - Signal valid flag of this port is used as accumulator enable.
- `&40:CKG_IPT`: `IPT` port configuration subfile
- `&41:CKG_MAX`: modulo value subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `CKG_MAX[19:0]`: modulo value for the accumulator
  - Write side effect: none
- `&42:CKG_PRE`: accumulator preload value subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `CKG_PRE[19:0]`: preload value for the accumulator
  - Write side effect: preload the accumulator with the written value

### DSP Unit - Digital Channel: `&43:DGT_CFG` to `&44:DGT_OUT`

The outputs of digital channels are used by other DSP units as input port signal valid flags for multi-rate applications. Each digital channel unit selects one of other units' digital outputs as input, and processes the signal with edge sensitivity, latch and inversion logic to generate the output signal. The data path is detailed as below.

```TEXT
              DGT_CFG
  ---------\     |     /-- Both --\
  Digital --|    |    |--- Neg. ---|
  Output ---+== MUX --+            +---> Latch ---> Inversion ---> Digital
  Bus ------|         |--- Pos. ---|     High                      Channel
  ---------/           \-- Levl --/
```

- Name: `DGT`
- Number of instances: 15
- `&43:DGT_CFG`: digital channel configuration subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `DGT_CFG[11]`: inversion
      - `0`: output as is
      - `1`: invert the signal before output
    - `DGT_CFG[10]`: latch high
      - `0`: proceed as is
      - `1`: latch high
    - `DGT_CFG[9:8]`: edge sensitivity
      - `00`: high level sensitive (proceed as is)
      - `01`: positive edge sensitive (convert positive edge to 1-cycle pulse)
      - `10`: negative edge sensitive
      - `11`: both edge sensitive
    - `DGT_CFG[5:0]`: input signal select
      - `0x00`: constant `0`
      - `0x01`: constant `1`
      - `0x02`, `0x03`: input signal from IO0, IO1, denoted as `DIN0`, `DIN1`
      - `0x04` ~ `0x07`: digital output `CKG0.TH` ~ `CKG3.TH`
      - `0x08` ~ `0x0F`: digital output `MIX0.GT` ~ `MIX7.GT`
      - `0x10` ~ `0x17`: digital output `MUA0.LO` ~ `MUA7.LO`
      - `0x18` ~ `0x1F`: digital output `MUA0.MD` ~ `MUA7.MD`
      - `0x20` ~ `0x27`: digital output `MUA0.HI` ~ `MUA7.HI`
      - `0x28` ~ `0x2D`: digital output `LGF0.FN` ~ `LGF5.FN`
  - Write side effect: reset the latch of current digital channel
- `&44:DGT_OUT`: channel state **CSR** (not a subfile)
  - Read value:
    - `DGT_OUT[14:0]`: channel state of `DGTE` ~ `DGT0`
  - Read side effect: none
  - Write value: (READ-ONLY)
  - Write side effect: none

### DSP Unit - Logical Function: `&45:LGF_LUT` to `&46:LGF_OUT`

The logical function unit takes 5 digital channels as input, and generates 1 bit digital output to port `FN`. This unit can be used to realize complicated on/off behavior of other DSP units. The logical function is implemented as a 32-to-1 LUT, with the 5 input bits being the selection and subfile `LGF_LUT` storing the LUT. More specifically:

- `LGF0`, `LGF3` takes `{DGT4, DGT3, ..., DGT0}` as input
- `LGF1`, `LGF4` takes `{DGT9, DGT8, ..., DGT5}` as input
- `LGF2`, `LGF5` takes `{DGTE, DGTD, ..., DGTA}` as input
- `LGFx.FN = LGF_LUT.&0x[ input ]`

The reference Python code for converting a function to LUT data is as follows. Suppose the input function has signature `func(d4, d3, d2, d1, d0)`.

```Python
def lgf_lut(func):
    return sum([(func(*map(int, f"{i:05b}")) & 1) << i for i in range(32)])
```

- Name: `LGF`
- Number of instances: 6
- `&45:LGF_LUT`: LUT data subfile
  - Read value: written value
  - Read side effect: none
  - Write value:
    - `LGF_LUT[31:0]`: LUT data
  - Write side effect: none
- `&46:LGF_OUT`: digital output **CSR** (not a subfile)
  - Read value:
    - `LGF_OUT[5:0]`: output state of `LGF5` ~ `LGF0`
  - Read side effect: none
  - Write value: (READ-ONLY)
  - Write side effect: none

### DSP Unit - Histogram: `&47:HST_INP` to `&48:HST_OUT`

The histogram unit takes the 14 LSBs of the input signal, and counts the occurrence of the values (saturates at the maximum count of 65535). The input signal valid flag is used, only the samples with the flag asserted will be taken into account. For reading the counts, first set the input signal to the desired value with the valid flag de-asserted, wait at least **8** cycles, and then read the count from `HST_OUT`. For clearing the counts, first assert `HST_OUT[0]`, then run the input signal through the desired range to be cleared.

- Name: `HST`
- Number of instances: 2
- `&47:HST_INP`: input port configuration subfile
  - Signal valid flag of this port is used to qualify the samples.
- `&48:HST_OUT`: count output subfile
  - Read value:
    - `HST_OUT[15:0]`: count of occurrence of the input sample
  - Read side effect: none
  - Write value:
    - `HST_OUT[0]`: count clear flag
      - `0`: normal operation
      - `1`: clear the count of the input sample
  - Write side effect: none

### DSP Unit Overflow Indicator: `&49:OVF`

For some DSP units, overflow may occur during the signal processing. Although the output signal is still limited to `[-1, 1)`, it is no longer reliable. When an overflow event occurs, it is registered in the `OVF` register. And it is optional to further trigger the exception channel of the RT-Core.

- Type: Flag CSR
- Read value: overflow flags of the corresponding DSP units, latch high
  - `OVF[31:24]`: `ACU7` ~ `ACU0`
  - `OVF[23:16]`: `CNV7` ~ `CNV0`
  - `OVF[15:8]`: `MIX7` ~ `MIX0`
  - `OVF[7:0]`: `MUA7` ~ `MUA0`
- Read side effect: none
- Write value:
  - `OVF[31:0]`: overflow exception handling enable of the corresponding DSP units
    - `0`: only register the overflow event, no further handling
    - `1`: enable the overflow exception handling, if any DSP unit with exception handling enabled overflows, the exception channel #9 of the RT-Core will be triggered.
- Write side effect: clear all registered overflow flags

## Resume Request Channels

- #0 ~ #2: StdCohNode channels
- #3: standalone chassis 10 Mbps UART interface idle
- #4: debug port idle
- #5: co-processor resume request (currently unused)
- #6: SPI transaction complete
- #7: IO0 external trigger, positive edge sensitive
- #8: IO1 external trigger, positive edge sensitive

## Exception Flags

- #0 ~ #7: StdCohNode flags
- #8: PLL lock lost
- #9: DSP unit overflow
- #A: AI0 out of range
- #B: AI1 out of range
