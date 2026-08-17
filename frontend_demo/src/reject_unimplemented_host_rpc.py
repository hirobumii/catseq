# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #52
# ENTRY: HostRpcExperiment.build_sequence
# EXPECT: reject
# CONTRACT: An undecorated exact function reached from BaseExp.build_sequence is a Host RPC leaf.
# CONTRACT: The unimplemented Host RPC call fails at its call site without publishing partial HIR.
# DIAGNOSTIC: unimplemented: host RPC calls are not implemented

from catseq import kernel
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a


def host_delay() -> Morphism:
    return Id() >> {correction_a: pulse(1 * us)}


class HostRpcExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return host_delay()
