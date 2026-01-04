from oasm.rtmq2 import *
import numpy as np

C_RSP = base_core(
    ["ICF", "ICA", "ICD", "DCF", "DCA", "DCD",
     "NEX", "FRM", "SCP", "TIM", "WCL", "WCH",
     "LED", "FAI", "MAC", "CPR", "SPI", "RND",
     "LED_SRC", "EXT_DIO", "EXT_DDS", "DDS_MON", "EXT_DAC", "EXT_ADC",
     "DAC_INP", "RFG_INP", "MON_INP", "MON0", "MON1", "MUX_IPA", "MUX_IPB",
     "RBF_INP", "RBF_OUT", "RBF_WRA", "RBF_RDA", "RBF_PBK",
     "FUN_INP", "FUN_DRV", "FUN_VAL", "DDS_IPF", "DDS_IPP", "DDS_CFG", "DDS_FTW",
     "MUA_INP", "MUA_GAN", "MUA_OFS", "MUA_CPL", "MUA_CPH",
     "MIX_IPA", "MIX_IPB", "MIX_CFG", "CNV_INP", "CNV_CFG", "CNV_KRN",
     "ACU_INP", "ACU_PRL", "ACU_PRH", "CKG_IPI", "CKG_IPT", "CKG_MAX", "CKG_PRE",
     "DGT_CFG", "DGT_OUT", "LGF_LUT", "LGF_OUT", "HST_INP", "HST_OUT", "OVF"],
    ["ICA", "DCA", "TIM"],
    {"NEX": [None]*32 + ["ADR", "BCE", "RTA", "RTD"],
     "FRM": ["PL1", "PL0", "TAG", "DST"],
     "SCP": ["MEM", "TGM", "CDM", "COD"],
     "WCL": ["NOW", "BGN", "END"],
     "WCH": ["NOW", "BGN", "END"],
     "FAI": ["FGL", "FGH", "KYL", "KYH", "IDL", "IDH", "AUX"],
     "MAC": ["MDI", "DLY", "CFG", "SRL", "SRH", "DSL", "DSH"],
     "SPI": [None]*4 + ["SLV", "CTL"],
     "DAC_INP": [None]*6, "RFG_INP": [None]*2, "MON_INP": [None]*2,
     "MUX_IPA": [None]*4, "RBF_INP": [None]*4, "FUN_INP": [None]*4,
     "DDS_IPF": [None]*8, "MUA_INP": [None]*8, "MIX_IPA": [None]*8,
     "CNV_INP": [None]*8, "ACU_INP": [None]*8, "CKG_IPI": [None]*4,
     "DGT_CFG": [None]*15, "LGF_LUT": [None]*6,
     "HST_INP": [None]*2}, 131072, 524288)

us = 250
ms = 1000 * us


#-------------------------
# -------- Helper --------
#-------------------------

def rsp_signed(val, wid):
    msk = 1 << (wid - 1)
    return -(val & msk) | (val & (msk - 1))

def rsp_unsigned(val, wid):
    msk = (1 << wid) - 1
    return val & msk

def rsp_signal(sig):
    sig = max(min(sig, 1), -1)
    ret = round(sig * 0x80000) & 0xFFFFF
    if (sig > 0) and (ret == 0x80000):
        return 0x7FFFF
    else:
        return ret

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

def rsp_decode(val, typ="signal"):
    if typ == "signal":
        return rsp_signed(val, 20) / 0x80000
    elif typ == "gain":
        return rsp_signed(val, 16) / (2 ** (val >> 16))

def _sig_wrap(val):
    if isinstance(val, int):
        return val
    else:
        return rsp_signal(val)

# -------- DSP CSR Interface --------

DSP_BUS = ["REG", "RND", "ADC0", "ADC1"] + \
          [f"MUX{i}" for i in range(4)] + \
          [f"RBF{i}" for i in range(4)] + \
          [f"FUN{i}" for i in range(4)] + \
          [f"DDS{i}" for i in range(8)] + \
          [f"MUA{i}" for i in range(8)] + \
          [f"MIX{i}" for i in range(8)] + \
          [f"CNV{i}" for i in range(8)] + \
          [f"ACU{i}" for i in range(8)]
DCI_BUS = ["CST0", "CST1"] + \
          [f"DIN{i}" for i in range(2)] + \
          [f"CKG{i}" for i in range(4)] + \
          [f"MIX{i}" for i in range(8)] + \
          [f"MLO{i}" for i in range(8)] + \
          [f"MMD{i}" for i in range(8)] + \
          [f"MHI{i}" for i in range(8)] + \
          [f"LGF{i}" for i in range(6)]
DGT_BUS = ["REG"] + [f"DGT{i:X}" for i in range(15)]

INP_IDX = dict()
for i in range(len(DSP_BUS)):
    INP_IDX[DSP_BUS[i]] = i
DCI_IDX = dict()
for i in range(len(DCI_BUS)):
    DCI_IDX[DCI_BUS[i]] = i
DGT_IDX = dict()
for i in range(len(DGT_BUS)):
    DGT_IDX[DGT_BUS[i]] = i

def mod_inp(sig, clk, val=0):
    return bit_concat((DGT_IDX[clk.upper()], 4), (0, 2), (INP_IDX[sig.upper()], 6), (_sig_wrap(val), 20))

def rbf_wra(adr):
    return adr & 0xFFFF

def rbf_rda(adr, clk):
    return bit_concat((DGT_IDX[clk.upper()], 4), (adr, 16))

def rbf_pbk(head, tail):
    return bit_concat((tail, 16), (head, 16))

def fun_load(func):
    sz = 4096
    val = list(func(np.linspace(-1, 1, sz, False) + 1/sz))
    val = val[sz//2:] + val[0:sz//2]
    itv = func(np.linspace(-1, 1, sz+1, True))
    drv = list((itv[1:] - itv[0:-1]) * sz / 2)
    drv = drv[sz//2:] + drv[0:sz//2]
    for a in range(sz):
        clo(R.fun_drv, rsp_gain(drv[a]))
        cli(R.fun_val, bit_concat((a, 12), (rsp_signal(val[a]), 20)))

def dds_cfg(out_sel, exp_fm, clr_pha=0):
    out_sel = {"SIN": 0, "PHA": 1}[out_sel.upper()]
    return bit_concat((clr_pha, 1), (out_sel, 1), (exp_fm, 4))

def dds_ftw(frq):
    if isinstance(frq, int):
        val = frq
    else:
        val = round((frq / 250) * (2 ** 32))
    return val

def mua_gan(gain):
    return rsp_gain(gain)

def mua_ofs(ofs):
    return _sig_wrap(ofs)

def mua_cpl(val):
    return _sig_wrap(val)

def mua_cph(val):
    return _sig_wrap(val)

def mix_cfg(sel, atn, sgn_a="", sgn_b="", dly_b=0):
    sel = {"+": 0, "*": 1, "m": 2, "M": 3}[sel]
    sgn = {"": 0, "A": 1, "-": 2, "-A": 3}
    sgn_a = sgn[sgn_a.upper()]
    sgn_b = sgn[sgn_b.upper()]
    return bit_concat((dly_b, 8), (0, 1), (atn, 5), (sel, 2), (sgn_b, 2), (sgn_a, 2))

def cnv_cfg(atn, fdb_ord, sig_rst=0, krn_rst=0):
    return bit_concat((krn_rst, 1), (sig_rst, 1), (0, 3), (atn, 5), (0, 2), (fdb_ord, 6))

def cnv_load(krnl):
    for k in krnl:
        clo(R.cnv_krn, rsp_gain(k))

def cnv_pid(kp, ki, kd):
    cnv_load([kd, -kp-kd*2, kp+ki+kd])

def acu_prl(val):
    if isinstance(val, int):
        return val & 0xFFFFFFFF
    else:
        return round(val * 0x80000) & 0xFFFFFFFF

def acu_prh(val, atn=0):
    if isinstance(val, int):
        tmp = (val>>32) & 0xFF
    else:
        tmp = (round(val * 0x80000) >> 32) & 0xFF
    return bit_concat((atn, 5), (0, 12), (tmp, 8))

def dgt_cfg(sel, inv=0, lac=0, neg=0, pos=0):
    return bit_concat((inv, 1), (lac, 1), (neg, 1), (pos, 1), (0, 2), (DCI_IDX[sel.upper()], 6))

# def func(d4, d3, d2, d1, d0): ...
def lgf_lut(func):
    return sum([(func(*map(int, f"{i:05b}")) & 1) << i for i in range(32)])

def ovf_chn(ovf):
    flg = bit_split(ovf, [8]*4)
    phr = ["ACU", "CNV", "MIX", "MUA"]
    for i in range(4):
        chn = ""
        for j in range(8):
            if (flg[i] >> j) & 1:
                chn += f"{j} "
        print(f"{phr[i]}: {chn}")


#------------------------------------------------
# --------- System Peripheral Interface ---------
#------------------------------------------------

def spi_send(pol_pha, clk_div, sdi_ltn, sdo_bit, tot_bit, wait=True):
    cfg = bit_concat((pol_pha, 2), (clk_div, 10), (sdi_ltn, 4),
                     (sdo_bit, 8), (tot_bit, 8))
    if wait:
        set_bit("rsm", "1.3")
    hp = H if wait else 0
    set_csr("spi.ctl", cfg, hp=hp)

def acs_mdio(rw, phy_adr, reg_adr, data):
    frm = bit_concat((rw + 5, 4), (phy_adr, 5), (reg_adr, 5), (2, 2), (data, 16))
    sfs("mac", "cfg")
    if rw:
        set_bit("mac", "1.9")
    else:
        clr_bit("mac", "1.9")
    set_csr("mac.mdi", frm)

def phy_cfg(rst, reg, dat):
    if rst:
        set_bit("mac.cfg", "2.9")
        wait(20*ms)
        clr_bit("mac.cfg", "2.9")
        wait(60*ms)
    for i in range(len(reg)):
        acs_mdio(0, 1, reg[i], dat[i])
        wait(2000)

def mac_cfg(tx_pha, rx_pha):
    phy_cfg(1, [22, 16, 21, 22, 0], [2, 0x4449, 0x1056, 0, 0x8140])
    set_csr("mac.dly", tx_pha * 16 + rx_pha)

def eth_cfg(src_mac, dst_mac, tx_gap, mdi_div, lnk_typ, typ_sel, eth_typ):
    # src_mac: MAC address of current node
    # dst_mac: destination MAC address
    # lnk_typ: link type, 0 for RTLink over Ethernet, 1 for raw RTLink
    # typ_sel: link type selection mode, 0 for automatic, 1 for manual
    # eth_typ: EtherType field
    cfg = bit_concat((tx_gap, 4), (mdi_div, 8), (0, 2), (lnk_typ, 1), (typ_sel, 1), (eth_typ, 16))
    set_csr("mac.cfg", cfg)
    set_csr("mac.srl", src_mac & 0xFFFFFFFF)
    set_csr("mac.srh", src_mac >> 32)
    set_csr("mac.dsl", dst_mac & 0xFFFFFFFF)
    set_csr("mac.dsh", dst_mac >> 32)

def lmk_spi(rw, reg, val, wait=True):
    frm = bit_concat((rw, 1), (reg, 15), (val, 8), (0, 8))
    set_csr("spi.&03", frm)
    spi_send(0b11, 25, 0, 32, 24, wait)

def parse_regmap(fn):
    with open(fn, "r") as f:
        txt = f.readlines()
    cnt = len(txt)
    rm = [0] * cnt
    for i in range(cnt):
        tmp = int((txt[i].split("\t"))[1][0:-1], 16)
        rm[i] = [tmp // 0x100, tmp % 0x100]
    return rm


#----------------------------------
# --------- DDS Interface ---------
#----------------------------------

DDS_REGLEN = [4, 4, 4, 4, 4, 6, 6, 4, 2, 4, 4, 8, 8, 4, 8, 8, 8, 8, 8, 8, 8, 8, 4, 0, 2, 2]

def dds_signal(rst=0b00, ior=0b00, syn=0b00, txe=0b00, f=0b0000, iou=0b00, prf=0o00):
    syn = bit_split(syn, [1]*2)
    txe = bit_split(txe, [1]*2)
    f = bit_split(f, [2]*2)
    iou = bit_split(iou, [1]*2)
    prf = bit_split(prf, [3]*2)
    tmp = [0] * 2
    for i in range(2):
        tmp[i] = bit_concat((syn[i], 1), (txe[i], 1), (f[i], 2), (iou[i], 1), (prf[i], 3))
    val = bit_concat((rst, 2), (ior, 2), (tmp[0], 8), (tmp[1], 8))
    clo("ext_dds", val)

def dds_delay(syn, pda, iou, prf):
    syn = bit_split(syn, [1]*2)
    pda = bit_split(pda, [1]*2)
    iou = bit_split(iou, [1]*2)
    prf = bit_split(prf, [1]*2)
    tmp = [0] * 2
    for i in range(2):
        tmp[i] = bit_concat((syn[i], 1), (pda[i], 1), (iou[i], 1), (prf[i], 1))
    val = bit_concat((tmp[0], 4), (tmp[1], 4), (0, 20))
    chi("ext_dds", val)

def dds_regwr(dds, reg, dat, clk=2, wait=True, iou=True):
    tln = len(dat)
    dat = [reg] + dat + ([0] * (11 - tln))
    ins = [0] * 3
    for i in range(3):
        ins[i] = bit_concat((dat[i*4], 8), (dat[i*4+1], 8),
                            (dat[i*4+2], 8), (dat[i*4+3], 8))
    set_csr("spi.slv", dds << 2)
    set_csr("spi.&03", ins[0])
    set_csr("spi.&02", ins[1])
    set_csr("spi.&01", ins[2])
    spi_send(0b11, clk, 0, 0xFF, DDS_REGLEN[reg]*8+8, wait)
    if iou:
        dds_signal(iou=dds)
        dds_signal(iou=dds)

def dds_regrd(dds, reg, clk=5, ltn=1, ret=True):
    set_csr("spi.slv", dds << 2)
    set_csr("spi.&03", (reg + 128) << 24)
    spi_send(0b11, clk, ltn, 8, DDS_REGLEN[reg]*8+8, ret)
    if ret:
        asm.dnld = 1
        asm.rply = 1
        asm.proc = lambda a, r: hex(((r[0]<<32) + r[1]) & ((1 << (DDS_REGLEN[reg]*8)) - 1))
        sfs("spi", "&01")
        nop(1, P)
        mov("$02", "spi")
        sfs("spi", "&00")
        nop(1, P)
        intf_send(["$02", "spi"])

def dds_prof(dds, prof, frq, amp, pha, wait=True, iou=True):
    ftw = round((frq / 1000) * (2 ** 32))
    ftw = ftw.to_bytes(4, "big")
    asf = round(amp * 16383).to_bytes(2, "big")
    phw = round(pha * 65536).to_bytes(2, "big")
    dds_regwr(dds, prof + 14, list(asf + phw + ftw), wait=wait, iou=iou)

def dds_carrier(dds, frq, wait=True, iou=True):
    ftw = round((frq / 1000) * (2 ** 32))
    ftw = ftw.to_bytes(4, "big")
    dds_regwr(dds, 7, list(ftw), wait=wait, iou=iou)


#----------------------------------
# --------- DAC Interface ---------
#----------------------------------

def dac_signal(dac_rst=0, ofs_dck_syn=0, adc_ofs_rst=0, dac_ofs_rst=0):
    val = bit_concat((dac_rst, 1), (ofs_dck_syn, 1), (adc_ofs_rst, 1), (dac_ofs_rst, 1))
    clo("ext_dac", val)

def dac_delay(dac_dat, adc_ofs_dck, dac_ofs_dck):
    val = bit_concat((dac_dat, 1), (adc_ofs_dck, 2), (dac_ofs_dck, 2), (0, 20))
    chi("ext_dac", val)

def dac_spi(dac, rw, reg, val, wait=True):
    frm = bit_concat((rw, 1), (0, 2), (reg, 5), (val, 8), (0, 16))
    bdo = 8 if rw else 16
    set_csr("spi.slv", dac << 4)
    set_csr("spi.&03", frm)
    spi_send(0b11, 10, 0, bdo, 16, wait)


#----------------------------------
# --------- ADC Interface ---------
#----------------------------------

def adc_ctrl(flt_typ, chn_cpl, dat_dly):
    dat_dly = bit_split(dat_dly, [3]*2)
    tmp = [0] * 2
    for i in range(2):
        tmp_typ = {"I": 0, "B": 1, "R": 2, "S": 3}[flt_typ[i].upper()]
        tmp_cpl = {"A": 0, "D": 1}[chn_cpl[i].upper()]
        tmp[i] = bit_concat((tmp_typ, 2), (tmp_cpl, 1), (dat_dly[i], 3))
    val = bit_concat((tmp[0], 6), (tmp[1], 6), (0, 20))
    chi("ext_adc", val)

def adc_spi(rw, reg, val, wait=True):
    frm = bit_concat((rw, 1), (0, 2), (reg, 13), (val, 8), (0, 8))
    bdo = 16 if rw else 24
    set_csr("spi.slv", 1 << 7)
    set_csr("spi.&03", frm)
    spi_send(0b11, 7, 0, bdo, 24, wait)


#----------------------------------
# --------- DIO Interface ---------
#----------------------------------

def led_src(d0="reg", d1="reg", d2="reg", d3="reg"):
    val = bit_concat((DGT_IDX[d0.upper()], 4), (DGT_IDX[d1.upper()], 4),
                     (DGT_IDX[d2.upper()], 4), (DGT_IDX[d3.upper()], 4))
    clo("led_src", val)

def dio_cfg(dir=0b00, lvl=0b00, io0="reg", io1="reg"):
    dir = bit_split(dir, [1]*2)
    lvl = bit_split(lvl, [1]*2)
    tmp = [io0, io1]
    for i in range(2):
        tmp[i] = bit_concat((dir[i], 1), (lvl[i], 1), (DGT_IDX[tmp[i].upper()], 4))
    val = bit_concat((tmp[0], 8), (tmp[1], 8))
    clo("ext_dio", val)
