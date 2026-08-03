from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar

import h5py

from catseq.experiment.analyzer import BaseAnalyzer
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import BaseDeviceIn, DeviceList
from catseq.experiment.h5 import H5Writer
from catseq.experiment.para_dict import ParaDict
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint
from catseq.experiment.result import BaseResult, create_result_field, list_field


@dataclass
class ReadingResult(BaseResult):
    signal: list[float] = list_field()


@dataclass
class Camera(BaseDeviceIn[ReadingResult]):
    gain: float = 2.0
    result: ReadingResult = create_result_field(ReadingResult)

    def post_init(self) -> None:
        pass

    def init_device(self) -> None:
        pass

    def read_list_dict(self):
        return []

    def post_close(self) -> None:
        pass


@dataclass
class Apparatus(DeviceList):
    camera: Camera = field(default_factory=Camera)


@dataclass
class MeanAnalyzer(BaseAnalyzer):
    means: list[float] = list_field()


@dataclass
class ExperimentRecord:
    amplitude: float = 0.5
    label: str = "tracer"
    runtime_handle: object = field(
        default_factory=object, metadata={"persist": False}, repr=False
    )
    device_list: Apparatus = field(default_factory=Apparatus)


class PointCompiler:
    def compile(self, entry, params: ExpParams):
        return {"entry": entry, "duration": params[PersistedExperiment.duration]}


class PointRuntime:
    def run(self, compiled):
        return compiled["duration"]


@dataclass
class PersistedExperiment(BaseExp):
    duration: ClassVar[ExpParam[Decimal]] = ExpParam("duration_us", "us")
    amplitude: float = 0.5
    device_list: Apparatus = field(default_factory=Apparatus)

    def config_generator(self) -> None:
        self.gen.add_descartes("scan", self.duration, [Decimal("1.25")])

    def build_sequence(self, params: ExpParams):
        raise AssertionError("the test compiler does not execute source")


def test_h5_writer_owns_the_complete_experiment_schema(tmp_path) -> None:
    duration = ExpParam[Decimal]("duration_us", "us")
    record = ExperimentRecord()
    record.para_dict = ParaDict()
    record.para_dict.append(
        ScanPoint(
            ExpParams({duration: Decimal("1.25")}),
            {"repeat_0": 0, "scan_0": 1},
            0,
        )
    )
    record.gen = DescartesGenerator()
    record.gen.add_descartes("repeat", 1)
    record.gen.add_descartes("scan", duration, [Decimal("1.25")])
    record.device_list.camera.result += ReadingResult(signal=[3.5])
    analyzer = MeanAnalyzer(means=[3.5])
    record._analyzer_pipeline = [analyzer]
    record._cleanup_errors = [ValueError("close failed")]
    record._panel_publisher_errors = ["publish: offline"]

    path = tmp_path / "experiment.h5"
    writer = H5Writer(path)
    writer.open(record)
    writer.write(record, run_error=RuntimeError("runtime failed"))
    writer.close()

    with h5py.File(path, "r") as h5_file:
        assert h5_file.attrs["schema_version"] == "1"
        assert h5_file.attrs["experiment_class"] == "ExperimentRecord"
        assert set(h5_file) == {
            "static_para",
            "dynamic_para",
            "descartes",
            "device",
            "analyze",
            "debug",
        }
        assert h5_file["static_para/amplitude"][()] == 0.5
        assert h5_file["static_para/label"].asstr()[()] == "tracer"
        assert "runtime_handle" not in h5_file["static_para"]
        assert h5_file["dynamic_para/duration_us"].asstr()[:].tolist() == [
            "1.25"
        ]
        assert h5_file["dynamic_para/__coord__scan_0"][:].tolist() == [1]
        assert h5_file["device/camera/result/signal"][:].tolist() == [3.5]
        assert h5_file["device/camera/gain"][()] == 2.0
        assert h5_file["analyze/MeanAnalyzer/means"][:].tolist() == [3.5]
        assert "runtime failed" in h5_file["debug/run_error"].asstr()[()]
        assert h5_file["debug/cleanup_errors"].asstr()[:].tolist() == [
            "ValueError('close failed')"
        ]


def test_base_exp_persists_its_completed_lifecycle(tmp_path) -> None:
    path = tmp_path / "base-exp.h5"
    experiment = PersistedExperiment(
        compiler=PointCompiler(),
        runtime=PointRuntime(),
        h5_writer=H5Writer(path),
    )

    experiment.run()

    with h5py.File(path, "r") as h5_file:
        assert h5_file["static_para/amplitude"][()] == 0.5
        assert h5_file["dynamic_para/duration_us"].asstr()[:].tolist() == [
            "1.25"
        ]
        assert h5_file["dynamic_para/__idx__"][:].tolist() == [0]
        assert h5_file["dynamic_para/__coord__scan_0"][:].tolist() == [0]
        assert "run_error" not in h5_file["debug"]
