import os,sys,math,json,ctypes
# lib = os.path.abspath('.')
import importlib.resources
lib=r"C:\Users\Jiang\Documents\rtmq\py\archon\hdl\rtmq2\lib"
from ctypes import c_int,c_void_p,POINTER,c_uint8,c_uint16,c_uint32,c_uint64

class sig:
    def __init__(self,ptr,name='top',header=None):
        self._ptr = ptr
        if header is None:
            with open(os.path.join(lib,f'{name}.json'),'r') as f:
                self._header = json.load(f)
        else:
            self._header = header
        self._sig = self._header[name]
    def __getattr__(self, key):
        types = (c_uint8,c_uint16,c_uint32,c_uint64)            
        val = self._sig.get(key,None)
        if val is None:
            val = self._sig.get('*'+key,None)
            if val is None:
                return
            val = val[:2]+[ctypes.cast(self._ptr+val[2],POINTER(c_uint64))[0]-self._ptr]+val[3:]
        if len(val) == 2:
            val = sig(ctypes.cast(self._ptr+val[1],POINTER(c_uint64))[0],val[0],self._header)
        elif len(val) == 3:
            typ = int(math.log2(val[1]))
            if typ > 3:
                #(c_uint32*(val[1]>>2)).from_address(self._ptr+val[2])
                typ = 2
            return ctypes.cast(self._ptr+val[2],POINTER(types[typ]))
        elif len(val) == 4:
            typ = int(math.log2(val[1]))
            if typ > 3:
                #(c_uint32*val[3]*(val[1]>>2)).from_address(self._ptr+val[2])
                typ = 2
            #return (types[typ]*val[3]).from_address(self._ptr+val[2])
            return ctypes.cast(self._ptr+val[2],POINTER(types[typ]))
        setattr(self,key,val)
        return val
        
class top:
    def __init__(self,name='top',io=None,trace=None,uart=0):
        self._lib = ctypes.CDLL(os.path.join(lib,f'{name}.'+('so' if sys.platform == 'linux' else 'dll')))
        self._io = io
        self._lib.top_open.restype = c_void_p
        self._lib.top_tick.argtypes = (c_void_p,c_uint32,c_void_p,c_void_p,c_void_p)
        self._lib.top_tick.restype = c_uint64
        self._lib.top_close.argtypes = (c_void_p,)
        self._lib.uart_open.restype = c_void_p
        self._lib.uart_open.argtypes = (c_void_p,c_void_p,c_void_p,c_int,c_void_p,c_void_p)
        self._lib.uart_buf.restype = POINTER(c_uint8)
        self._lib.uart_buf.argtypes = (c_void_p,c_int)
        self._lib.uart_done.argtypes = (c_void_p,)
        self._lib.uart_fill.argtypes = (c_void_p,c_int)
        self._lib.uart_flush.argtypes = (c_void_p,)
        self._lib.uart_close.argtypes = (c_void_p,)
        self._lib.vcd_open.restype = c_void_p
        self._lib.vcd_open.argtypes = (c_void_p,)
        self._lib.vcd_flush.argtypes = (c_void_p,)
        self._lib.vcd_close.argtypes = (c_void_p,)
        
        self._top = self._lib.top_open()
        try:
            self._sig = sig(self._top,name)
        except:
            self._sig = None
        if uart and self._sig is not None:
            rx_frm = getattr(self._sig,'rx_frm',None)
            tx_frm = getattr(self._sig,'tx_frm',None)
        else:
            rx_frm,tx_frm = None,None
        if None in (rx_frm,tx_frm):
            uart = 0        
        self._uart = self._lib.uart_open(self._top,None,None,uart,rx_frm,tx_frm)
        self._chunk = uart*(4096//uart) if uart else 4096
        self._vcd = None if trace is None else self._lib.vcd_open(self._top,trace)
        self._ibuf = self._lib.uart_buf(self._uart,0)
        self._obuf = self._lib.uart_buf(self._uart,1)
        self._in = b''
        self._out = []
    def tick(self, n=1, uart=True, vcd=True, brk=None):
        return self._lib.top_tick(self._top,n,self._uart if uart else None,self._vcd if vcd else None,brk)
    def status(self):
        if self._vcd:
            self._lib.vcd_flush(self._vcd)
        if callable(self._io):
            self._io(self)
        elif self._io:
            line = '\r[%-10dus] ' % (self.ns[0]//1000)
            for k in self._io:
               line += f'{getattr(self,k)[0]:X} '
            sys.stderr.write(line)
    def run(self, us=1, vcd=None):
        if type(us) is not int:
            self._in += bytes(us)
            us = None
        while True:
            if self._lib.uart_done(self._uart):
                if len(self._in):
                    res = self._in[:self._chunk]
                    ctypes.memmove(self._ibuf,res,len(res))
                    self._lib.uart_fill(self._uart,len(res))
                    self._in = self._in[self._chunk:]
                elif us is None:
                    break
            self.tick(250,vcd=vcd)
            self.status()
            size = self._lib.uart_flush(self._uart)
            for i in range(size):
                self._out.append(self._obuf[i])
            if type(us) is int:
                us -= 1
                if us == 0:
                    break
    def write(self, buf):
        self.run(buf)
    def read(self, ret, tout=5):
        if len(self._out) >= ret:
            res = self._out[:ret]
            self._out = self._out[ret:]
            if self._io and not callable(self._io):
                sys.stderr.write('\n')
            return bytes(res)
        tout = tout * 1000000
        while len(self._out) < ret and tout:
            self.run(vcd=True)
            tout -= 1
        res = self._out[:ret]
        self._out = self._out[ret:]
        if len(res) > 0 and self._io and not callable(self._io):
            sys.stderr.write('\n')
        return bytes(res)
    def close(self):
        if self._vcd:
            self._lib.vcd_close(self._vcd)
        self._lib.uart_close(self._uart)
        self._lib.top_close(self._top)
    def __getattr__(self, key):
        return getattr(self._sig,key)
