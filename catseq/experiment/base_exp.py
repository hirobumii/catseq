"""Experiment source ownership during the frontend migration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Never

from catseq.morphism import Morphism

from .analyzer import BaseAnalyzer
from .descartes import DescartesGenerator
from .device import DeviceList
from .panel import NullPanelPublisher, PanelPublisher, local_run_id
from .para_dict import ParaDict
from .params import ExpParams, ScanPoint
from .run_control import RunControl

if TYPE_CHECKING:
    from .h5 import H5Writer


@dataclass
class BaseExp(ABC):
    """Own an experiment's registered source and host-side declarations.

    The registered-source frontend accepts an actual ``BaseExp`` instance and
    its ``build_sequence`` entry.  CatSeq does not currently provide a public
    end-to-end compiler and experiment runner, so ``run`` fails before starting
    any experiment lifecycle work.
    """

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

    def run(self) -> Never:
        """Reject the unavailable public end-to-end execution path."""

        raise NotImplementedError(
            "BaseExp.run(): the public end-to-end compiler and execution pipeline "
            "is unavailable during the registered-source frontend migration"
        )


__all__ = ["BaseExp"]
