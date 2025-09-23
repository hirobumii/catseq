"""
OASM DSL function definitions.

This module contains the actual OASM DSL functions that will be called
when executing compiled sequences on the hardware.
"""
# Import actual OASM functions
from oasm.rtmq2 import sfs, amk, wait, send_trig_code, wait_rtlk_trig,asm
from oasm.dev.rwg import fte, rwg, sbg


from ..types.rwg import WaveformParams
from .mask_utils import binary_to_rtmq_mask
from ..time_utils import us

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


def ttl_set(mask, state):
    """设置 TTL 通道状态
    
    用于 TTL_ON/TTL_OFF 操作，设置TTL通道的输出状态
    
    Args:
        mask: 通道掩码，指定哪些通道受影响 (binary format, e.g., 0b0101) 
        state: TTL 状态值，指定选中通道的输出状态 (binary format, e.g., 0b0001)
    """
    # Convert binary masks to RTMQ "A.B" format if possible
    rtmq_mask = binary_to_rtmq_mask(mask)
    rtmq_state = binary_to_rtmq_mask(state)
    
    amk('ttl', rtmq_mask, rtmq_state)
    print(f"TTL_SET - mask={rtmq_mask}, state={rtmq_state}")
    print(f"  -> mask=0b{mask:08b}, state=0b{state:08b}")
    print("  TODO: 实现实际的OASM汇编调用")

def wait_mu(cycles):
    wait(cycles)

def wait_us(duration):
    """等待指定微秒数
    
    Args:
        duration: 等待时长（微秒）
    """
    # print(f"OASM: Wait {duration} μs")
    t = round(duration*250)
    wait(t)  # 使用转换后的时间单位

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
            
    print(f"RF_SWITCH - ch_mask=0b{ch_mask:04b}, state_mask=0b{state_mask:04b}")
    print(f"  -> Affected RF ports: {[i for i in range(4) if ch_mask & (1 << i)]}")

def rwg_load_waveform(params: WaveformParams):
    """Load waveform parameters for a single SBG."""
    # User implementation will call rwg.frq() and rwg.amp()
    pha_rld: int = 1 if params.phase_reset else 0
    fte.cfg(params.sbg_id, 0, 0, pha_rld=pha_rld)
    rwg.frq(None, params.freq_coeffs, params.initial_phase)
    rwg.amp(None, params.amp_coeffs)

def rwg_play(pud_mask: int, iou_mask: int):
    """Trigger the waveform playback."""
    sbg.ctrl(iou=iou_mask, pud=pud_mask, mrk=0)

