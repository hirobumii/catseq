from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import cast

import pytest

from catseq.experiment.analyzer import BaseAnalyzer, _sort_analyzer_classes
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import DeviceList
from catseq.experiment.h5 import H5Writer
from catseq.experiment.panel import PanelUpdate
from catseq.experiment.params import ExpParams
from catseq.morphism import Morphism


class RecordingWriter:
    def __init__(self) -> None:
        self.events: list[str] = []

    def open(self, experiment: BaseExp) -> None:
        del experiment
        self.events.append("open")

    def write(self, experiment: BaseExp, *, run_error: BaseException | None) -> None:
        del experiment, run_error
        self.events.append("write")

    def close(self) -> None:
        self.events.append("close")


class RecordingPublisher:
    run_id = "run-123"

    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def publish(self, update: PanelUpdate) -> str:
        del update
        self.events.append("publish")
        return "panel"

    def finish(self) -> None:
        self.events.append("finish")

    def close(self) -> None:
        self.events.append("close")


@dataclass
class RecordingDeviceList(DeviceList):
    events: list[str] = field(default_factory=list)

    def start_run(self) -> None:
        self.events.append("start")

    def init_device(self) -> None:
        self.events.append("init")

    def read(self) -> None:
        self.events.append("read")

    def post_close(self) -> None:
        self.events.append("close")


@dataclass
class InertExperiment(BaseExp):
    lifecycle_events: list[str] = field(default_factory=list)
    device_list: RecordingDeviceList = field(default_factory=RecordingDeviceList)

    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        self.lifecycle_events.append("build_sequence")
        raise AssertionError("BaseExp.run() must not execute registered source")

    def config_generator(self) -> None:
        self.lifecycle_events.append("config_generator")

    def prepare_run(self) -> None:
        self.lifecycle_events.append("prepare_run")

    def final_analyzer(self, gen: DescartesGenerator) -> None:
        del gen
        self.lifecycle_events.append("final_analyzer")

    def finish(self) -> None:
        self.lifecycle_events.append("finish")


def test_base_exp_run_fails_before_removed_pipeline_side_effects() -> None:
    writer = RecordingWriter()
    publisher = RecordingPublisher()
    experiment = InertExperiment(
        h5_writer=cast(H5Writer, writer),
        panel_publisher=publisher,
    )

    with pytest.raises(
        NotImplementedError,
        match="public end-to-end compiler and execution pipeline is unavailable",
    ):
        experiment.run()

    field_names = {definition.name for definition in fields(BaseExp)}
    assert {"compiler", "runtime"}.isdisjoint(field_names)
    assert writer.events == []
    assert publisher.events == []
    assert experiment.device_list.events == []
    assert experiment.lifecycle_events == []
    assert len(experiment.para_dict) == 0


@dataclass
class CycleA(BaseAnalyzer):
    @classmethod
    def dependent_analyzers(cls) -> tuple[type[BaseAnalyzer], ...]:
        return (CycleB,)


@dataclass
class CycleB(BaseAnalyzer):
    @classmethod
    def dependent_analyzers(cls) -> tuple[type[BaseAnalyzer], ...]:
        return (CycleA,)


def test_analyzer_dependency_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="CycleA -> CycleB -> CycleA"):
        _sort_analyzer_classes((CycleA,))
