from typing import Set, Union, Tuple
import numpy as np
from catseq.model import State
from catseq.hardware.base import BaseHardware
from catseq.states.common import Uninitialized
from catseq.states.rwg import (
    RWGState, RWGReady, RWGStaged, RWGArmed, RWGActive, WaveformParams, StaticWaveform
)


class RWGDevice(BaseHardware):
    """
    Represents a Real-time Waveform Generator (RWG) device.

    This class models a physical RWG channel. It acts as a "rulebook" for the
    DSL layer, providing methods to validate:
    1.  Process Dynamics (`validate_dynamics`): Are the waveform parameters valid?
    2.  FSM Path (`is_valid_fsm_path`): Is a state transition allowed?
    3.  Continuity (`check_continuity`): Does the connection between two
        active segments meet the channel's policy?
    """
    
    def __init__(
        self,
        name: str,
        # --- Physical Capability Parameters ---
        available_sbgs: Set[int],
        max_ramping_order: int = 0,
        # --- Policy & Role Parameters ---
        allow_ramping: bool = True,
        allow_disable: bool = True,
        enforce_continuity: bool = False,
        max_freq_jump_mhz: float = 1e-9,
        max_amp_jump_fs: float = 1e-9,
    ):
        super().__init__(name)
        self.available_sbgs = available_sbgs
        self.max_ramping_order = max_ramping_order

        if max_ramping_order == 0 and allow_ramping:
            raise ValueError(f"Configuration error for '{name}': Policy allows ramping, but hardware does not support it.")
        
        self.allow_ramping = allow_ramping
        self.allow_disable = allow_disable
        self.enforce_continuity = enforce_continuity
        self.max_freq_jump_mhz = max_freq_jump_mhz
        self.max_amp_jump_fs = max_amp_jump_fs

    def validate_dynamics(self, dynamics: Tuple[WaveformParams, ...]) -> None:
        """
        Validates the process parameters against the hardware's capabilities and policies.
        This is called by the DSL *before* creating a Morphism.
        """
        if not dynamics:
            return
        
        sbg_ids = set()
        for wf in dynamics:
            if wf.sbg_id in sbg_ids:
                raise TypeError(f"Duplicate SBG ID {wf.sbg_id} used for '{self.name}'.")
            sbg_ids.add(wf.sbg_id)
            if wf.sbg_id not in self.available_sbgs:
                raise TypeError(f"SBG ID {wf.sbg_id} is not available on device '{self.name}'.")
        
        required_order = max(wf.required_ramping_order for wf in dynamics)
        if required_order > 0 and not self.allow_ramping:
            raise TypeError(f"Policy violation for '{self.name}': Ramping is not allowed.")
        
        if required_order > self.max_ramping_order:
            raise TypeError(f"Hardware capability exceeded for '{self.name}': Required order is {required_order}, "
                            f"but hardware only supports up to {self.max_ramping_order}.")

    def validate_transition(self, from_state: State, to_state: State) -> None:
        """
        Validates the "seam" between two composed Morphisms.

        This method is called by the `@` composition operator. Its primary
        role is to ensure state continuity at the composition point, according
        to the channel's policies. It does NOT validate the FSM flow itself,
        as that responsibility lies with the DSL layer.
        """
        if isinstance(from_state, RWGActive) and isinstance(to_state, RWGActive):
            if self.enforce_continuity:
                from_map = {wf.sbg_id: wf for wf in from_state.waveforms}
                to_map = {wf.sbg_id: wf for wf in to_state.waveforms}

                if from_map.keys() != to_map.keys():
                    raise TypeError(f"Continuity violation on '{self.name}': Active SBGs changed.")
                
                for sbg_id, from_wf in from_map.items():
                    to_wf = to_map[sbg_id]
                    if abs(from_wf.freq - to_wf.freq) > self.max_freq_jump_mhz:
                        raise TypeError(f"Frequency jump on SBG {sbg_id} of '{self.name}' exceeds policy.")
                    if abs(from_wf.amp - to_wf.amp) > self.max_amp_jump_fs:
                        raise TypeError(f"Amplitude jump on SBG {sbg_id} of '{self.name}' exceeds policy.")
                    
            return
        
        if from_state != to_state:
            raise TypeError(
                f"State mismatch during composition on '{self.name}'. "
                f"Previous state ended in {from_state} but next state begins with {to_state}. "
                "The endpoints of composed morphisms must be identical."
            )