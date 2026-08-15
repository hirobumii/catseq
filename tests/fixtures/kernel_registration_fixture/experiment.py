from dataclasses import dataclass

from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq import compute
from catseq.morphism import Morphism
from catseq.morphism.core import kernel

from . import helper
from .helper import external_helper, external_twice


external_twice_alias = external_twice


@compute
def external_normalize(value: int) -> int:
    return external_twice_alias(value) + 1


@compute
def external_attribute_normalize(value: int) -> int:
    return helper.external_twice(value) + 1


@dataclass
class MultiModuleExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        return external_helper(1)
