from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from threading import Event
from typing import ClassVar

import pytest

from catseq.experiment.analyzer import BaseAnalyzer
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import BaseDeviceIn, DeviceList
from catseq.experiment.panel import PanelUpdate
from catseq.experiment.params import ExpParam, ExpParams
from catseq.experiment.result import BaseResult, create_result_field, list_field


@dataclass
class ReadingResult(BaseResult):
    values: list[int] = list_field()


@dataclass
class RecordingDevice(BaseDeviceIn[ReadingResult]):
    events: list[str] = field(default_factory=list)
    result: ReadingResult = create_result_field(ReadingResult)

    def post_init(self) -> None:
        self.events.append("start")

    def init_device(self) -> None:
        self.events.append("init")

    def read_list_dict(self):
        self.events.append("read")
        return [{"values": 1}]

    def post_close(self) -> None:
        self.events.append("close")


@dataclass
class Apparatus(DeviceList):
    detector: RecordingDevice = field(default_factory=RecordingDevice)


class RecordingCompiler:
    def __init__(self, *, fail_value: float | None = None) -> None:
        self.fail_value = fail_value
        self.calls: list[tuple[object, ExpParams]] = []

    def compile(self, entry, params: ExpParams):
        self.calls.append((entry, params))
        value = params[TracerExperiment.duration]
        if value == self.fail_value:
            raise RuntimeError(f"compile failed at {value}")
        return {"duration": value}


class RecordingRuntime:
    def __init__(self, *, fail_value: float | None = None, on_run=None) -> None:
        self.fail_value = fail_value
        self.on_run = on_run
        self.compiled: list[dict[str, float]] = []

    def run(self, compiled):
        self.compiled.append(compiled)
        if self.on_run is not None:
            self.on_run()
        if compiled["duration"] == self.fail_value:
            raise RuntimeError(f"runtime failed at {compiled['duration']}")
        return {"ok": True}


class BlockingSecondCompiler(RecordingCompiler):
    def __init__(self) -> None:
        super().__init__()
        self.second_started = Event()
        self.release_second = Event()

    def compile(self, entry, params: ExpParams):
        self.calls.append((entry, params))
        value = params[TracerExperiment.duration]
        if value == 2.0 and not self.second_started.is_set():
            self.second_started.set()
            if not self.release_second.wait(timeout=2):
                raise RuntimeError("second compilation was not released")
        return {"duration": value}


class OverlapRuntime(RecordingRuntime):
    def __init__(self, compiler: BlockingSecondCompiler) -> None:
        super().__init__()
        self.compiler = compiler
        self.first_finished = Event()

    def run(self, compiled):
        self.compiled.append(compiled)
        if len(self.compiled) == 1:
            if not self.compiler.second_started.wait(timeout=1):
                raise RuntimeError("next point was not compiling during runtime")
            self.first_finished.set()
        if self.on_run is not None:
            self.on_run()
        return {"ok": True}


class FailingOverlapRuntime(OverlapRuntime):
    def run(self, compiled):
        super().run(compiled)
        raise RuntimeError(f"runtime failed at {compiled['duration']}")


class RecordingWriter:
    def __init__(self) -> None:
        self.events: list[object] = []

    def open(self, experiment) -> None:
        self.events.append(("open", experiment.__class__.__name__))

    def write(self, experiment, *, run_error=None) -> None:
        self.events.append(("write", run_error, len(experiment.para_dict)))

    def close(self) -> None:
        self.events.append("close")


class RecordingPublisher:
    run_id = "run-123"

    def __init__(self) -> None:
        self.events: list[object] = []

    def start(self) -> None:
        self.events.append("start")

    def publish(self, update: PanelUpdate) -> str:
        self.events.append(("publish", update))
        return f"panel-{update.name}"

    def finish(self) -> None:
        self.events.append("finish")

    def close(self) -> None:
        self.events.append("close")


@dataclass
class RecordingAnalyzer(BaseAnalyzer):
    streaming: list[tuple[str, int]] = field(default_factory=list)
    final_calls: int = 0

    def request_dependencies(self, request) -> bool:
        self.device = request(RecordingDevice)
        self.generator = request(DescartesGenerator)
        self.experiment = request(BaseExp)
        return all(
            dependency is not None
            for dependency in (self.device, self.generator, self.experiment)
        )

    def streaming_analyze(self, caller_name: str, order: int):
        self.streaming.append((caller_name, order))
        if caller_name == "final_exp":
            return PanelUpdate(name="progress", data=[order])
        return None

    def analyze(self):
        self.final_calls += 1
        return PanelUpdate(name="summary", data=[self.final_calls])


@dataclass
class TracerExperiment(BaseExp):
    duration: ClassVar[ExpParam[float]] = ExpParam("duration_us", "us")
    device_list: Apparatus = field(default_factory=Apparatus)

    def config_generator(self) -> None:
        self.gen.add_descartes("repeat", 2)
        self.gen.add_descartes("scan", self.duration, [1.0, 2.0])

    def required_analyzers(self):
        return (RecordingAnalyzer,)

    def build_sequence(self, params: ExpParams):
        raise AssertionError(
            "the host test compiler must inspect build_sequence without executing it"
        )


@dataclass
class IndexedExperiment(BaseExp):
    repetition: ClassVar[ExpParam[int]] = ExpParam("repetition")
    duration: ClassVar[ExpParam[float]] = ExpParam("duration_us", "us")

    def config_generator(self) -> None:
        self.gen.add_descartes("repeat", 2, idx_param=self.repetition)
        self.gen.add_descartes("scan", self.duration, [1.0, 2.0])

    def build_sequence(self, params: ExpParams):
        raise AssertionError(
            "the host test compiler must inspect build_sequence without executing it"
        )


class IndexedCompiler:
    def __init__(self) -> None:
        self.calls: list[tuple[int, float]] = []

    def compile(self, entry, params: ExpParams):
        del entry
        point = (
            params[IndexedExperiment.repetition],
            params[IndexedExperiment.duration],
        )
        self.calls.append(point)
        return {"repetition": point[0], "duration": point[1]}


def make_experiment(
    *,
    compiler: RecordingCompiler | None = None,
    runtime: RecordingRuntime | None = None,
    writer: RecordingWriter | None = None,
    publisher: RecordingPublisher | None = None,
) -> tuple[
    TracerExperiment,
    RecordingCompiler,
    RecordingRuntime,
    RecordingWriter,
    RecordingPublisher,
]:
    compiler = compiler or RecordingCompiler()
    runtime = runtime or RecordingRuntime()
    writer = writer or RecordingWriter()
    publisher = publisher or RecordingPublisher()
    return (
        TracerExperiment(
            compiler=compiler,
            runtime=runtime,
            h5_writer=writer,
            panel_publisher=publisher,
        ),
        compiler,
        runtime,
        writer,
        publisher,
    )


def test_base_exp_compiles_and_runs_each_attempted_scan_point() -> None:
    experiment, compiler, runtime, writer, publisher = make_experiment()

    experiment.run()

    assert [params[experiment.duration] for _, params in compiler.calls] == [
        1.0,
        2.0,
        1.0,
        2.0,
    ]
    assert all(
        entry.__self__ is experiment
        and entry.__func__ is TracerExperiment.build_sequence
        for entry, _ in compiler.calls
    )
    assert runtime.compiled == [
        {"duration": 1.0},
        {"duration": 2.0},
        {"duration": 1.0},
        {"duration": 2.0},
    ]
    assert experiment.para_dict.execution_indexes == (0, 1, 2, 3)
    assert experiment.device_list.detector.result.values == [1, 1, 1, 1]
    assert experiment.device_list.detector.events == [
        "start",
        "init",
        "read",
        "init",
        "read",
        "init",
        "read",
        "init",
        "read",
        "close",
    ]
    analyzer = experiment._analyzer_pipeline[0]
    assert analyzer.experiment is experiment
    assert analyzer.final_calls == 1
    assert writer.events == [
        ("open", "TracerExperiment"),
        ("write", None, 4),
        "close",
    ]
    assert publisher.events[0] == "start"
    assert publisher.events[-2:] == ["finish", "close"]
    assert experiment.dashboard_exp_id == "run-123"
    assert experiment.panels == ["panel-progress", "panel-summary"]


def test_base_exp_compiles_the_next_point_while_the_current_point_runs() -> None:
    compiler = BlockingSecondCompiler()
    runtime = OverlapRuntime(compiler)
    experiment, _, _, _, _ = make_experiment(
        compiler=compiler,
        runtime=runtime,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(experiment.run)
        try:
            assert compiler.second_started.wait(timeout=1)
            assert runtime.first_finished.wait(timeout=1)
            with pytest.raises(TimeoutError):
                running.result(timeout=0.02)
            assert runtime.compiled == [{"duration": 1.0}]
        finally:
            compiler.release_second.set()
        running.result(timeout=2)

    assert [params[experiment.duration] for _, params in compiler.calls] == [
        1.0,
        2.0,
        1.0,
        2.0,
    ]
    assert [compiled["duration"] for compiled in runtime.compiled] == [
        1.0,
        2.0,
        1.0,
        2.0,
    ]


def test_lookahead_preserves_nested_repeat_parameters_and_coordinates() -> None:
    compiler = IndexedCompiler()
    runtime = RecordingRuntime()
    experiment = IndexedExperiment(
        compiler=compiler,
        runtime=runtime,
        h5_writer=RecordingWriter(),
    )

    experiment.run()

    assert compiler.calls == [(0, 1.0), (0, 2.0), (1, 1.0), (1, 2.0)]
    assert runtime.compiled == [
        {"repetition": 0, "duration": 1.0},
        {"repetition": 0, "duration": 2.0},
        {"repetition": 1, "duration": 1.0},
        {"repetition": 1, "duration": 2.0},
    ]
    assert experiment.para_dict.coordinate_values("repeat_0") == (0, 0, 1, 1)
    assert experiment.para_dict.coordinate_values("scan_0") == (0, 1, 0, 1)


def test_runtime_failure_does_not_wait_for_speculative_compilation() -> None:
    compiler = BlockingSecondCompiler()
    experiment, _, _, _, _ = make_experiment(
        compiler=compiler,
        runtime=FailingOverlapRuntime(compiler),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(experiment.run)
        try:
            with pytest.raises(RuntimeError, match="runtime failed at 1.0"):
                running.result(timeout=1)
            assert experiment.device_list.detector.events == ["start", "init", "close"]
        finally:
            compiler.release_second.set()


def test_compile_failure_records_attempt_before_stopping() -> None:
    experiment, _, runtime, writer, _ = make_experiment(
        compiler=RecordingCompiler(fail_value=1.0)
    )

    with pytest.raises(RuntimeError, match="compile failed at 1.0"):
        experiment.run()

    assert experiment.para_dict.execution_indexes == (0,)
    assert runtime.compiled == []
    assert experiment.device_list.detector.events == ["start", "close"]
    assert experiment._analyzer_pipeline[0].final_calls == 0
    assert isinstance(writer.events[1][1], RuntimeError)


def test_prefetched_compile_failure_is_raised_when_that_point_is_attempted() -> None:
    experiment, compiler, runtime, writer, _ = make_experiment(
        compiler=RecordingCompiler(fail_value=2.0)
    )

    with pytest.raises(RuntimeError, match="compile failed at 2.0"):
        experiment.run()

    assert [params[experiment.duration] for _, params in compiler.calls] == [
        1.0,
        2.0,
    ]
    assert experiment.para_dict.execution_indexes == (0, 1)
    assert runtime.compiled == [{"duration": 1.0}]
    assert experiment.device_list.detector.events == [
        "start",
        "init",
        "read",
        "close",
    ]
    assert isinstance(writer.events[1][1], RuntimeError)


def test_runtime_failure_keeps_the_attempt_and_closes_devices() -> None:
    experiment, compiler, _, writer, _ = make_experiment(
        runtime=RecordingRuntime(fail_value=1.0)
    )

    with pytest.raises(RuntimeError, match="runtime failed at 1.0"):
        experiment.run()

    assert [params[experiment.duration] for _, params in compiler.calls] == [
        1.0,
        2.0,
    ]
    assert experiment.para_dict.execution_indexes == (0,)
    assert experiment.device_list.detector.events == ["start", "init", "close"]
    assert isinstance(writer.events[1][1], RuntimeError)


def test_cancellation_stops_before_next_point_and_runs_final_analysis() -> None:
    compiler = BlockingSecondCompiler()
    runtime = OverlapRuntime(compiler)
    experiment, _, _, _, _ = make_experiment(compiler=compiler, runtime=runtime)
    runtime.on_run = experiment.run_control.request_stop

    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(experiment.run)
        try:
            running.result(timeout=1)
        finally:
            compiler.release_second.set()

    assert [params[experiment.duration] for _, params in compiler.calls] == [
        1.0,
        2.0,
    ]
    assert experiment.para_dict.execution_indexes == (0,)
    assert experiment._analyzer_pipeline[0].final_calls == 1


@dataclass
class MissingDependencyAnalyzer(BaseAnalyzer):
    def request_dependencies(self, request) -> bool:
        del request
        return False

    def analyze(self):
        raise AssertionError("disabled analyzer must not run")


@dataclass
class MissingDependencyExperiment(TracerExperiment):
    def required_analyzers(self):
        return (MissingDependencyAnalyzer,)


def test_analyzer_with_missing_dependencies_is_disabled() -> None:
    compiler = RecordingCompiler()
    runtime = RecordingRuntime()
    writer = RecordingWriter()
    experiment = MissingDependencyExperiment(
        compiler=compiler,
        runtime=runtime,
        h5_writer=writer,
    )

    experiment.run()

    assert experiment._analyzer_pipeline[0]._dependencies_satisfied is False


@dataclass
class CycleA(BaseAnalyzer):
    @classmethod
    def dependent_analyzers(cls):
        return (CycleB,)


@dataclass
class CycleB(BaseAnalyzer):
    @classmethod
    def dependent_analyzers(cls):
        return (CycleA,)


@dataclass
class CycleExperiment(TracerExperiment):
    def required_analyzers(self):
        return (CycleA,)


def test_analyzer_dependency_cycle_fails_before_point_execution() -> None:
    experiment = CycleExperiment(
        compiler=RecordingCompiler(),
        runtime=RecordingRuntime(),
        h5_writer=RecordingWriter(),
    )

    with pytest.raises(ValueError, match="CycleA -> CycleB -> CycleA"):
        experiment.run()

    assert len(experiment.para_dict) == 0
