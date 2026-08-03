from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

import catseq.experiment as experiment
from catseq.experiment.base_module import BaseModule, BaseService
from catseq.experiment.params import (
    ExpParam,
    ExpParams,
    ScanPoint,
    compile_scan_values,
)


@dataclass
class PulseModule(BaseModule):
    duration_us: float = 1.0

    def init(self, hard: bool = False):
        del hard
        return None

    def channel_styles(self):
        return {}

    @property
    def default_state(self):
        return {}


@dataclass
class PulseService(BaseService):
    module: PulseModule = field(default_factory=PulseModule)

    @property
    def module_list(self):
        return [self.module]


def test_experiment_namespace_does_not_bulk_reexport_public_types() -> None:
    assert not hasattr(experiment, "BaseModule")
    assert not hasattr(experiment, "BaseService")
    assert not hasattr(experiment, "BaseExp")


def test_module_and_service_preserve_composition() -> None:
    module = PulseModule(duration_us=2.5)
    service = PulseService(module=module)

    assert module.duration_us == 2.5
    assert service.module is module


def test_exp_params_are_immutable_and_keyed_by_declaration_identity() -> None:
    first = ExpParam[float]("duration_us", unit="us")
    second = ExpParam[float]("duration_us", unit="us")
    params = ExpParams({first: 1.0, second: 2.0})

    assert params[first] == 1.0
    assert params[second] == 2.0
    assert first is not second
    with pytest.raises(TypeError):
        params.mapping[first] = 3.0  # type: ignore[index]


def test_scan_point_freezes_tensor_coordinates() -> None:
    duration = ExpParam[float]("duration_us")
    coordinates = {"repeat_0": 1, "scan_0": 2}
    point = ScanPoint(
        params=ExpParams({duration: 4.0}),
        coordinates=coordinates,
        execution_index=7,
    )
    coordinates["scan_0"] = 9

    assert dict(point.tensor_coordinates) == {"repeat_0": 1, "scan_0": 2}
    with pytest.raises(TypeError):
        point.coordinates["scan_0"] = 3  # type: ignore[index]


def test_compile_scan_values_distinguishes_ranges_from_explicit_values() -> None:
    assert compile_scan_values((Decimal("0.1"), Decimal("0.3"), Decimal("0.1"))) == (
        Decimal("0.1"),
        Decimal("0.2"),
        Decimal("0.3"),
    )
    assert compile_scan_values([0.1, 0.3, 0.1]) == (0.1, 0.3, 0.1)
