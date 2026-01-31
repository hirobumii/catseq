"""CatSeq V2 RWG Operations - Compositional Architecture

基于原子操作的组合设计：
- 原子操作：rwg_init, set_carrier, load_coeffs, update_params, rf_switch
- 高层操作通过 >> 组合原子操作实现

使用示例：
    >>> from catseq.v2.rwg import initialize, set_state, rf_pulse, StaticWaveform
    >>> from catseq.time_utils import us
    >>>
    >>> # 初始化 + RF 脉冲
    >>> seq = initialize(100.0) >> rf_on() >> wait(10*us) >> rf_off()
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import overload, Union, Tuple, Optional, List

from catseq.types.common import Channel
from catseq.time_utils import time_to_cycles
from catseq.v2.morphism import (
    HardwareState,
    OpenMorphism,
    BoundMorphism,
)
from catseq.v2.opcodes import OpCode


# =============================================================================
# RWG Hardware States
# =============================================================================

@dataclass(frozen=True)
class RWGUninitialized(HardwareState):
    """RWG 未初始化状态"""
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (RWGUninitialized, RWGReady))


@dataclass(frozen=True)
class RWGReady(HardwareState):
    """RWG 就绪状态（已设置载波频率，但未激活）"""
    carrier_freq: float  # MHz

    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (RWGReady, RWGActive))


@dataclass(frozen=True)
class StaticWaveform:
    """静态波形快照

    Attributes:
        sbg_id: SBG 通道 ID
        freq: 频率 (MHz)
        amp: 幅度 (FS, 0.0-1.0)
        phase: 相位 (Radian)
    """
    sbg_id: int
    freq: float = 0.0
    amp: float = 0.0
    phase: float = 0.0


@dataclass(frozen=True)
class WaveformParams:
    """动态波形参数（Taylor 系数）"""
    sbg_id: int
    freq_coeffs: Tuple[Optional[float], ...] = (0.0, None, None, None)
    amp_coeffs: Tuple[Optional[float], ...] = (0.0, None, None, None)
    initial_phase: Optional[float] = None
    phase_reset: bool = False


@dataclass(frozen=True)
class RWGActive(HardwareState):
    """RWG 活跃状态（正在输出波形）"""
    carrier_freq: float
    rf_on: bool = False
    snapshot: Tuple[StaticWaveform, ...] = field(default_factory=tuple)

    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (RWGReady, RWGActive))


# =============================================================================
# Payload Encoding (Internal)
# =============================================================================

def _encode_waveform_params(params: List[WaveformParams]) -> bytes:
    """编码波形参数列表"""
    data = struct.pack('<B', len(params))
    for p in params:
        freq = tuple(c if c is not None else 0.0 for c in p.freq_coeffs[:4])
        while len(freq) < 4:
            freq = freq + (0.0,)
        amp = tuple(c if c is not None else 0.0 for c in p.amp_coeffs[:4])
        while len(amp) < 4:
            amp = amp + (0.0,)
        data += struct.pack(
            '<B4d4ddB',
            p.sbg_id, *freq, *amp,
            p.initial_phase if p.initial_phase is not None else 0.0,
            1 if p.phase_reset else 0
        )
    return data


def _encode_static_waveforms(waveforms: List[StaticWaveform]) -> bytes:
    """编码静态波形列表"""
    data = struct.pack('<B', len(waveforms))
    for w in waveforms:
        data += struct.pack('<Bddd', w.sbg_id, w.freq, w.amp, w.phase)
    return data


# =============================================================================
# Atomic Operations (原子操作)
# =============================================================================

def rwg_init() -> OpenMorphism:
    """RWG 板级初始化 (原子操作)

    状态转换: RWGUninitialized -> RWGReady(0)
    """
    def gen():
        yield (0, OpCode.RWG_INIT, b"")
    return OpenMorphism(gen, name="rwg_init", transitions={RWGUninitialized: RWGReady},
                        infer_state=lambda _: RWGReady(carrier_freq=0.0))


def set_carrier(freq: float) -> OpenMorphism:
    """设置载波频率 (原子操作)

    状态转换: RWGReady -> RWGReady

    Args:
        freq: 载波频率 (MHz)
    """
    def gen():
        yield (0, OpCode.RWG_SET_CARRIER, struct.pack('<d', freq))
    return OpenMorphism(gen, name=f"set_carrier({freq}MHz)", transitions={RWGReady: RWGReady},
                        infer_state=lambda _, f=freq: RWGReady(carrier_freq=f))


def load_coeffs(params: List[WaveformParams]) -> OpenMorphism:
    """加载波形系数 (原子操作)

    状态转换: RWGReady|RWGActive -> RWGActive

    Args:
        params: 波形参数列表
    """
    def gen():
        yield (0, OpCode.RWG_LOAD_COEFFS, _encode_waveform_params(params))

    def _infer(s: HardwareState) -> HardwareState:
        freq = s.carrier_freq if hasattr(s, 'carrier_freq') else 0.0
        rf = s.rf_on if hasattr(s, 'rf_on') else False
        snap = s.snapshot if hasattr(s, 'snapshot') else ()
        return RWGActive(carrier_freq=freq, rf_on=rf, snapshot=snap)

    return OpenMorphism(
        gen, name="load_coeffs",
        transitions={RWGReady: RWGActive, RWGActive: RWGActive},
        infer_state=_infer,
    )


def update_params(waveforms: List[StaticWaveform] | None = None) -> OpenMorphism:
    """触发参数更新 (原子操作)

    状态转换: RWGActive -> RWGActive

    Args:
        waveforms: 可选的波形快照（用于状态追踪）
    """
    def gen():
        payload = _encode_static_waveforms(waveforms) if waveforms else b""
        yield (0, OpCode.RWG_UPDATE_PARAMS, payload)

    def _infer(s: HardwareState) -> HardwareState:
        snap = tuple(waveforms) if waveforms else s.snapshot if hasattr(s, 'snapshot') else ()
        return RWGActive(carrier_freq=s.carrier_freq, rf_on=s.rf_on, snapshot=snap)

    return OpenMorphism(gen, name="update_params", transitions={RWGActive: RWGActive},
                        infer_state=_infer)


def rf_switch(on: bool) -> OpenMorphism:
    """RF 开关控制 (原子操作)

    状态转换: RWGActive -> RWGActive

    Args:
        on: True=开, False=关
    """
    def gen():
        yield (0, OpCode.RWG_RF_SWITCH, b'\x01' if on else b'\x00')

    def _infer(s: HardwareState) -> HardwareState:
        freq = s.carrier_freq if hasattr(s, 'carrier_freq') else 0.0
        snap = s.snapshot if hasattr(s, 'snapshot') else ()
        return RWGActive(carrier_freq=freq, rf_on=on, snapshot=snap)

    return OpenMorphism(gen, name=f"rf_{'on' if on else 'off'}",
                        transitions={RWGReady: RWGActive, RWGActive: RWGActive},
                        infer_state=_infer)


def wait(duration: float) -> OpenMorphism:
    """等待 (原子操作)

    Args:
        duration: 等待时长 (秒，SI 单位)
    """
    def gen():
        cycles = time_to_cycles(duration)
        if cycles > 0:
            yield (cycles, OpCode.IDENTITY, b"")
    return OpenMorphism(gen, name=f"wait({duration*1e6:.1f}us)")


# =============================================================================
# Composite Operations (组合操作)
# =============================================================================

def initialize(carrier_freq: float) -> OpenMorphism:
    """初始化 RWG (组合操作)

    等价于: rwg_init() >> set_carrier(carrier_freq)

    状态转换: RWGUninitialized -> RWGReady
    """
    return rwg_init() >> set_carrier(carrier_freq)


def set_state(targets: List[StaticWaveform], phase_reset: bool = True) -> OpenMorphism:
    """设置波形状态 (组合操作)

    等价于: load_coeffs(params) >> update_params(targets)

    状态转换: RWGReady/RWGActive -> RWGActive
    """
    params = [
        WaveformParams(
            sbg_id=t.sbg_id,
            freq_coeffs=(t.freq, None, None, None),
            amp_coeffs=(t.amp, None, None, None),
            initial_phase=t.phase,
            phase_reset=phase_reset,
        )
        for t in targets
    ]
    return load_coeffs(params) >> update_params(targets)


def rf_on() -> OpenMorphism:
    """打开 RF (组合操作)"""
    return rf_switch(True)


def rf_off() -> OpenMorphism:
    """关闭 RF (组合操作)"""
    return rf_switch(False)


def rf_pulse(duration: float) -> OpenMorphism:
    """RF 脉冲 (组合操作)

    等价于: rf_on() >> wait(duration) >> rf_off()
    """
    return rf_on() >> wait(duration) >> rf_off()


def linear_ramp(
    target: List[StaticWaveform],
    duration: float,
) -> OpenMorphism:
    """线性渐变 (组合操作，使用 backpatching 推导起始状态)

    起始波形从前序操作的 exit_state 自动推导（通过 backpatching）。

    Args:
        target: 目标波形状态
        duration: 渐变时长 (秒，SI 单位)

    Note:
        典型用法：
        >>> seq = set_state(start) >> linear_ramp(target, 10*us)
    """
    duration_us = duration * 1e6

    # Static end: load_coeffs payload 已知
    static_params = [
        WaveformParams(
            sbg_id=t.sbg_id,
            freq_coeffs=(t.freq, 0.0, None, None),
            amp_coeffs=(t.amp, 0.0, None, None),
            initial_phase=0.0,
            phase_reset=False,
        )
        for t in target
    ]

    def _ramp_payload(state: HardwareState) -> bytes:
        """Backpatch generator: 从前序状态推导 ramp 系数"""
        start = state.snapshot if hasattr(state, 'snapshot') and state.snapshot else [
            StaticWaveform(sbg_id=t.sbg_id, freq=state.carrier_freq if hasattr(state, 'carrier_freq') else 0.0)
            for t in target
        ]
        ramp_params = []
        for start_wf, target_wf in zip(start, target):
            freq_rate = (target_wf.freq - start_wf.freq) / duration_us if duration_us > 0 else 0
            amp_rate = (target_wf.amp - start_wf.amp) / duration_us if duration_us > 0 else 0
            ramp_params.append(WaveformParams(
                sbg_id=start_wf.sbg_id,
                freq_coeffs=(start_wf.freq, freq_rate, None, None),
                amp_coeffs=(start_wf.amp, amp_rate, None, None),
                initial_phase=start_wf.phase if hasattr(start_wf, 'phase') else 0.0,
                phase_reset=False,
            ))
        return _encode_waveform_params(ramp_params)

    def gen():
        # Dynamic: ramp load_coeffs (payload depends on predecessor state)
        yield (0, OpCode.RWG_LOAD_COEFFS, _ramp_payload)
        yield (0, OpCode.RWG_UPDATE_PARAMS, b"")
        # Wait
        cycles = time_to_cycles(duration)
        if cycles > 0:
            yield (cycles, OpCode.IDENTITY, b"")
        # Static end: settle to target
        yield (0, OpCode.RWG_LOAD_COEFFS, _encode_waveform_params(static_params))
        yield (0, OpCode.RWG_UPDATE_PARAMS, _encode_static_waveforms(target))

    def _infer(s: HardwareState) -> HardwareState:
        freq = s.carrier_freq if hasattr(s, 'carrier_freq') else 0.0
        rf = s.rf_on if hasattr(s, 'rf_on') else False
        return RWGActive(carrier_freq=freq, rf_on=rf, snapshot=tuple(target))

    return OpenMorphism(
        gen, name="linear_ramp",
        transitions={RWGReady: RWGActive, RWGActive: RWGActive},
        infer_state=_infer,
    )
