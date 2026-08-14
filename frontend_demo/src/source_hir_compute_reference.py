# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #52
# ENTRY: ComputeReferenceExperiment.build_sequence
# EXPECT: accept
# CONTRACT: An exact registered @compute call is one opaque typed Compute reference in CatSeq HIR.
# CONTRACT: CatSeq records argument, result, identity, availability, and provenance without a Compute CFG.
# CONTRACT: NAC3 validates the reachable Compute body and returns its sealed interface before HIR publication.

from typing import ClassVar

from catseq import compute, kernel
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.morphism import Morphism, identity
from catseq.time_utils import cycles


@compute
def normalize_width(width: int) -> int:
    if width < 1:
        return 1
    return width


class ComputeReferenceExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        width = normalize_width(params[self.width])
        return identity(cycles(width))
