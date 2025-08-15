# Generic Quantum Experiment Control Platform - Real-time Waveform Generator

by Zhang Junhua

Rev.0.1 - 2025.05.19

## Introduction

The real-time waveform generator (RWG) module is a 4-channel RF source that is capable of generating complicated RF waveforms in real-time. Unlike ordinary arbitrary waveform generators (AWG), that waveform data is generated point-by-point by the host and then downloaded to the device, which consumes a significant amount of time, the RWG only requires parameterized description, and the waveform is generated on-the-fly. It is especially useful in scenarios that require low-latency and complicated feedback control like quantum error correction (QEC).

The RWG module is capable of generating up to 128 tones simultaneously in a 100 MHz band tunable within 0.1 ~ 400 MHz. And each tone has independent frequency and amplitude nonlinear ramping capability, and frequency-dependent amplitude compensation capability.

## Ports

| Name      | Function |
|:---------:|:---------|
| IO0 ~ IO3 | 4 mark output ports (can be upgraded to GPIO ports) |
| RF0 ~ RF3 | 4 RF output ports, 1 GSps, 0.1 ~ 400 MHz, +10 dBm max. |
| DBG       | Debug port (reserved) |

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
| W_DCH     |   20  | Data cache capacity: 1 MB |
| W_DCC     |   20  | Data cache address auto-increment counter width |

## Module Options

- Basic options: maximum number of tones that each RF port can simultaneously generate
  - **RWG-F1**: 1 tone
  - **RWG-F2**: 2 tones
  - **RWG-F4**: 4 tones
  - **RWG-F8**: 8 tones
  - **RWG-F16**: 16 tones
  - **RWG-F32**: 32 tones
- Add-on options:
  - **-M**: tones can be arbitrarily assigned between RF ports (such that **RWG-F32-M** can generate at most 128 tones in 1 port)
  - **-S**: enable frequency and amplitude linear ramping capability for tones
    - **-SP**: enable nonlinear ramping
  - **-A**: AWG mode, playback waveform samples from the data cache, each port can be independently enabled / disabled
  - **-C**: upgrade MARK outputs to GPIO ports

## CSR Specifications

### Platform CSR: `&12:LED` to `&17:RND`

These CSRs are common to all the modules in the platform, please refer to *Generic Quantum Experiment Control Platform - Master Module*. However, there are some minor differences:

- `LED[7:0]` controls the state of front panel LED D7 ~ D0.
- `MAC` subfile is functional only in the standalone chassis form.
- There are 4 more SPI slaves:
  - `SPI.SLV[0]`: clock distribution chip
  - `SPI.SLV[4:1]`: DDS chip for RF3 ~ RF0 port

### GPIO Subsystem: `&18:TTL` to `&1D:TEV`

The GPIO subsystem functionality is enabled with **-C** option, and is implemented mostly the same as the master module, with exceptions that:

- There are only 4 channels.
- Mark outputs of RF3 ~ RF0 and written value of `TTL[3:0]` are first bitwise-ORed, then used as channel enables and output states.

### Auxiliary UART Receiver

When a GPIO port is configured as input, it can function as a UART receiver. This function provides a handy way of communication with other apparatus. Each port has a dedicated shift-in register as its own data buffer, and the baud rate can be individually configured.

### `&1E:UBR` Subfile

`UBR` subfile configures the baud rate of the auxiliary UART receivers. Each CSR corresponds to a GPIO port.

#### `&00` to `&03` (unnamed CSR)

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[11:0]`: baud rate clock divider, `baud_rate = 250 MHz / &xx[11:0]`
- Write side effect: none

### `&1F:UDA` Subfile

`UDA` subfile provides access to the received data of the auxiliary UART receivers:

- Port IO0: `&00` to `&3F`
- Port IO1: `&40` to `&7F`
- Port IO2: `&80` to `&BF`
- Port IO3: `&C0` to `&FF`

CSRs in `UDA` subfile are read-only. The most recent received byte is stored in the LSBs of each buffer, and the data is shifted towards MSB. As an example, the most recent received byte from IO1 is in `UDA.&40[7:0]`.

### RF Subsystem

The RF subsystem implements the primary functionality of the RWG module. Sideband generator (SBG) cores in the subsystem generate digital baseband signals according to waveform parameters. The baseband signals are then frequency up-converted and D/A converted to analog RF signals in external DDS.

The CSRs related to the RF subsystem are:

- `&20:DDS`: external DDS control
- `&21:SBG`: sideband generator control
- `&22:PDM`: baseband signal source select
- `&23:CDS`: external DDS and SBG configuration subfile
  - `&00` ~ `&0F`: baseband signal association control
  - `&10:DLY`: signal delay settings
  - `&11:SCA`: baseband signal scale
- `&24:POF`: initial phase / phase offset subfile
- `&25:FTE`: frequency ramping control subfile
- `&26:FT0` ~ `&29:FT3`: frequency ramping coefficient subfiles
- `&2A:APE`: amplitude ramping control subfile
- `&2B:AP0` ~ `&2E:AP3`: amplitude ramping coefficient subfiles
- `&2F:CMK`: frequency-dependent amplitude compensation data input mask subfile
- `&30:CFQ`: amplitude compensation data input - frequency
- `&31:CAM`: amplitude compensation data input - amplitude

A simplified data path of RF signal generation is as illustrated below. First, a single-tone baseband signal is generated in each SBG. `FTE`, `FT0` ~ `FT3` controls the frequency ramping behavior, then frequency is accumulated into phase, either reloaded or offset with `POF`, converted to sine wave, and finally rescaled with amplitude (with ramping behavior controlled by `APE`, `AP0` ~ `AP3`) and frequency-dependent compensation (with `CMK`, `CFQ` and `CAM` as data input interface) to form the SBG baseband signal.

```TEXT
   FT*          POF ---+    AP* ---> Amplitude
     \            \     \                \
  Frequency ---> Phase --+--> Sine -------x---> SBG Baseband
       \                                 /
        +---> Freq.Dep. Compensation ---+
                        /
  CMK --\              /
  CFQ ---+---> Compensation Data
  CAM --/
```

Then, for each RF port, the baseband signals from all the 128 SBGs are selected according to `CDS.&0x` registers, summed together, and finally rescaled with `CDS.SCA` to form a multi-tone baseband signal. Optionally, the baseband signal for each RF port can also come from the data cache, as selected by `PDM`.

```TEXT
        CDS.MX*       Data Cache --\
            \                       |
  SBG #00 ---#--\        PDM ---> (Mux) ---> RF Baseband
  SBG #01 ---#---|                  |
  ...     ---#---+===> Summation --/
  SBG #7E ---#---|        /
  SBG #7F ---#--/     CDS.SCA
```

Finally, the digital baseband signals are frequency up-converted and D/A converted to analog RF signals in external DDS and output to the RF ports.

```TEXT
RF Baseband ---> ( Freq. Up-conv. ---> D/A Conv. ) ---> RF Port
                  \                             /
                   +------ External DDS -------+
```

Parameters of the RF subsystem:

- Number of SBG: 128
- Frequency resolution: 32 bits
- Phase resolution: 20 bits
- Amplitude resolution: 20 bits
- Digital baseband resolution: 18 bits

### `&20:DDS`

`DDS` register contains the control signals for the external DDSs.

- Type: Flag CSR
- Read value:
  - `DDS[31:28]`: SYNC_SAMP_ERR states of external DDS #3 ~ #0
  - `DDS[27:0]`: written value
- Read side effect: none
- Write value:
  - `DDS[29]`: state of synchronizer to external DDSs
  - `DDS[28]`: synchronizer reset, `1` for reset
  - `DDS[27:24]`: master reset for DDS #3 ~ #0, `1` for reset
  - `DDS[23:20]`: SPI interface I/O reset for DDS #3 ~ #0, `1` for reset
    - auto reload to `0`
  - `DDS[19:16]`: TX_ENABLE signal to DDS #3 ~ #0
  - `DDS[15]`: IO_UPDATE signal to DDS #3
    - auto reload to `0`
  - `DDS[14:12]`: PROFILE signal to DDS #3
  - `DDS[11:8]`: IO_UPDATE and PROFILE signals to DDS #2
  - `DDS[7:4]`: IO_UPDATE and PROFILE signals to DDS #1
  - `DDS[3:0]`: IO_UPDATE and PROFILE signals to DDS #0
- Write side effect: none

### `&21:SBG`

`SBG` register contains the control signals for the SBGs.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `SBG[19:16]`: mark output to IO3 ~ IO0
  - `SBG[13]`: IO_UPDATE signal to DDS #3
    - When using SBGs, use this signal instead of `DDS[15]` so that the carrier phase reset is aligned.
    - auto reload to `0`
  - `SBG[12]`: parameter update (PAR_UPD) flag for SBSs associated to RF3
    - `1`: instruct the corresponding SBGs to load the parameters in subfile `&24:POF` ~ `&2E:AP3` into internal logic
    - auto reload to `0`
  - `SBG[9:8]`: IO_UPDATE and PAR_UPD flag for RF2
  - `SBG[5:4]`: IO_UPDATE and PAR_UPD flag for RF1
  - `SBG[1:0]`: IO_UPDATE and PAR_UPD flag for RF0
- Write side effect: none

### `&22:PDM`

`PDM` register controls the data source of the baseband signal to the RF ports.

- Type: Flag CSR
- Read value: written value
- Read side effect: none
- Write value:
  - `PDM[14:12]`: data source select for RF3
    - `0`: from associated SBGs
    - `1`: disabled (tied to all 0)
    - `2`: from data cache stream output `[15:0]`, 2 LSBs padded with 0
    - `3`: from data cache stream output `[31:16]`, 2 LSBs padded with 0
    - `4`: from data cache stream output `[7:0]`, 10 LSBs padded with 0
    - `5`: from data cache stream output `[15:8]`, 10 LSBs padded with 0
    - `6`: from data cache stream output `[23:16]`, 10 LSBs padded with 0
    - `7`: from data cache stream output `[31:24]`, 10 LSBs padded with 0
  - `PDM[10:8]`: data source select for RF2
  - `PDM[6:4]`: data source select for RF1
  - `PDM[2:0]`: data source select for RF0
- Write side effect: none
- **NOTE:** value `2` ~ `7` is only available with **-A** option.

### `&23:CDS` Subfile

`CDS` subfile stores parameters for SBGs and external DDSs that are not frequently modified.

#### `&00` ~ `&0F` (unnamed CSR)

These CSRs control the association of SBGs to the RF ports. For each port, 4 CSRs are combined into a 128-bit wide bit-string, with each bit corresponds to a SBG. If a SBG is associated to a RF port, then its baseband signal goes to that port, and it accepts control signals issued to that port. Note that a SBG can be associated to multiple RF ports.

- Read value: written value
- Read side effect: none
- Write value:
  - `&00[31:0]`: association flags for SBG #1F ~ #00 to RF0
  - `&01[31:0]`: association flags for SBG #3F ~ #20 to RF0
  - `&02[31:0]`: association flags for SBG #5F ~ #40 to RF0
  - `&03[31:0]`: association flags for SBG #7F ~ #60 to RF0
  - `&04` ~ `&07`: association flags for SBGs to RF1
  - `&08` ~ `&0B`: association flags for SBGs to RF2
  - `&0C` ~ `&0F`: association flags for SBGs to RF3
- Write side effect: none
- **NOTE:**
  - These CSRs are only functional with **-M** option.
  - Without **-M** option, SBG association is locked to:
    - SBG #1F ~ #00 to RF0
    - SBG #3F ~ #20 to RF1
    - SBG #5F ~ #40 to RF2
    - SBG #7F ~ #60 to RF3

#### `&10:DLY`

`DLY` register configures the delay taps of signals for timing alignment. **For experienced user only.**

- Read value: written value
- Read side effect: none
- Write value:
  - `DLY[30]`: half-cycle delay for IO_UPDATE signals, `1` for extra half-cycle delay
  - `DLY[29]`: half-cycle delay for baseband signals, `1` for extra half-cycle delay
  - `DLY[28]`: half-cycle delay for synchronizer signals, `1` for extra half-cycle delay
  - `DLY[19:16]`: delay tap for `PDM` to take effect
  - `DLY[15:8]`: delay tap for mark outputs
  - `DLY[7:0]`: delay tap for IO_UPDATE assertion from `SBG` register
- Write side effect: none

#### `&11:SCA`

`SCA` register controls the scale as baseband signals from multiple SBGs are summed. For each RF port, the baseband signals from associated SBGs are first summed then arithmetic right-shifted according to the setting in `SCA`.

- Read value: written value
- Read side effect: none
- Write value:
  - `SCA[27:20]`: carrier leakage compensation (for experienced user only)
  - `SCA[15:12]`: right-shift bits for RF3
  - `SCA[11:8]`: right-shift bits for RF2
  - `SCA[7:4]`: right-shift bits for RF1
  - `SCA[3:0]`: right-shift bits for RF0
- Write side effect: none

### Frequency and Amplitude Ramping

Each SBG is capable of generating a single-tone baseband signal with varying frequency and amplitude. Internally, the ramping behavior of frequency and amplitude is approximated with Taylor series to the 3rd order, expanded from the beginning of each waveform segment. The conversion from different orders of derivatives in SI unit to coefficients in machine unit is detailed as follows.

For the frequency, the conversion relationship can be summarized as:

```TEXT
Fi = round( D[f(t),i](t0) * (2^32 / 250) * (2^(2*Sf+5) / 250)^i )
```

In which, `F0` ~ `F3` are the 0th to 3rd order coefficients, `D[f(t),i](t0)` is the i-th order derivative of `f(t)` at `t = t0`, the beginning of a waveform segment. The frequency function `f(t)` is in **MHz**, and time `t` is in **us**. And `Sf` is the scale parameter for frequency.

For the amplitude, the relationship is similar:

```TEXT
Ai = round( D[a(t),i](t0) * (2^19 - 1) * (2^(2*Sa+5) / 250)^i )
```

Here the amplitude function `a(t)` is in unit of **FS (full-scale)**, hence the range is limited to **-1 ~ 1**.

With this approximation, the baseband signal is finally computed as:

```TEXT
s(t) = Comp[f(t)] * a(t) * cos[Int[f(t),t0] + p0 + pof]
```

Where `Comp[f(t)]` is the frequency-dependent compensation factor, `Int[f(t),t0]` is the integration of `f(t)` from `t = t0`, with `p0` being the initial phase, and `pof` is the phase offset.

The subfiles related to frequency and amplitude ramping are:

- `&24:POF`: initial phase / phase offset subfile
- `&25:FTE`: frequency ramping control subfile
- `&26:FT0` ~ `&29:FT3`: frequency ramping coefficient subfiles
- `&2A:APE`: amplitude ramping control subfile
- `&2B:AP0` ~ `&2E:AP3`: amplitude ramping coefficient subfiles

Each of these subfiles contains 128 unnamed CSRs, `&00` ~ `&7F`, each corresponds to a SBG.

**NOTE:**

- All these subfiles share the subfile selection address of `FTE`.
- After writing to these subfiles, the parameters are just stored. Only when the PAR_UPD flag (in `SBG`) is asserted for the associated RF port, will the parameters be loaded into SBG logic, indicating the beginning of a new waveform segment.
- After the assertion of the PAR_UPD flag, wait at least **14** clock cycles (2 `NOP P` instructions) before writing to these subfiles, such that the parameters are correctly loaded into the SBG.
- SBG #00 ~ #7F are grouped into 4 groups of 32, for basic option **RWG-Fx**, only the first `x` SBGs in each group are enabled.

### `&24:POF` Subfile

`POF` subfile stores the initial phase or phase offset for the SBGs, depending on the setting in `FTE` subfile.

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[19:0]`: initial phase / phase offset word for SBG #xx
  - value range `0x00000` ~ `0xFFFFF` maps to phase range `[0, 2pi)`
- Write side effect: none

### `&25:FTE` Subfile

`FTE` subfile configures all parameters related to frequency and phase other than coefficients.

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[31:28]`: coefficient load flag for the 3rd to 0th order (`F3` ~ `F0`)
    - `0`: the frequency function is continuous at the corresponding order at the beginning of the next waveform segment, no need to load new coefficient value
    - `1`: new value of coefficient should be loaded
  - `&xx[27:25]`: highest non-zero order flag, indicating the highest order with non-zero coefficient
    - `100`: the 3rd order
    - `010`: the 2nd order
    - `001`: the 1st order
    - `000`: the 0th order (even if the coefficient of the 0th order is also 0)
    - all other values are illegal
  - `&xx[24]`: scale changed flag
    - `0`: the highest non-zero order flag (`FTE.&xx[27:25]`) and the scale parameter (`FTE.&xx[22:20]`) for the next waveform segment are the same as current one
    - `1`: any of the 2 parameters are different
  - `&xx[22:20]`: scale parameter `Sf`, can be `0` ~ `7`
  - `&xx[5]`: phase dithering enable flag (experimental feature)
    - default value: `0`
  - `&xx[4]`: phase accumulator reload flag
    - `0`: interpret `POF.&xx` as phase offset, load it to the phase offset register when PAR_UPD flag is asserted
    - `1`: interpret `POF.&xx` as initial phase, reload the phase accumulator with it and **reset the phase offset register to 0** when PAR_UPD flag is asserted
  - `&xx[3:0]`: phase dithering gain (experimental feature)
    - default value: `0`
- Write side effect: none

### `&26:FT0` ~ `&29:FT3` Subfile

Subfile `FT0` ~ `FT3` store the 0th ~ 3rd order coefficients for frequency ramping respectively (`F0` ~ `F3`, as computed in section *Frequency and Amplitude Ramping*).

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[31:0]`: frequency ramping coefficient for SBG #xx, signed
- Write side effect: none
- **NOTE:**
  - `FT1` is functional only with **-S** or **-SP** option.
  - `FT2` and `FT3` are functional only with **-SP** option.

### `&2A:APE` Subfile

`APE` subfile configures parameters related to amplitude ramping other than coefficients.

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[31:28]`: coefficient load flag for the 3rd to 0th order (`A3` ~ `A0`)
    - `0`: the amplitude function is continuous at the corresponding order at the beginning of the next waveform segment, no need to load new coefficient value
    - `1`: new value of coefficient should be loaded
  - `&xx[27:25]`: highest non-zero order flag, indicating the highest order with non-zero coefficient
    - `100`: the 3rd order
    - `010`: the 2nd order
    - `001`: the 1st order
    - `000`: the 0th order (even if the coefficient of the 0th order is also 0)
    - all other values are illegal
  - `&xx[24]`: scale changed flag
    - `0`: the highest non-zero order flag (`APE.&xx[27:25]`) and the scale parameter (`APE.&xx[22:20]`) for the next waveform segment are the same as current one
    - `1`: any of the 2 parameters are different
  - `&xx[22:20]`: scale parameter `Sa`, can be `0` ~ `7`
- Write side effect: none

### `&2B:AP0` ~ `&2E:AP3` Subfile

Subfile `AP0` ~ `AP3` store the 0th ~ 3rd order coefficients for amplitude ramping respectively (`A0` ~ `A3`, as computed in section *Frequency and Amplitude Ramping*).

- Read value: written value
- Read side effect: none
- Write value:
  - `&xx[19:0]`: amplitude ramping coefficient for SBG #xx, signed
- Write side effect: none
- **NOTE:**
  - `AP1` is functional only with **-S** or **-SP** option.
  - `AP2` and `AP3` are functional only with **-SP** option.

### Frequency-Dependent Amplitude Compensation

Other components used in the experiment system along with RWG modules may have non-uniform frequency response. The frequency-dependent amplitude compensation feature is designed to deal with this issue conveniently.

The compensation is implemented as a normalized factor, being a function of realtime baseband frequency `f(t)` that is approximated to the 1st order. Note that the compensation is done according to the baseband frequency, the final output frequency of the RF port depends also on the carrier frequency of the external DDS. So if the carrier frequency is changed, usually the compensation data should be updated.

The compensation data takes the form of a 1024-entry look-up table (LUT), covering baseband frequency range of -62.5 ~ +62.5 MHz. For each SBG the LUT is independent. However, since most of them would store identical data, the data input interface is designed to be a masked multiple input way.

Similar to `CDS.&0*`, the 4 CSRs in `CMK` subfile are combined to be a 128-bit mask, indicating whether the write operation is applicable to each SBG. The baseband frequency `F` is written to `CFQ`, while the compensation factor `C0[F]` and its 1st order derivative `C1[F]` are written to `CAM`. The conversion from SI unit data to machine unit parameters is as follows.

```TEXT
F = round( f * 8.192 )
C0[F] = round( c(f) * 1023 )
C1[F] = (C0[F+1] - C0[F-1]) / 8
```

In which, `f` is the baseband frequency in **MHz**, `c(f)` is the compensation factor (reciprocal of the measured frequency response) normalized to **0 ~ 1**.

### `&2F:CMK` Subfile

`CMK` subfile stores the write enable flags of compensation data to the SBGs. There are 4 unnamed CSRs in the subfile.

- Read value: N/A (write-only)
- Read side effect: none
- Write value:
  - `&00[31:0]`: write enable flags for SBG #1F ~ #00
    - `0`: disabled
    - `1`: enabled
  - `&01[31:0]`: write enable flags for SBG #3F ~ #20
  - `&02[31:0]`: write enable flags for SBG #5F ~ #40
  - `&03[31:0]`: write enable flags for SBG #7F ~ #60
- Write side effect: none

### `&30:CFQ`

`CFQ` is the frequency CSR of the compensation data input interface.

- Type: Flag CSR
- Read value: N/A (write-only)
- Read side effect: none
- Write value:
  - `CFQ[9:0]`: compensation frequency `F`, as computed in section *Frequency-Dependent Amplitude Compensation*
- Write side effect: none

### `&31:CAM`

`CAM` is the data CSR of the compensation data input interface.

- Type: Flag CSR
- Read value: N/A (write-only)
- Read side effect: none
- Write value:
  - `CAM[17:10]`: factor derivative `C1[F]`, as computed in section *Frequency-Dependent Amplitude Compensation*
  - `CAM[9:10]`: compensation factor `C0[F]`, as computed in section *Frequency-Dependent Amplitude Compensation*
- Write side effect: write `C0` and `C1` to entry `F` of the compensation data LUT, for each SBG with its corresponding write enable flag in `CMK` asserted.

## Resume Request Channels

- #0 ~ #2: StdCohNode channels
- #3: standalone chassis 10 Mbps UART interface idle
- #4: debug port idle
- #5: co-processor resume request (currently unused)
- #6: SPI transaction complete
- #7: GPIO external trigger

## Exception Flags

- #0 ~ #7: StdCohNode flags
- #8: PLL lock lost
