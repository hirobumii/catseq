# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #52
# ENTRY: SourceHirExperiment.build_sequence
# EXPECT: accept
# CONTRACT: The exact registered BaseExp.build_sequence object is the sole analysis root.
# CONTRACT: One referenced ExpParam and one direct Kernel callee enter TypedSourceHir.
# CONTRACT: An unused ExpParam and registered Kernel definition do not enter the reachable HIR.

from typing import ClassVar

from catseq import kernel
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.morphism import Id, Morphism, Wait
from catseq.time_utils import cycles


@kernel
def make_delay(width: int) -> Morphism:
    return Id() >> Wait(cycles(width)) >> Wait(cycles(2))


@kernel
def unused_delay() -> Morphism:
    return Wait(cycles(99))


class SourceHirExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")
    unused_width: ClassVar[ExpParam[int]] = ExpParam("unused_width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        width = params[self.width]
        return make_delay(width)
