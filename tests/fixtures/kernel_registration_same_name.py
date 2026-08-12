from catseq.morphism import Morphism
from catseq.morphism.core import kernel


@kernel
def same_name_helper() -> Morphism:
    raise AssertionError("registered Kernel bodies must not execute")
