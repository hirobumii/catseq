"""Unit tests for the hardware compiler-intrinsic source surfaces.

These modules are part of the restricted CatSeq source language: importing them
must succeed and expose typed declarations, but executing an intrinsic with
CPython must be rejected with ``CompilerOnlyError``.
"""

import pytest

from catseq.hardware import common, rsp, rwg, sync
from catseq.morphism import CompilerOnlyError


class TestCommonIntrinsics:
    def test_hold_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            common.hold(1.0)

    def test_exports_hold(self) -> None:
        assert common.__all__ == ["hold"]


class TestSyncIntrinsics:
    def test_global_sync_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            sync.global_sync()

    def test_exports_global_sync(self) -> None:
        assert sync.__all__ == ["global_sync"]


class TestRspIntrinsics:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: rsp.initialize(100e6),
            lambda: rsp.pid_config(),
            lambda: rsp.pid_start(),
            lambda: rsp.pid_hold(),
            lambda: rsp.pid_release(),
            lambda: rsp.rf_config(rsp.RSPWaveformParams(rf_out=0, amp=0.5)),
        ],
    )
    def test_intrinsics_are_compiler_only(self, call) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            call()

    def test_reexports_state_and_config_types(self) -> None:
        for name in (
            "RSPPIDActive",
            "RSPPIDConfig",
            "RSPPIDReady",
            "RSPReady",
            "RSPUninitialized",
            "RSPWaveformParams",
        ):
            assert name in rsp.__all__
            assert hasattr(rsp, name)


class TestRwgAtomicLeaves:
    @pytest.mark.parametrize(
        "func, symbol",
        [
            (rwg.initialize, "catseq.hardware.rwg.initialize"),
            (rwg.load, "catseq.hardware.rwg.load"),
            (rwg.play, "catseq.hardware.rwg.play"),
            (rwg.rf_on, "catseq.hardware.rwg.rf_on"),
            (rwg.rf_off, "catseq.hardware.rwg.rf_off"),
        ],
    )
    def test_atomic_leaves_record_their_symbol(self, func, symbol: str) -> None:
        assert func.__catseq_definition__.kind == "atomic_morphism"
        assert func.__catseq_definition__.symbol == symbol

    def test_calling_an_atomic_leaf_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            rwg.play()

    def test_load_body_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            rwg.load([])


class TestRwgTemplates:
    @pytest.mark.parametrize(
        "func",
        [rwg.set_state, rwg.linear_ramp, rwg.rf_pulse, rwg.hold],
    )
    def test_templates_record_the_template_kind(self, func) -> None:
        assert func.__catseq_definition__.kind == "morphism_template"

    def test_hold_body_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            rwg.hold(1.0)

    def test_rf_pulse_body_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            rwg.rf_pulse(1.0)
