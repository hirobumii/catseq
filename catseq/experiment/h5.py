"""Concrete H5 persistence for one completed or failed experiment run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, cast

import h5py  # type: ignore[import-untyped]
import numpy as np

from .device import BaseDeviceIn


class H5Writer:
    """Write the CatSeq experiment schema to one new H5 file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: h5py.File | None = None

    def open(self, experiment: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = h5py.File(self.path, "x")
        self._file.attrs["schema_version"] = "1"
        self._file.attrs["experiment_class"] = experiment.__class__.__name__

    def write(
        self,
        experiment: object,
        *,
        run_error: BaseException | None = None,
    ) -> None:
        h5_file = self._require_file()
        self._write_static(h5_file.require_group("static_para"), experiment)
        self._write_dynamic(h5_file.require_group("dynamic_para"), experiment)
        self._write_descartes(h5_file.require_group("descartes"), experiment)
        self._write_devices(h5_file.require_group("device"), experiment)
        self._write_analyzers(h5_file.require_group("analyze"), experiment)
        self._write_debug(
            h5_file.require_group("debug"), experiment, run_error=run_error
        )
        h5_file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _require_file(self) -> h5py.File:
        if self._file is None:
            raise RuntimeError("H5Writer.open() must be called before write()")
        return self._file

    @staticmethod
    def _write_static(group: h5py.Group, experiment: object) -> None:
        if not is_dataclass(experiment):
            return
        for item in fields(experiment):
            if (
                item.name.startswith("_")
                or item.name == "device_list"
                or item.metadata.get("persist", True) is False
            ):
                continue
            _write_value(group, item.name, getattr(experiment, item.name))

    @staticmethod
    def _write_dynamic(group: h5py.Group, experiment: object) -> None:
        para_dict = getattr(experiment, "para_dict", None)
        if para_dict is None:
            return
        for name, values in para_dict.columns.items():
            _write_value(group, name, values)

    @staticmethod
    def _write_descartes(group: h5py.Group, experiment: object) -> None:
        generator = getattr(experiment, "gen", None)
        if generator is None:
            return
        descriptions = [
            json.dumps(dict(node), default=str, sort_keys=True)
            for node in generator.node_descriptions
        ]
        _write_value(group, "nodes", descriptions)

    @staticmethod
    def _write_devices(group: h5py.Group, experiment: object) -> None:
        device_list = getattr(experiment, "device_list", None)
        if device_list is None:
            return
        for name, device in device_list.devices():
            device_group = group.require_group(name)
            if isinstance(device, BaseDeviceIn):
                _write_dataclass(
                    device_group.require_group("result"), device.result
                )
            _write_dataclass(device_group, device, excluded={"result"})

    @staticmethod
    def _write_analyzers(group: h5py.Group, experiment: object) -> None:
        for analyzer in getattr(experiment, "_analyzer_pipeline", ()):
            if not analyzer._dependencies_satisfied:
                continue
            _write_dataclass(group.require_group(analyzer.__class__.__name__), analyzer)

    @staticmethod
    def _write_debug(
        group: h5py.Group,
        experiment: object,
        *,
        run_error: BaseException | None,
    ) -> None:
        analyzers = [
            analyzer.__class__.__name__
            for analyzer in getattr(experiment, "_analyzer_pipeline", ())
        ]
        _write_value(group, "analyzer_pipeline", analyzers)
        if run_error is not None:
            _write_value(group, "run_error", repr(run_error))
        cleanup_errors = getattr(experiment, "_cleanup_errors", ())
        if cleanup_errors:
            _write_value(
                group,
                "cleanup_errors",
                [repr(error) for error in cleanup_errors],
            )
        publisher_errors = getattr(experiment, "_panel_publisher_errors", ())
        if publisher_errors:
            _write_value(group, "panel_publisher_errors", publisher_errors)


def _write_dataclass(
    group: h5py.Group,
    value: object,
    *,
    excluded: set[str] | None = None,
) -> None:
    excluded = excluded or set()
    for item in fields(cast(Any, value)):
        if (
            item.name.startswith("_")
            or item.name in excluded
            or item.metadata.get("persist", True) is False
        ):
            continue
        _write_value(group, item.name, getattr(value, item.name))


def _write_value(group: h5py.Group, name: str, value: Any) -> None:
    if is_dataclass(value) and not isinstance(value, type):
        _write_dataclass(group.require_group(name), value)
        return
    if isinstance(value, Path):
        value = str(value)
    if value is None:
        value = "null"
    if isinstance(value, Decimal):
        value = str(value)
    if isinstance(value, str):
        data: Any = np.asarray(value, dtype=h5py.string_dtype(encoding="utf-8"))
    elif isinstance(value, (bool, int, float, np.number, np.ndarray)):
        data = value
    elif isinstance(value, Mapping):
        data = np.asarray(
            json.dumps(value, default=str, sort_keys=True),
            dtype=h5py.string_dtype(encoding="utf-8"),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        data = _sequence_data(value)
    else:
        raise TypeError(f"cannot persist {name!r} with type {type(value).__name__}")
    if name in group:
        del group[name]
    group.create_dataset(name, data=data)


def _sequence_data(value: Sequence[Any]) -> np.ndarray:
    if all(isinstance(item, (Decimal, str)) for item in value):
        return np.asarray(
            [str(item) for item in value],
            dtype=h5py.string_dtype(encoding="utf-8"),
        )
    try:
        result = np.asarray(value)
    except ValueError:
        result = np.asarray(value, dtype=object)
    if result.dtype.kind in {"U", "O"}:
        return np.asarray(
            [json.dumps(item, default=str) for item in value],
            dtype=h5py.string_dtype(encoding="utf-8"),
        )
    return result


__all__ = ["H5Writer"]
