from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from decimal import Decimal

import pytest

from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.para_dict import ParaDict
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint, compile_scan_values
from catseq.experiment.run_control import RunControl


def test_descartes_preserves_nested_callback_and_tensor_coordinate_order() -> None:
    duration = ExpParam[float]("duration_us", unit="us")
    history = ParaDict()
    streaming_events: list[tuple[str, int]] = []
    local_events: list[object] = []
    generator = DescartesGenerator(
        lambda name, order: streaming_events.append((name, order))
    )
    generator.add_descartes(
        "repeat",
        2,
        analyze=lambda _generator, children: local_events.append(
            ("repeat", len(children))
        ),
    )
    generator.add_descartes(
        "scan",
        duration,
        [1.0, 2.0],
        analyze=lambda _generator, children, values: local_events.append(
            ("scan", len(children), values)
        ),
    )

    def analyze_point(current: DescartesGenerator) -> None:
        point = current.current_scan_point
        assert point is not None
        local_events.append(
            ("point", dict(point.tensor_coordinates), point.params[duration])
        )

    generator.final_exp(history.append, lambda point: point.execution_index, analyze_point)
    generator.call_next()

    assert history.para_dict == {
        "duration_us": [1.0, 2.0, 1.0, 2.0],
        "__coord__repeat_0": [0, 0, 1, 1],
        "__coord__scan_0": [0, 1, 0, 1],
        "__idx__": [0, 1, 2, 3],
    }
    assert streaming_events == [
        ("final_exp", 0),
        ("final_exp", 0),
        ("scan", 0),
        ("final_exp", 0),
        ("final_exp", 0),
        ("scan", 0),
        ("repeat", 0),
    ]
    assert local_events == [
        ("point", {"repeat_0": 0, "scan_0": 0}, 1.0),
        ("point", {"repeat_0": 0, "scan_0": 1}, 2.0),
        ("scan", 2, (1.0, 2.0)),
        ("point", {"repeat_0": 1, "scan_0": 0}, 1.0),
        ("point", {"repeat_0": 1, "scan_0": 1}, 2.0),
        ("scan", 2, (1.0, 2.0)),
        ("repeat", 2),
    ]


def test_descartes_records_an_attempt_before_execution_failure() -> None:
    duration = ExpParam[float]("duration_us")
    history = ParaDict()
    generator = DescartesGenerator()
    generator.add_descartes("scan", duration, [1.0, 2.0])

    def fail(point: ScanPoint) -> None:
        raise RuntimeError(f"cannot compile {point.params[duration]}")

    generator.final_exp(history.append, fail)

    with pytest.raises(RuntimeError, match="cannot compile 1.0"):
        generator.call_next()

    assert history.values(duration) == (1.0,)
    assert history.execution_indexes == (0,)


def test_descartes_stops_at_the_next_safe_checkpoint() -> None:
    control = RunControl()
    attempted: list[int] = []
    generator = DescartesGenerator()
    generator.is_exp_running = control.checkpoint
    generator.add_descartes("repeat", 5)

    def execute(point: ScanPoint) -> None:
        attempted.append(point.execution_index)
        control.request_stop()

    generator.final_exp(lambda _point: None, execute)
    control.start()
    try:
        generator.call_next()
    finally:
        control.finish()

    assert attempted == [0]


def test_run_control_pauses_and_resumes_a_checkpoint() -> None:
    control = RunControl()
    control.start()
    control.request_pause()
    with ThreadPoolExecutor(max_workers=1) as executor:
        checkpoint = executor.submit(control.checkpoint)
        with pytest.raises(TimeoutError):
            checkpoint.result(timeout=0.02)
        control.resume()
        assert checkpoint.result(timeout=1) is True
    control.finish()


def test_run_control_keeps_a_stop_requested_before_start() -> None:
    control = RunControl()

    control.request_stop()
    control.start()

    assert control.checkpoint() is False
    control.finish()


def test_para_dict_is_append_only_and_keeps_declaration_identity() -> None:
    duration = ExpParam[float]("duration_us")
    history = ParaDict()
    history.append(
        ScanPoint(ExpParams({duration: 1.0}), {"scan_0": 0}, 0)
    )
    history.append(
        ScanPoint(ExpParams({duration: 2.0}), {"scan_0": 1}, 1)
    )

    assert history.current(duration) == 2.0
    assert history.coordinate_values("scan_0") == (0, 1)
    assert history.columns["duration_us"] == (1.0, 2.0)
    with pytest.raises(TypeError):
        history.para_dict["duration_us"].append(3.0)
    with pytest.raises(KeyError):
        history.values(ExpParam[float]("duration_us"))


def test_scan_range_uses_closed_decimal_arithmetic() -> None:
    assert compile_scan_values((0.0, 0.3, 0.1)) == (0.0, 0.1, 0.2, 0.3)
    assert compile_scan_values((1, 0, -1)) == (1, 0)
    assert compile_scan_values(
        (Decimal("0.0"), Decimal("0.2"), Decimal("0.1"))
    ) == (Decimal("0.0"), Decimal("0.1"), Decimal("0.2"))
    with pytest.raises(ValueError, match="negative step"):
        compile_scan_values((0, 1, -1))


def test_descartes_rejects_parameter_role_collisions() -> None:
    index = ExpParam[int]("index")
    generator = DescartesGenerator()
    generator.add_descartes("repeat", 2, idx_param=index)
    with pytest.raises(ValueError, match="repeat idx_param and scan"):
        generator.add_descartes("scan", index, [0, 1])
