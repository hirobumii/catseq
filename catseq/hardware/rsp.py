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
    rsp_rf_config as atomic_rsp_rf_config,
    rsp_set_carrier as atomic_rsp_set_carrier,
)
from catseq.morphism import Morphism, MorphismDef
from catseq.types import Channel, State
from catseq.types.rsp import RSPPIDActive, RSPPIDConfig, RSPPIDReady, RSPReady, RSPUninitialized, RSPWaveformParams


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
    config: RSPPIDConfig | None = None,
    *,
    ai_channel: int | None = None,
    ao_channel: int | None = None,
    setpoint: float | None = None,
    kp: float = -1.0,
    ki: float = -0.02,
    kd: float = 0.0,
    output_max: float | None = 0.01,
    dgt_source: int | None = None,
) -> MorphismDef:
    """Create a PID-loop configuration definition.

    Args:
    config: PID configuration object.  Alternatively, pass ``ai_channel``,
        ``ao_channel`` and ``setpoint`` to build a default :class:`RSPPIDConfig`.
    """
    if config is None:
        if ai_channel is None or ao_channel is None or setpoint is None:
            raise TypeError(
                "pid_config requires either config=RSPPIDConfig(...) or "
                "ai_channel=..., ao_channel=..., setpoint=..."
            )
        config = RSPPIDConfig(
            adc_in=ai_channel,
            rf_out=ao_channel,
            dgt_source=ao_channel if dgt_source is None else dgt_source,
            setpoint=setpoint,
            kp=kp,
            ki=ki,
            kd=kd,
            output_max=output_max,
        )

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RSPReady, RSPPIDReady, RSPPIDActive)):
            raise TypeError(
                f"RSP pid_config must start from RSPReady/RSPPIDReady/RSPPIDActive, not {type(start_state)}"
            )
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

def rf_config(config: RSPWaveformParams) -> MorphismDef:
    """Create a static RSP RF-output configuration definition."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RSPReady):
            raise TypeError(f"RSP rf_config must start from RSPReady, not {type(start_state)}")
        if channel.local_id != config.rf_out:
            raise TypeError(
                f"RF configuration mismatch: expected RF channel rf{channel.local_id}, "
                f"but got channel rf{config.rf_out}."
            )
        return atomic_rsp_rf_config(channel, config, start_state)

    return MorphismDef(generator)
