from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from catseq.experiment.analyzer import AnalyzerConfig, BaseAnalyzer
from catseq.experiment.device import (
    BaseDeviceIn,
    BaseDeviceOut,
    DeviceList,
)
from catseq.experiment.indexer import Indexer
from catseq.experiment.panel import NullPanelPublisher, PanelUpdate
from catseq.experiment.result import BaseResult, create_result_field, list_field


@dataclass
class ReadingResult(BaseResult):
    values: list[int] = list_field()
    labels: list[str] = list_field()


@dataclass
class RecordingInput(BaseDeviceIn[ReadingResult]):
    events: list[str] = field(default_factory=list)
    result: ReadingResult = create_result_field(ReadingResult)

    def post_init(self) -> None:
        self.events.append("input-start")

    def init_device(self) -> None:
        self.events.append("input-init")

    def read_list_dict(self) -> list[dict[str, object]]:
        self.events.append("input-read")
        return [{"values": 3, "labels": "ready"}]

    def post_close(self) -> None:
        self.events.append("input-close")


@dataclass
class RecordingOutput(BaseDeviceOut):
    events: list[str] = field(default_factory=list)

    def post_init(self) -> None:
        self.events.append("output-start")

    def init_device(self) -> None:
        self.events.append("output-init")

    def config(self) -> None:
        self.events.append("output-config")

    def post_close(self) -> None:
        self.events.append("output-close")


@dataclass
class Apparatus(DeviceList):
    camera: RecordingInput = field(default_factory=RecordingInput)
    source: RecordingOutput = field(default_factory=RecordingOutput)


@dataclass
class AnalysisSettings(AnalyzerConfig):
    threshold: int = 2


@dataclass
class ReadingAnalyzer(BaseAnalyzer):
    def request_dependencies(self, request) -> bool:
        self.camera = request(RecordingInput)
        self.settings = request(AnalysisSettings)
        return self.camera is not None and self.settings is not None


def test_base_result_appends_typed_rows_and_tracks_the_latest_slice() -> None:
    result = ReadingResult.from_list_dict(
        [
            {"values": 1, "labels": "first"},
            {"values": 2, "labels": "second"},
        ]
    )
    result += ReadingResult.from_list_dict([{"values": 3, "labels": "third"}])

    assert result.values == [1, 2, 3]
    assert result.labels == ["first", "second", "third"]
    assert result.last_slice() == slice(2, 3)
    with pytest.raises(ValueError, match="undeclared result keys"):
        ReadingResult.from_list_dict([{"values": 1, "labels": "x", "extra": 4}])


def test_two_device_lists_are_independent_and_run_the_same_lifecycle() -> None:
    first = Apparatus()
    second = Apparatus()

    first.start_run()
    first.config()
    first.init_device()
    first.read()
    first.post_close()

    assert first is not second
    assert first.camera is not second.camera
    assert first.camera.result.values == [3]
    assert second.camera.result.values == []
    assert first.camera.events == [
        "input-start",
        "input-init",
        "input-read",
        "input-close",
    ]
    assert first.source.events == [
        "output-start",
        "output-config",
        "output-init",
        "output-close",
    ]


def test_indexer_resolves_exact_dependencies_and_reports_ambiguity() -> None:
    apparatus = Apparatus()
    settings = AnalysisSettings(threshold=5)
    analyzer = ReadingAnalyzer()
    root = {"apparatus": apparatus, "settings": settings, "analyzers": [analyzer]}
    indexer = Indexer(root)

    assert indexer.request_one(RecordingInput) is apparatus.camera
    assert indexer.request_one(AnalysisSettings) is settings
    assert indexer.request(BaseAnalyzer, strict=False) == [analyzer]

    with pytest.raises(LookupError, match="ambiguous"):
        Indexer([Apparatus(), Apparatus()]).request_one(RecordingInput)


def test_analyzer_can_disable_itself_when_a_dependency_is_missing() -> None:
    analyzer = ReadingAnalyzer()
    indexer = Indexer({"apparatus": Apparatus()})

    assert analyzer.request_dependencies(indexer.request_one) is False


def test_null_panel_publisher_preserves_run_identity_without_transport() -> None:
    publisher = NullPanelPublisher(run_id="local run")
    update = PanelUpdate(
        name="loading rate",
        title="Loading",
        data=[{"x": [1], "y": [0.5]}],
    )

    publisher.start()
    assert publisher.run_id == "local_run"
    assert publisher.publish(update) == ""
    publisher.finish()
    publisher.close()
