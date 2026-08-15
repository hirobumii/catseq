from catseq import compute
from catseq.morphism import Morphism
from catseq.morphism.core import kernel


@kernel
def external_helper(width: int) -> Morphism:
    del width
    raise AssertionError("registered Kernel bodies must not execute")


@compute
def external_twice(value: int) -> int:
    return value * 2
