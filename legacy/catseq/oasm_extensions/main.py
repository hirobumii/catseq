from .std import *

C_MAIN = base_core(["ICF", "ICA", "ICD", "DCF", "DCA", "DCD",
                    "NEX", "FRM", "SCP", "TIM", "WCL", "WCH",
                    "LED", "FAI", "MAC", "CPR", "SPI", "RND", 
                    "TTL", "DIO", "CTR", "CSM", "TTS", "TEV", "BPL", "MON"], ["ICA", "DCA"],
                   {"NEX": [None]*32 + ["ADR", "BCE", "RTA", "RTD"],
                    "FRM": (["PL0", "PL1"] if PL01 else ["PL1", "PL0"])+["TAG", "DST"],
                    "SCP": ["MEM", "TGM", "CDM", "COD"],
                    "WCL": ["NOW", "BGN", "END"],
                    "WCH": ["NOW", "BGN", "END"],
                    "FAI": ["FGL", "FGH", "DNL", "DNH", "IDL", "IDH", "AUX"],
                    "MAC": ["MDI", "DLY", "CFG", "SRL", "SRH", "DSL", "DSH"],
                    "SPI": [None]*4 + ["SLV", "CTL"],
                    "DIO": ["DIR", "INV", "POS", "NEG"],
                    "CTR": [None]*4},
                   131072, 1048576)

class rsm(rsm.__class__):
    debug = bit_field(4)
    coproc = bit_field(5)
    spi = bit_field(6)
    gpio = bit_field(7)
    trg1 = bit_field(8)
    trg0 = bit_field(9)

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

class ctr(ports):
    def __init__(self):
        super().__init__()
        for i in range(0x20):
            setattr(self,f'&{i:02x}',port(f'&{i:02x}'))

ctr = ctr()

class main(std.__class__):
    C_MAIN = C_MAIN

    def play(self, dur, strict=True, wait=1):
        self.timer(round(dur*self.us)&-2,strict=strict,wait=wait)


main = main(**globals())