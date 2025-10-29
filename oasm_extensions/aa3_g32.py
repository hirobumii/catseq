from .flex import *

class aa3_g32(flex.__class__):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config(32,12,6,1)
    
aa3_g32 = aa3_g32(**globals())