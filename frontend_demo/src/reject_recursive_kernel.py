# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Runtime recursion cannot contribute statically bounded Control topology.
# DIAGNOSTIC: recursive kernel call

from catseq import kernel
from catseq.morphism import Morphism


@kernel
def sequence() -> Morphism:
    return sequence()
