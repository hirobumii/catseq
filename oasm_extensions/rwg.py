from .std import *

import math

N_SBG = 128
C_RWG = base_core(
    ["ICF", "ICA", "ICD", "DCF", "DCA", "DCD",
    "NEX", "FRM", "SCP", "TIM", "WCL", "WCH",
    "LED", "FAI", "MAC", "CPR", "SPI", "RND", 
    "TTL", "DIO", "CTR", "CSM", "TTS", "TEV", "UBR", "UDA",
    "DDS", "SBG", "PDM", "CDS", "POF",
    "FTE", "FT0", "FT1", "FT2", "FT3", "FT4", "FT5", 
    "APE", "AP0", "AP1", "AP2", "AP3", "AP4", "AP5", "CMK", "CFQ", "CAM"], ["ICA", "DCA", "TIM"],
    {"NEX": [None]*32 + ["ADR", "BCE", "RTA", "RTD"],
    "FRM": ["PL1", "PL0", "TAG", "DST"],
    "SCP": ["MEM", "TGM", "CDM", "COD"],
    "WCL": ["NOW", "BGN", "END"],
    "WCH": ["NOW", "BGN", "END"],
    "FAI": ["FGL", "FGH", "DNL", "DNH", "IDL", "IDH", "AUX"],
    "MAC": ["MDI", "DLY", "CFG", "SRL", "SRH", "DSL", "DSH"],
    "SPI": [None]*4 + ["SLV", "CTL"],
    "DIO": ["DIR", "INV", "POS", "NEG"],
    "CTR": [None]*4,
    "UBR": [None]*4,
    "UDA": [None]*256,
    "CDS": [None]*16 + ["DLY", "SCA"],
    "POF": [None]*N_SBG,
    "FTE": [None]*N_SBG,
    "FT0": [None]*N_SBG,
    "FT1": [None]*N_SBG,
    "FT2": [None]*N_SBG,
    "FT3": [None]*N_SBG,
    "FT4": [None]*N_SBG,
    "FT5": [None]*N_SBG,
    "APE": [None]*N_SBG,
    "AP0": [None]*N_SBG,
    "AP1": [None]*N_SBG,
    "AP2": [None]*N_SBG,
    "AP3": [None]*N_SBG,
    "AP4": [None]*N_SBG,
    "AP5": [None]*N_SBG,
    "CMK": [None]*4},
    131072, 1048576)

class rsm(rsm.__class__):
    debug = bit_field(4)
    coproc = bit_field(5)
    spi = bit_field(6)
    gpio = bit_field(7)

rsm = rsm()

class exc(exc.__class__):
    pll = bit_field(8)

exc = exc()

ttl = port('ttl')

class dio(ports):
    def __init__(self):
        super().__init__()
        self.dir = port('dir')
        self.inv = port('inv')
        self.pos = port('pos')
        self.neg = port('neg')

dio = dio()

csm = port('csm')

class ubr(ports):
    def __init__(self):
        super().__init__()
        for i in range(4):
            setattr(self,f'&{i:02x}',port(f'&{i:02x}'))

ubr = ubr()

class uba(ports):
    def __init__(self):
        super().__init__()
        for i in range(0x100):
            setattr(self,f'&{i:02x}',port(f'&{i:02x}'))

uba = uba()

class dds(port):
    pfl0 = bit_field(0,2)
    iou0 = bit_field(3)
    pfl1 = bit_field(4,6)
    iou1 = bit_field(7)
    pfl2 = bit_field(8,10)
    iou2 = bit_field(11)
    pfl3 = bit_field(12,14)
    iou3 = bit_field(15)
    txe = bit_field(16,19)
    ior = bit_field(20,23)
    rst = bit_field(24,27)
    synrst = bit_field(28,31)

    def signal(self, iou=0, txe=0, pfl=(0,0,0,0)):
        self(0,LO,**{f'iou{i}':(iou>>i)&1 for i in range(4)},**{f'pfl{i}':pfl[i] for i in range(4)},txe=txe)
    
    def ctrl(self, rst=0, ior=0, synrst=0b00):
        self(0,HI,rst=rst,ior=ior,synrst=synrst)

dds = dds()

class sbg(port):
    pud0 = bit_field(0)
    iou0 = bit_field(1)
    pud1 = bit_field(4)
    iou1 = bit_field(5)
    pud2 = bit_field(8)
    iou2 = bit_field(9)
    pud3 = bit_field(12)
    iou3 = bit_field(13)
    mrk = bit_field(16,19)

    def ctrl(self, iou=0, pud=0, mrk=0):
        self(0,LO,**{f'iou{i}':(iou>>i)&1 for i in range(4)},**{f'pud{i}':(pud>>i)&1 for i in range(4)},mrk=mrk)
        std.pause(2)

sbg = sbg()

class pdm(port):
    rf0 = bit_field(0,3)
    rf1 = bit_field(4,7)
    rf2 = bit_field(8,11)
    rf3 = bit_field(12,15)

    def source(self, rf0, rf1, rf2, rf3):
        self(0,LO,rf0=rf0,rf1=rf1,rf2=rf2,rf3=rf3)

pdm = pdm()

class cds_sca(port):
    sca0 = bit_field(0,3)
    sca1 = bit_field(4,7)
    sca2 = bit_field(8,11)
    sca3 = bit_field(12,15)

class cds(ports):
    def __init__(self):
        super().__init__()
        self.dly = port('dly')
        self.sca = cds_sca('sca')
        for i in range(16):
            setattr(self,f'&{i:02x}',port(f'&{i:02x}'))

    def mux(self, sca, ena):
        self.sca(0,LO,**{f'sca{i}':sca[i] for i in range(4)})
        for i in range(4):
            for j in range(4):
                getattr(self,f'&{i*4+j:02x}')((ena[i]>>(32*j))&0xffffffff)

cds = cds()

class spi_ctl(port):
    tot_bit = bit_field(0,7)
    sdo_bit = bit_field(8,15)
    sdi_ltn = bit_field(16,19)
    clk_div = bit_field(20,29)
    pol_pha = bit_field(30,31)

class spi_da(port):
    b0 = bit_field(0,7)
    b1 = bit_field(8,15)
    b2 = bit_field(16,23)
    b3 = bit_field(24,31)

class spi(ports):
    def __init__(self):
        super().__init__()
        for i in range(4):
            setattr(self,f'&{i:02x}',spi_da(f'&{i:02x}'))
        self.ctl = spi_ctl('ctl')
        self.slv = port('slv')

    def send(self, pol_pha, clk_div, sdi_ltn, sdo_bit, tot_bit, wait=True):
        if wait:
            rsm.on(spi=1)
        self.ctl(pol_pha=pol_pha,clk_div=clk_div,sdi_ltn=sdi_ltn,sdo_bit=sdo_bit,tot_bit=tot_bit)
        if wait:
            std.hold()

spi = spi()

class fte_s(port):
    # &xx[3:0]: phase dithering gain (experimental feature)
    # 相位抖动增益（实验功能）
        # default value: 0
    dth_gan = bit_field(0,3)
    
    # &xx[4]: phase accumulator reload flag
    # 相位累加器重载标志
        # 0: interpret POF.&xx as phase offset, load it to the phase offset register when PAR_UPD flag is asserted
        # 0: 将 POF.&xx 解释为相位偏移量，并在 PAR_UPD 标志被置位时将其加载到相位偏移寄存器中
        # 1: interpret POF.&xx as initial phase, reload the phase accumulator with it and reset the phase offset register to 0 when PAR_UPD flag is asserted
        # 1: 将 POF.&xx 解释为初始相位，在 PAR_UPD 标志被置位时重新加载相位累加器，并将相位偏移寄存器重置为 0
    pha_rld = bit_field(4)
    
    # &xx[5]: phase dithering enable flag (experimental feature)
    # 相位抖动使能标志（实验功能）
        # default value: 0
    dth_ena = bit_field(5)
    
    
    ext = bit_field(16,19)
    
    # &xx[22:20]: scale parameter Sf, can be 0 ~ 7
    # &xx[22:20]: 尺度参数 Sf，取值范围为 0 ~ 7
    sel = bit_field(20,23)
    
    # &xx[27:25]: highest non-zero order flag, indicating the highest order with non-zero coefficient
    # 最高非零阶标志，指示具有非零系数的最高阶
        # 100: the 3rd order 3阶
        # 010: the 2nd order 2阶
        # 001: the 1st order 1阶
        # 000: the 0th order (even if the coefficient of the 0th order is also 0) 0阶（即使0阶的系数也是0）
    # &xx[24]: scale changed flag
    # 尺度变化标志
        # 0: the highest non-zero order flag (FTE.&xx[27:25]) and the scale parameter (FTE.&xx[22:20]) for the next waveform segment are the same as current one
        # 0: 下一个波形段的最高非零阶标志 (FTE.&xx[27:25]) 和尺度参数 (FTE.&xx[22:20]) 与当前相同
        # 1: any of the 2 parameters are different
        # 1: 这两个参数中有任意一个不同
    hnz = bit_field(24,27)
    
    # &xx[31:28]: coefficient load flag for the 3rd to 0th order (F3 ~ F0)
    # 3rd 到 0th 阶的系数加载标志 (F3 ~ F0)
        # 0: the frequency function is continuous at the corresponding order at the beginning of the next waveform segment, no need to load new coefficient value
        # 0: 下一个波形段开始时，对应阶数的频率函数是连续的，无需加载新的系数值
        # 1: new value of coefficient should be loaded
        # 1: 需要加载新的系数值
    rld = bit_field(28,31)

class fte(fte_s,ports):
    def __init__(self, _name=None):
        super().__init__(_name)
        for i in range(N_SBG):
            setattr(self,f'&{i:02x}',fte_s(f'&{i:02x}'))

    def cfg(self, sbn, dth_ena, dth_gan, pha_rld):
        """
        cfg 的 Docstring
        
        :param self: 对象本身
        :param sbn: SBG 的通道号
        :param dth_ena: 相位抖动使能标志（实验功能）
        :param dth_gan: 相位抖动增益（实验功能）
        :param pha_rld: 相位累加器重载标志
        """
        # fte[0]代表访问fte.&00属性，这个属性是fte_s类的一个实例，此处调用的函数是fte_s类的__call__方法
        # 由于fte_s类继承自port类，所以调用的是port类的__call__方法
        self[sbn](0, LO, dth_ena=dth_ena, dth_gan=dth_gan, pha_rld=pha_rld)

fte = fte()
ape = fte_s('ape')
for i in range(6):
    globals()[f'ft{i}'] = port(f'ft{i}')
    globals()[f'ap{i}'] = port(f'ap{i}')
pof = port('pof')

class rwg(std.__class__):
    C_RWG = C_RWG
    DDS_REGLEN = [4, 4, 4, 4, 4, 6, 6, 4, 2, 4, 4, 8, 8, 4, 8, 8, 8, 8, 8, 8, 8, 8, 4, 0, 2, 2]

    def regwr(self, chn, reg, dat, clk=1, wait=True, ioupd=True):
        spi.slv(chn << 1)
        tln = len(dat)
        dat = [reg] + dat + ([0] * (11 - tln))
        for i in range(3):
            spi[3-i](b3=dat[i*4],b2=dat[i*4+1],b1=dat[i*4+2],b0=dat[i*4+3])
        spi.send(0b11, clk, 0, 0xFF, self.DDS_REGLEN[reg]*8+8, wait)
        if ioupd:
            dds.signal(iou=chn)
        return self

    def prof_sgt(self, chn, prof, frq, amp, pha, wait=True, ioupd=True):
        ftw = round((frq / 1000) * (2 ** 32))
        ftw = ftw.to_bytes(4, "big")
        asf = round(amp * 16383).to_bytes(2, "big")
        phw = round(pha * 65536).to_bytes(2, "big")
        return self.regwr(chn, prof + 14, list(asf + phw + ftw), wait=wait, ioupd=ioupd)
    
    def prof_duc(self, chn, prof, ccir, s_inv, i_cci, frq, amp, pha, wait=True, ioupd=True):
        ctr = bit_concat((ccir, 6), (s_inv, 1), (i_cci, 1)).to_bytes(1, "big")
        ftw = round((frq / 1000) * (2 ** 32)).to_bytes(4, "big")
        asf = round(amp * 255).to_bytes(1, "big")
        phw = round(pha * 65536).to_bytes(2, "big")
        return self.regwr(chn, prof + 14, list(ctr + asf + phw + ftw), wait=wait, ioupd=ioupd)
    
    def rst_cic(self, chn):
        return self.regwr(chn, reg = 0x0, dat = [0x00, 0x60, 0x20, 0x02])
    
    def carrier(self, chn, frq, amp=1.0, pha=0.0, upd=False):
        return self.prof_duc(chn, 0, 2, 0, 0, frq, amp, pha, wait=True, ioupd=upd)
    
    @staticmethod
    def to_coe(par, fct, sel):
        sca = 1 << (sel * 2 + 5)
        coe = [None] * len(par)
        hnz = 0
        rld = 0
        for i in range(len(par)):
            if par[i] is not None:
                rld += 1 << i
                hnz = i if par[i] != 0 else hnz 
                coe[i] = par[i] if getattr(par[i],'__round__',None) is None else round(par[i] * fct * (sca/rwg.us)**i)
        hnz = 1 << hnz if hnz > 0 else 0
        return rld, hnz, coe

    @staticmethod
    def to_sel(dur):
        return min(max(round((math.log2(dur * rwg.us) - 5) / 2) - 1, 0), 7)
    
    def frq(self, sbn, frq, pha=None, dur=100.0, hnzo_cont=0, fct=None, sel=None, ena=True):
        """
        <sbn>: SBG channel number
        <frq>: sideband frequency ramp coefficient, list of 4, in MHz/us^i, 
        <pha>: phase offset / origin, in 2pi
        <dur>: wave segment duration, in us
        <hnzo_cont>: if the order of <frq> and <dur> are the same as the previous segment, this can be 1
        """
        if fct is None:
            fct = 0x100000000/self.us
        if sel is None:
            if type(dur) is expr:
                sel = expr(rwg.to_sel,table(dur))
            else:
                sel = rwg.to_sel(dur)
        rld, hnz, coe = rwg.to_coe(frq, fct, sel)
        if ena:
            (fte if sbn is None else fte[sbn])(0,HI,rld=rld,hnz=hnz+1-hnzo_cont,sel=sel)
            fte.set(ext=bit_concat((rld>>4,2),(hnz>>4,2)))
        elif sbn is not None:
            fte[sbn]()
        for i in range(len(coe)):
            if coe[i] is not None:
                globals()[f'ft{i}'](coe[i])
        if pha is not None:
            pof(round(pha * 0x1_00000) & 0xFFFFF)
        return self
    
    def amp(self, sbn, amp, dur=100.0, hnzo_cont=0, fct=None, sel=None, ena=True):
        """
        <sbn>: SBG channel number
        <amp>: sideband amplitude ramp coefficient, list of 4, in FS/us^i, 
        <dur>: wave segment duration, in us
        <hnzo_cont>: if the order of <frq> and <dur> are the same as the previous segment, this can be 1
        """
        if fct is None:
            fct = 0x7FFFFFFF
        if sel is None:
            if type(dur) is expr:
                sel = expr(rwg.to_sel,table(dur))
            else:
                sel = rwg.to_sel(dur)
        rld, hnz, coe = rwg.to_coe(amp, fct, sel)
        if sbn is not None:
            fte[sbn]()
        if ena:
            ape(0,HI,rld=rld,hnz=hnz+1-hnzo_cont,sel=sel)
            ape.set(ext=bit_concat((rld>>4,2),(hnz>>4,2)))
        for i in range(len(coe)):
            if coe[i] is not None:
                globals()[f'ap{i}'](coe[i]>>12)
        return self
    
    def play(self, dur, pud=0xf, cph=0xf, mrk=0, wait=1):
        self.timer(round(dur*self.us)&-2, wait=wait&1)
        sbg.ctrl(iou=cph, pud=pud, mrk=mrk)
        if wait>>1:
            std.hold()
        return self

rwg = rwg(**globals())