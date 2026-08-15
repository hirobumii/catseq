"""Host-side orchestration for one experiment lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from catseq.morphism import Morphism

from .analyzer import BaseAnalyzer, _sort_analyzer_classes
from .descartes import DescartesGenerator
from .device import DeviceList
from .indexer import Indexer
from .panel import (
    NullPanelPublisher,
    PanelPublisher,
    PanelUpdate,
    local_run_id,
)
from .para_dict import ParaDict
from .params import ExpParams, ScanPoint
from .run_control import RunControl

if TYPE_CHECKING:
    from .h5 import H5Writer


@dataclass
class BaseExp(ABC):
    """Coordinate traversal, point execution, analysis, and persistence.

    Experiment orchestration runs as ordinary Python.  At each attempted scan
    point, only ``build_sequence`` and that point's parameters are handed to
    the CatSeq compiler.  While the current compiled sequence runs, BaseExp
    compiles one immutable scan point ahead.  Sequence configuration outside
    ``ExpParams`` must therefore remain stable for the duration of a run.
    """

    compiler: Any = field(kw_only=True, repr=False, metadata={"persist": False})
    runtime: Any = field(kw_only=True, repr=False, metadata={"persist": False})
    h5_writer: H5Writer = field(
        kw_only=True, repr=False, metadata={"persist": False}
    )
    run_control: RunControl = field(
        default_factory=RunControl,
        kw_only=True,
        repr=False,
        metadata={"persist": False},
    )
    panel_publisher: PanelPublisher | None = field(
        default=None,
        kw_only=True,
        repr=False,
        metadata={"persist": False},
    )
    device_list: DeviceList = field(default_factory=DeviceList)

    def __post_init__(self) -> None:
        self.para_dict = ParaDict()
        self._analyzer_pipeline: list[BaseAnalyzer] = []
        self._panel_publisher = self.panel_publisher or NullPanelPublisher(
            run_id=local_run_id(self.__class__.__name__)
        )
        self.dashboard_exp_id = self._panel_publisher.run_id
        self.panels: list[str] = []
        self._panel_publisher_errors: list[str] = []
        self._cleanup_errors: list[BaseException] = []
        self._panel_publisher_started = False
        self._h5_opened = False
        self._device_run_started = False
        self._compile_executor: ThreadPoolExecutor | None = None
        self._next_compilation: Future[Any] | None = None
        self._running = False

    @abstractmethod
    def build_sequence(self, params: ExpParams) -> Morphism:
        """Define the CatSeq sequence compiled for one scan point."""

    def config_generator(self) -> None:
        """Declare repeat and scan nodes through ``self.gen``."""

    def required_analyzers(self) -> tuple[type[BaseAnalyzer], ...]:
        return ()

    def prepare_run(self) -> None:
        """Perform experiment setup after devices have started."""

    def apply_scan_params_to_devices(self, scan_point: ScanPoint) -> None:
        """Apply one point's parameters to device configuration."""

    def final_analyzer(self, gen: DescartesGenerator) -> None:
        """Run a local callback after one point completes successfully."""

    def finish(self) -> None:
        """Release experiment-specific resources during cleanup."""

    def run(self) -> None:
        """Run the complete experiment lifecycle."""

        if self._running:
            raise RuntimeError("an experiment lifecycle is already active")

        self._running = True
        run_error: BaseException | None = None
        run_traceback = None
        try:
            self._panel_publisher_started = True
            self._call_panel_publisher("start", self._panel_publisher.start)

            self.h5_writer.open(self)
            self._h5_opened = True

            self._device_run_started = True
            self.device_list.start_run()
            self.prepare_run()

            self.gen = DescartesGenerator(streaming_analyze=self._streaming_analyze)
            self.gen.is_exp_running = self.run_control.checkpoint
            self.config_generator()
            self.gen.final_exp(
                self.para_dict.append_point,
                self._execute_point,
                self.final_analyzer,
            )

            self._analyzer_pipeline = [
                analyzer_class()
                for analyzer_class in _sort_analyzer_classes(
                    self.required_analyzers()
                )
            ]
            self.indexer = Indexer(self)
            for analyzer in self._analyzer_pipeline:
                dependencies_satisfied = analyzer.request_dependencies(
                    self.indexer.request_one
                )
                analyzer._dependencies_satisfied = dependencies_satisfied is not False

            self.run_control.start()
            compile_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="catseq-compile",
            )
            self._compile_executor = compile_executor
            try:
                self.gen.call_next()
            finally:
                wait_for_compiler = self._next_compilation is None
                self._compile_executor = None
                self._next_compilation = None
                compile_executor.shutdown(
                    wait=wait_for_compiler,
                    cancel_futures=True,
                )
            for analyzer in self._analyzer_pipeline:
                if analyzer._dependencies_satisfied:
                    self._publish_analyzer_updates(analyzer, analyzer.analyze())
        except BaseException as error:
            run_error = error
            run_traceback = error.__traceback__
        finally:
            self._cleanup(run_error)
            self._running = False

        if run_error is not None:
            raise run_error.with_traceback(run_traceback)
        if len(self._cleanup_errors) == 1:
            raise self._cleanup_errors[0]
        if self._cleanup_errors:
            raise BaseExceptionGroup(
                "BaseExp cleanup failures", self._cleanup_errors
            )

    def _execute_point(self, scan_point: ScanPoint) -> Any:
        if self._next_compilation is None:
            compiled = self.compiler.compile(self.build_sequence, scan_point.params)
        else:
            compilation = self._next_compilation
            self._next_compilation = None
            compiled = compilation.result()

        self.apply_scan_params_to_devices(scan_point)
        self.device_list.init_device()

        next_point = self.gen._next_scan_point(scan_point)
        if next_point is not None and self._compile_executor is not None:
            self._next_compilation = self._compile_executor.submit(
                self.compiler.compile,
                self.build_sequence,
                next_point.params,
            )

        result = self.runtime.run(compiled)
        self.device_list.read()
        return result

    def _streaming_analyze(self, caller_name: str, order: int) -> None:
        for analyzer in self._analyzer_pipeline:
            if analyzer._dependencies_satisfied:
                self._publish_analyzer_updates(
                    analyzer,
                    analyzer.streaming_analyze(caller_name, order),
                )

    def _publish_analyzer_updates(
        self,
        analyzer: BaseAnalyzer,
        result: PanelUpdate | tuple[PanelUpdate, ...] | list[PanelUpdate] | None,
    ) -> None:
        if result is None:
            return
        updates = (result,) if isinstance(result, PanelUpdate) else tuple(result)
        if not all(isinstance(update, PanelUpdate) for update in updates):
            raise TypeError(
                f"{analyzer.__class__.__name__} returned a non-PanelUpdate result"
            )
        for update in updates:
            if update.analyzer is None:
                update = replace(update, analyzer=analyzer.__class__.__name__)
            panel_id = self._call_panel_publisher(
                "publish", lambda: self._panel_publisher.publish(update)
            )
            if panel_id and panel_id not in self.panels:
                self.panels.append(panel_id)

    def _cleanup(self, run_error: BaseException | None) -> None:
        cleanup_errors: list[BaseException] = []

        def attempt(operation) -> None:
            try:
                operation()
            except BaseException as error:
                cleanup_errors.append(error)
                self._cleanup_errors = list(cleanup_errors)

        attempt(self.run_control.finish)
        attempt(self.finish)
        if self._device_run_started:
            attempt(self.device_list.post_close)
            self._device_run_started = False

        if self._panel_publisher_started:
            self._call_panel_publisher("finish", self._panel_publisher.finish)
            self._call_panel_publisher("close", self._panel_publisher.close)
            self._panel_publisher_started = False

        if self._h5_opened:
            attempt(lambda: self.h5_writer.write(self, run_error=run_error))
            attempt(self.h5_writer.close)
            self._h5_opened = False

        self._cleanup_errors = cleanup_errors

    def _call_panel_publisher(self, stage: str, operation):
        try:
            return operation()
        except Exception as error:
            self._panel_publisher_errors.append(
                f"{stage}: {str(error) or type(error).__name__}"
            )
            return None


__all__ = ["BaseExp"]
