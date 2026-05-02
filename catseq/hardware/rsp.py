"""RSP (signal processor) hardware abstraction layer.

This module mirrors the RWG interface style but focuses on RSP/DSP operations.
The public functions return MorphismDef objects, so they can be composed with
``>>`` and applied to an RSP Channel.
"""

from catseq.atomic import (
    rsp_board_init,
    rsp_pid_config as atomic_rsp_pid_config,
    rsp_pid_hold as atomic_rsp_pid_hold,
    rsp_pid_release as atomic_rsp_pid_release,
    rsp_pid_start as atomic_rsp_pid_start,
    rsp_set_carrier as atomic_rsp_set_carrier,
)
from catseq.morphism import Morphism, MorphismDef
from catseq.types import Channel, State
from catseq.types.rsp import RSPPIDActive, RSPPIDConfig, RSPPIDReady, RSPReady, RSPUninitialized


def initialize() -> MorphismDef:
    """Create an RSP board-initialization definition."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RSPUninitialized, RSPReady)):
            raise TypeError(
                "RSP initialize must start from RSPUninitialized or RSPReady, "
                f"not {type(start_state)}"
            )
        if isinstance(start_state, RSPReady):
            # Idempotent from CatSeq's state-model perspective: emitting init again is
            # allowed and leaves the board ready.
            return rsp_board_init(channel)
        return rsp_board_init(channel)

    return MorphismDef(generator)


def set_carrier(carrier_freq: float) -> MorphismDef:
    """Create an RSP RF-carrier setup definition for the target channel."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RSPReady):
            raise TypeError(
                f"RSP set_carrier must start from RSPReady, not {type(start_state)}"
            )
        return atomic_rsp_set_carrier(channel, carrier_freq)

    return MorphismDef(generator)


def pid_config(
    ai_channel: int,
    ao_channel: int,
    setpoint: float,
    kp: float,
    ki: float,
    kd: float = 0.0,
    output_min: float | None = 0.0,
    output_max: float | None = 0.01,
    sample_rate: float | None = None,
    dgt_source: int | None = None,
) -> MorphismDef:
    """Create a PID-loop configuration definition.

    Args:
        ai_channel: ADC input index used as the measured signal.
        ao_channel: RF/DAC output index controlled by the loop.
        setpoint: PID setpoint in the RSP signal units used by the OASM helper.
        kp, ki, kd: PID gains.
        output_min, output_max: Optional clamp limits forwarded to the hardware
            helper.  The current low-level helper expects concrete clamp values;
            use its defaults when ``None`` is supplied.
        sample_rate: Reserved for future RSP helpers.  It is accepted so the
            high-level API is stable but is not currently emitted to OASM.
        dgt_source: Optional DGT-valid source index.  Defaults to ``ao_channel``
            so each RF output has a matching enable source unless specified.
    """
    if sample_rate is not None and sample_rate <= 0:
        raise ValueError("sample_rate must be positive when provided")

    config = RSPPIDConfig(
        adc_in=ai_channel,
        rf_out=ao_channel,
        dgt_source=ao_channel if dgt_source is None else dgt_source,
        setpoint=setpoint,
        kp=kp,
        ki=ki,
        kd=kd,
        output_min=0.0 if output_min is None else output_min,
        output_max=0.01 if output_max is None else output_max,
    )

    def generator(channel: Channel, start_state: State) -> Morphism:
        return atomic_rsp_pid_config(channel, config, start_state)

    return MorphismDef(generator)


def pid_start() -> MorphismDef:
    """Create a definition that starts or resumes a configured PID loop."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RSPPIDReady, RSPPIDActive)):
            raise TypeError(
                f"RSP pid_start must start from RSPPIDReady/RSPPIDActive, not {type(start_state)}"
            )
        return atomic_rsp_pid_start(channel, start_state)

    return MorphismDef(generator)


def pid_hold() -> MorphismDef:
    """Create a definition that holds an active PID loop output."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RSPPIDActive):
            raise TypeError(f"RSP pid_hold must start from RSPPIDActive, not {type(start_state)}")
        return atomic_rsp_pid_hold(channel, start_state)

    return MorphismDef(generator)


def pid_release() -> MorphismDef:
    """Create a definition that releases a held PID loop and resumes updates."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RSPPIDActive):
            raise TypeError(
                f"RSP pid_release must start from RSPPIDActive, not {type(start_state)}"
            )
        return atomic_rsp_pid_release(channel, start_state)

    return MorphismDef(generator)
