"""
OASM DSL function definitions.

This module contains the actual OASM DSL functions that will be called
when executing compiled sequences on the hardware.
"""
# Import actual OASM functions
from oasm.rtmq2 import sfs, amk, wait, send_trig_code, wait_rtlk_trig, asm, nop, P
from oasm.dev.rwg import fte, rwg, sbg
from oasm.dev.rsp import (
    dds_prof, dds_carrier, dds_signal, R, rsp_signal,
    mua_cph, mua_cpl, mua_gan, mua_ofs,
    acu_prh, acu_prl,
    mod_inp,
    mix_cfg,
    dgt_cfg,
    clo,
    cnv_cfg, cnv_pid,
    adc_ctrl,
    
)

from ..types.rwg import WaveformParams
from .mask_utils import binary_to_rtmq_mask
from ..types.rsp import RSPPIDConfig, RSPWaveformParams

def ttl_config(mask, dir):
    """配置 TTL 通道方向/初始化
    
    用于 TTL_INIT 操作，设置TTL通道的方向配置
    
    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101)
        dir: TTL 方向值，指定选中通道的方向 (binary format, e.g., 0b0001)
    """
    # Convert binary mask to RTMQ "A.B" format if possible
    rtmq_mask = binary_to_rtmq_mask(mask)
    
    # TTL direction uses registers $00 or $01
    # Convert dir value to appropriate register address
    if dir == 0:
        dir_reg = '$00'  # Register $00 for direction 0
    elif dir == 1:
        dir_reg = '$01'  # Register $01 for direction 1
    else:
        # For complex patterns, convert to RTMQ format
        dir_reg = binary_to_rtmq_mask(dir)
    
    sfs('dio', 'dir')
    amk('dio', rtmq_mask, dir_reg)
    
    # print("SFS - DIO DIR")
    # print(f"AMK - DIO {rtmq_mask} {dir_reg}")
    # print(f"  -> mask=0b{mask:08b}, dir=0b{dir:08b}")


def ttl_set(mask, state, board_type="main"):
    """根据板卡类型选择 TTL 控制方式

    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101)
        state: TTL 状态值，指定选中通道的输出状态 (binary format, e.g., 0b0001)
        board_type: 板卡类型 ("main" 或 "rwg")，默认为 "main"
    """
    # if board_type == "main":
        # Main 板卡：使用 TTL 寄存器（GPIO 子系统）
    rtmq_mask = binary_to_rtmq_mask(mask)
    rtmq_state = binary_to_rtmq_mask(state)
    amk('ttl', rtmq_mask, rtmq_state)
        # print(f"TTL_SET (Main) - mask={rtmq_mask}, state={rtmq_state}")
    # else:  # RWG 板卡
    #     # RWG 板卡：使用 SBG mark 位，避免与 IO_UPDATE 的流水线延迟错位
    #     sbg.ctrl(iou=0, pud=0, mrk=state & 0xF)
        # print(f"TTL_SET (RWG) - SBG mark bits: 0b{state & 0xF:04b}")

    # print(f"  -> mask=0b{mask:08b}, state=0b{state:08b}, board_type={board_type}")

def wait_mu(cycles):
    """等待指定机器周期数

    OASM wait(N) 的实现（验证结果）：
    - wait(N) 生成: CHI-TIM, CLO-TIM(N-1), AMK-EXC, AMK-RSM, NOP H
    - CLO-TIM 写入后立即启动 timer 倒计数
    - 总时长 = N cycles (OASM 内部已处理 overhead)

    时序示例 wait(128):
      Cycle 1: CHI-TIM (timer=0)
      Cycle 2: CLO-TIM 0x7F (timer=127, 启动倒计数)
      Cycle 3: AMK-EXC (timer=126)
      Cycle 4: AMK-RSM (timer=125)
      Cycle 5+: NOP H 暂停，timer 继续倒计数 125→0
      总计: 4 + 124 = 128 cycles ✓

    Args:
        cycles: 需要等待的机器周期数
    """
    if cycles <= 0:
        return

    # OASM wait() 已正确处理时序，无需减去 overhead
    # 对于极短等待（≤4 cycles），NOP 可能更高效
    if cycles <= 10:
        if cycles >=7:
            nop(1,P)
            cycles -=7
        nop(cycles)
    else:
        wait(cycles)

def wait_us(duration):
    """等待指定微秒数

    Args:
        duration: 等待时长（微秒）
    """
    # print(f"OASM: Wait {duration} μs")
    cycles = round(duration * 250)  # 250 MHz = 250 cycles/μs
    wait_mu(cycles)  # 使用 wait_mu 以支持短延时优化

def wait_master(cod=None):
    wait_rtlk_trig('c', cod or id(asm.intf))

def trig_slave(wait_time, cod=None):
    wait(wait_time)
    send_trig_code('ib', 0, 0, cod or id(asm.intf))

# --- RWG Placeholder Functions ---
def rwg_init(sca=(0,0,0,0), mux=(32,32,32,32)):
    rwg.rsm.on(spi=1)
    rwg.pdm.source(1, 1, 1, 1)
    rwg.cds.mux(sca,[((1<<mux[i])-1)<<sum(mux[:i]) for i in range(4)])
    rwg.rst_cic(0xF)

def rwg_set_carrier(chn: int, carrier_mhz: float):
    rwg.carrier(1<<chn, carrier_mhz, upd=True)

def rwg_rf_switch(ch_mask: int, state_mask: int):
    """Control RF switch via PDM register.
    
    Args:
        ch_mask: Channel mask indicating which RF ports to affect (binary format, e.g., 0b0101)
        state_mask: State mask indicating RF switch states for selected channels (binary format, e.g., 0b0001)
                   0 = RF enabled (from SBGs), 1 = RF disabled (tied to 0)
    """
    # Generate one AMK instruction per affected RF port
    for rf_port in range(4):  # RF0 to RF3
        if ch_mask & (1 << rf_port):  # This RF port is affected
            rf_state = 1 if (state_mask & (1 << rf_port)) else 0
            
            # Each RF port uses 3-bit field in PDM register: RF0=bits 2:0, RF1=bits 6:4, etc.
            # Use 7 (0b111) to mask the complete 3-bit field
            rtmq_mask = f"7.{rf_port * 2}"      # 7.0, 7.2, 7.4, 7.6
            rtmq_value = f"{rf_state}.{rf_port * 2}"  # rf_state at same position
            
            amk('PDM', rtmq_mask, rtmq_value)
            
    # print(f"RF_SWITCH - ch_mask=0b{ch_mask:04b}, state_mask=0b{state_mask:04b}")
    # print(f"  -> Affected RF ports: {[i for i in range(4) if ch_mask & (1 << i)]}")

def rwg_load_waveform(params: WaveformParams):
    """Load waveform parameters for a single SBG."""
    # User implementation will call rwg.frq() and rwg.amp()
    pha_rld: int = 1 if params.phase_reset else 0
    fte.cfg(params.sbg_id, 0, 0, pha_rld=pha_rld)
    rwg.frq(None, params.freq_coeffs, params.initial_phase, fct = params.fct)
    rwg.amp(None, params.amp_coeffs)

def rwg_play(pud_mask: int, iou_mask: int):
    """Trigger the waveform playback."""
    sbg.ctrl(iou=0, pud=pud_mask, mrk=0)


# ----- RSP Placeholder Functions -----
def rsp_set_carrier(chn:int, carrier:float):
    # config rfg
    dds_prof(1<<chn, 0, carrier, 0.0, 0.0)
    dds_carrier(1<<chn, carrier)
    dds_signal()

def rsp_init(offset_0 = 0.0, offset_1 = 0.0, flt_typ='rr', chn_cpl='dd'):
    # config adc
    ofs0 = offset_0/10
    ofs1 = offset_1/10
    dly = 0b000000
    # flt_typ = ("i" + flt) if chn == 0 else (flt + "i")
    # chn_cpl = ("a" + cpl) if chn == 0 else (cpl + "a")
    R.dac_inp[4+0] = mod_inp("reg", "reg", rsp_signal(ofs0))
    R.dac_inp[4+1] = mod_inp('reg', 'reg', rsp_signal(ofs1))
    adc_ctrl(flt_typ, chn_cpl, dly)
    wait(10*250)
    clo(R.ext_adc, 0b00)

def rsp_rf_config(config: RSPWaveformParams):
    R.mua_inp[config.rf_out] = mod_inp("reg", "reg", rsp_signal(config.amp*2.0-1.0))
    R.mua_gan = mua_gan(1.0)
    R.mua_ofs = mua_ofs(0.0)
    R.mua_cpl = mua_cpl(-1.0)
    R.mua_cph = mua_cph(-1.0+2*config.output_max)
    
    R.rfg_inp[config.rf_out] = mod_inp("mua0", "reg")

def rsp_pid_config(config: RSPPIDConfig):
    """
    连接DSP units  adc -> mix -> cnv -> acu -> mua -> rfg ，构建PID回路
    """
    R.dgt_cfg[config.dgt_source] = dgt_cfg("cst0")

    # error signal: mix0 = adc{config.adc_in} - set_point
    R.mix_ipa[config.rf_out] = mod_inp(f"adc{config.adc_in}", f"dgt{config.dgt_source}")
    R.mix_ipb = mod_inp("reg", f"dgt{config.dgt_source}", config.setpoint)
    R.mix_cfg = mix_cfg("+", 0, "", "-")
    
    # PID: acu0 = pid(mix0)
    R.cnv_inp[config.rf_out] = mod_inp(f"mix{config.rf_out}", f"dgt{config.dgt_source}")
    R.cnv_cfg = cnv_cfg(0, 0, 1, 1)
    atn_cnv = 3
    R.cnv_cfg = cnv_cfg(atn_cnv, 0)
    cnv_pid(config.kp, config.ki, config.kd)
    R.acu_inp[config.rf_out] = mod_inp(f"cnv{config.rf_out}", f"dgt{config.dgt_source}")
    atn_acu = 2
    R.acu_prh = acu_prh(-1048576*2, atn_acu)
    R.acu_prl = acu_prl(-1048576*2)
    
    R.mua_inp[config.rf_out] = mod_inp(f"acu{config.rf_out}", f"dgt{config.dgt_source}")
    R.mua_gan = mua_gan(1.0)
    R.mua_ofs = mua_ofs(0.0)
    R.mua_cpl = mua_cpl(-1.0)
    R.mua_cph = mua_cph(-1.0+2*config.output_max)
    
    R.rfg_inp[config.rf_out] = mod_inp(f"mua{config.rf_out}", f"dgt{config.dgt_source}")
    

def rsp_pid_start(loop_id:int):
    """
    开启 dgt 通道，开始PID过程
    """
    R.dgt_cfg[loop_id] = dgt_cfg("cst1")

def rsp_pid_hold(loop_id: int):
    """
    关闭 dgt 通道，使得对应的 pid 回路完全停止，所有寄存器的值保持不变。
    """
    R.dgt_cfg[loop_id] = dgt_cfg("cst0")

def rsp_pid_release(config: RSPPIDConfig):
    """
    释放PID回路，将RF输出设置为0。
    """
    R.dgt_cfg[config.dgt_source] = dgt_cfg("cst0")

    R.mua_inp[config.rf_out] = mod_inp("reg", "reg", rsp_signal(-1.0))
    R.mua_gan = mua_gan(1.0)
    R.mua_ofs = mua_ofs(0.0)
    R.mua_cpl = mua_cpl(-1.0)
    R.mua_cph = mua_cph(-1.0+2*config.output_max)
    
    R.rfg_inp[config.rf_out] = mod_inp(f"mua{config.rf_out}", "reg")

def rsp_pid_relink(config: RSPPIDConfig):
    """
    重新连接PID回路，将RF输出设置为保持值。
    """
    R.dgt_cfg[config.dgt_source] = dgt_cfg("cst0")

    R.mua_inp[config.rf_out] = mod_inp(f"acu{config.rf_out}", f"dgt{config.dgt_source}")
    R.mua_gan = mua_gan(1.0)
    R.mua_ofs = mua_ofs(0.0)
    R.mua_cpl = mua_cpl(-1.0)
    R.mua_cph = mua_cph(-1.0+2*config.output_max)
    
    R.rfg_inp[config.rf_out] = mod_inp(f"mua{config.rf_out}", f"dgt{config.dgt_source}")

