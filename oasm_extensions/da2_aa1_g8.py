from .flex import *

class da2_aa1_g8(flex.__class__):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config(1,12,6,1)
    
da2_aa1_g8 = da2_aa1_g8(**globals())