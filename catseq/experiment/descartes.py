"""Repeat and tensor-scan traversal for one experiment run."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from .params import ExpParam, ExpParams, ScanPoint, compile_scan_values


StreamingAnalyze = Callable[[str, int], Any]


class DescartesGenerator:
    """Recursively traverse repeat and scan nodes into immutable points."""

    def __init__(self, streaming_analyze: StreamingAnalyze | None = None) -> None:
        self.streaming_analyze = streaming_analyze or (lambda _name, _order: None)
        self.is_exp_running: Callable[[], bool] | None = None
        self._callers: list[
            tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]
        ] = []
        self._caller_count: dict[str, list[int]] = defaultdict(list)
        self._order: list[tuple[str, int]] = []
        self._has_final = False
        self._execution_index = 0
        self._params = ExpParams.empty()
        self._coordinates: dict[str, int] = {}
        self._current_scan_point: ScanPoint | None = None
        self._params_by_name: dict[str, ExpParam[Any]] = {}
        self._param_roles: dict[ExpParam[Any], str] = {}
        self._scanned_params: set[ExpParam[Any]] = set()
        self._scan_nodes: list[tuple[ExpParam[Any], tuple[Any, ...]]] = []
        self._stopped = False

    @property
    def current_scan_point(self) -> ScanPoint | None:
        return self._current_scan_point

    @property
    def scan_axes(self) -> tuple[tuple[ExpParam[Any], tuple[Any, ...]], ...]:
        return tuple(self._scan_nodes)

    @property
    def node_descriptions(self) -> tuple[Mapping[str, Any], ...]:
        descriptions: list[Mapping[str, Any]] = []
        for (node_type, order), (_, args, kwargs) in zip(
            self._order, self._callers, strict=True
        ):
            description: dict[str, Any] = {"type": node_type, "order": order}
            if node_type == "scan":
                description.update(param=args[0].name, values=tuple(args[1]))
            elif node_type == "repeat":
                description["count"] = args[0]
                if (idx_param := kwargs.get("idx_param")) is not None:
                    description["idx_param"] = idx_param.name
            descriptions.append(MappingProxyType(description))
        return tuple(descriptions)

    def add_descartes(
        self, node_type: str, *args: Any, **kwargs: Any
    ) -> "DescartesGenerator":
        if node_type not in {"repeat", "scan", "final_exp"}:
            raise ValueError(f"unsupported Descartes node type: {node_type!r}")
        if node_type == "final_exp":
            return self.final_exp(*args, **kwargs)

        order = len(self._caller_count[node_type])
        normalized_args = args
        normalized_kwargs = dict(kwargs)
        if node_type == "scan":
            if len(args) < 2 or not isinstance(args[0], ExpParam):
                raise TypeError("scan requires an ExpParam and scan values")
            param = args[0]
            if param in self._scanned_params:
                raise ValueError(f"ExpParam {param.name!r} is scanned more than once")
            self._register_param(param, "scan")
            self._scanned_params.add(param)
            values = compile_scan_values(args[1])
            normalized_args = (param, values, *args[2:])
            self._scan_nodes.append((param, values))
        else:
            if not args:
                raise TypeError("repeat requires a count")
            count = args[0]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("repeat count must be a non-negative integer")
            if (idx_param := normalized_kwargs.get("idx_param")) is not None:
                if not isinstance(idx_param, ExpParam):
                    raise TypeError("repeat idx_param must be an ExpParam declaration")
                self._register_param(idx_param, "repeat idx_param")

        self._caller_count[node_type].append(len(self._callers))
        self._order.append((node_type, order))
        self._callers.append(
            (getattr(self, f"_{node_type}"), normalized_args, normalized_kwargs)
        )
        return self

    def final_exp(
        self,
        save_point: Callable[[ScanPoint], None],
        execute: Callable[[ScanPoint], Any],
        analyze: Callable[["DescartesGenerator"], Any] | None = None,
    ) -> "DescartesGenerator":
        if self._has_final:
            raise ValueError("DescartesGenerator already has a final_exp node")
        self._has_final = True
        self._caller_count["final_exp"].append(len(self._callers))
        self._order.append(("final_exp", 0))
        self._callers.append((self._final_exp, (save_point, execute, analyze), {}))
        return self

    def call_next(self, current_index: int = -1) -> Any:
        next_index = current_index + 1
        if next_index >= len(self._callers):
            raise RuntimeError("Descartes traversal has no final_exp node")
        caller, args, kwargs = self._callers[next_index]
        return caller(next_index, *args, **kwargs)

    def get_scan_param(self, order: int) -> ExpParam[Any]:
        return self._scan_nodes[order][0]

    def get_scan_values(self, order: int) -> tuple[Any, ...]:
        return self._scan_nodes[order][1]

    def finish(self) -> None:
        """Complete the traversal lifecycle; immutable points need no restore."""

    def _repeat(
        self,
        current_index: int,
        repeats: int,
        analyze: Callable[["DescartesGenerator", list[Any]], Any] | None = None,
        idx_param: ExpParam[int] | None = None,
    ) -> Any:
        order = self._order[current_index][1]
        axis = f"repeat_{order}"
        previous_params = self._params
        results: list[Any] = []
        try:
            for index in range(repeats):
                if not self._should_continue():
                    self._stopped = True
                    return None
                self._coordinates[axis] = index
                if idx_param is not None:
                    self._params = previous_params.with_value(idx_param, index)
                results.append(self.call_next(current_index))
                if self._stopped:
                    return None
        finally:
            self._params = previous_params
            self._coordinates.pop(axis, None)

        self.streaming_analyze("repeat", order)
        return {
            "resls": results,
            "res_anlz": analyze(self, results) if analyze else None,
        }

    def _scan(
        self,
        current_index: int,
        param: ExpParam[Any],
        values: tuple[Any, ...],
        analyze: Callable[["DescartesGenerator", list[Any], tuple[Any, ...]], Any]
        | None = None,
    ) -> Any:
        order = self._order[current_index][1]
        axis = f"scan_{order}"
        previous_params = self._params
        results: list[Any] = []
        try:
            for index, value in enumerate(values):
                if not self._should_continue():
                    self._stopped = True
                    return None
                self._coordinates[axis] = index
                self._params = previous_params.with_value(param, value)
                results.append(self.call_next(current_index))
                if self._stopped:
                    return None
        finally:
            self._params = previous_params
            self._coordinates.pop(axis, None)

        self.streaming_analyze("scan", order)
        return {
            "resls": results,
            "res_anlz": analyze(self, results, values) if analyze else None,
        }

    def _final_exp(
        self,
        current_index: int,
        save_point: Callable[[ScanPoint], None],
        execute: Callable[[ScanPoint], Any],
        analyze: Callable[["DescartesGenerator"], Any] | None,
    ) -> Any:
        del current_index
        if not self._should_continue():
            self._stopped = True
            return None
        point = ScanPoint(
            params=self._params,
            coordinates=self._coordinates,
            execution_index=self._execution_index,
        )
        self._execution_index += 1
        self._current_scan_point = point
        save_point(point)
        execution_result = execute(point)
        analysis_result = analyze(self) if analyze else None
        self.streaming_analyze("final_exp", 0)
        return {"res": execution_result, "res_anlz": analysis_result}

    def _register_param(self, param: ExpParam[Any], role: str) -> None:
        existing = self._params_by_name.get(param.name)
        if existing is not None and existing is not param:
            raise ValueError(
                f"different ExpParam declarations share name {param.name!r}"
            )
        if (existing_role := self._param_roles.get(param)) is not None:
            raise ValueError(
                f"ExpParam {param.name!r} cannot be both {existing_role} and {role}"
            )
        self._params_by_name[param.name] = param
        self._param_roles[param] = role

    def _should_continue(self) -> bool:
        return self.is_exp_running is None or bool(self.is_exp_running())


__all__ = ["DescartesGenerator"]
