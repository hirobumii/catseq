from dataclasses import dataclass

from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq.morphism import Morphism
from catseq.morphism.core import kernel

from .helper import external_helper


@dataclass
class MultiModuleExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        return external_helper(1)
