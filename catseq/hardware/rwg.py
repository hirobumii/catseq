from typing import Set, Tuple, Optional
from catseq.core.protocols import State, PhysicsViolationError
from catseq.hardware.base import BaseHardware
from catseq.states import RWGState, RWGUninitialized, RWGReady, RWGActive, Uninitialized


class RWGDevice(BaseHardware):
    """
    Real-time Waveform Generator (RWG) device with Taylor coefficient validation
    
    Provides hardware constraint validation for RWG channels including:
    - State transition validation
    - Taylor coefficient feasibility checking  
    - SBG resource management
    - Optional amplitude lock constraints
    """

    def __init__(
        self,
        name: str,
        available_sbgs: Set[int],
        max_ramping_order: int = 3,
        max_freq_mhz: float = 1000.0,
        max_amp_fs: float = 1.0,
        amplitude_locked: bool = False,
    ):
        super().__init__(name)
        self.available_sbgs = available_sbgs
        self.max_ramping_order = max_ramping_order
        self.max_freq_mhz = max_freq_mhz
        self.max_amp_fs = max_amp_fs
        self.amplitude_locked = amplitude_locked

    def validate_transition(self, from_state: State, to_state: State) -> None:
        """Validate RWG state transitions"""
        
        # Allow any transition from uninitialized state
        if isinstance(from_state, Uninitialized):
            if isinstance(to_state, RWGState):
                return
            else:
                raise PhysicsViolationError(
                    f"RWG device '{self.name}' cannot transition from Uninitialized to {type(to_state).__name__}"
                )
        
        # Both states must be RWG states for other transitions
        if not isinstance(from_state, RWGState) or not isinstance(to_state, RWGState):
            raise PhysicsViolationError(
                f"RWG device '{self.name}' requires RWG states, got {type(from_state).__name__} -> {type(to_state).__name__}"
            )
        
        # Validate specific RWG transitions
        if isinstance(from_state, RWGUninitialized):
            # Can transition to any RWG state from uninitialized
            return
        elif isinstance(from_state, RWGReady):
            # From Ready, can go to Active or back to Uninitialized
            if not isinstance(to_state, (RWGActive, RWGUninitialized)):
                raise PhysicsViolationError(
                    f"RWG device '{self.name}' cannot transition from RWGReady to {type(to_state).__name__}"
                )
        elif isinstance(from_state, RWGActive):
            # From Active, can go to Ready, Active (parameter change), or Uninitialized
            if not isinstance(to_state, (RWGReady, RWGActive, RWGUninitialized)):
                raise PhysicsViolationError(
                    f"RWG device '{self.name}' cannot transition from RWGActive to {type(to_state).__name__}"
                )
            
            # Validate SBG consistency for Active->Active transitions
            if isinstance(to_state, RWGActive):
                if from_state.sbg_id != to_state.sbg_id:
                    raise PhysicsViolationError(
                        f"RWG device '{self.name}' cannot change SBG ID during Active->Active transition"
                    )
                if from_state.sbg_id not in self.available_sbgs:
                    raise PhysicsViolationError(
                        f"RWG device '{self.name}' does not have access to SBG {from_state.sbg_id}"
                    )

    def validate_taylor_coefficients(
        self, 
        freq_coeffs: Tuple[Optional[float], ...], 
        amp_coeffs: Tuple[Optional[float], ...]
    ) -> None:
        """Validate Taylor coefficients for RWG hardware constraints"""
        
        if len(freq_coeffs) > 4 or len(amp_coeffs) > 4:
            raise PhysicsViolationError(
                f"RWG device '{self.name}' supports maximum 4 Taylor coefficients, got freq:{len(freq_coeffs)} amp:{len(amp_coeffs)}"
            )
        
        # Find highest non-zero coefficient order
        max_freq_order = -1
        for i, coeff in enumerate(freq_coeffs):
            if coeff is not None and abs(coeff) > 1e-12:
                max_freq_order = i
                
        max_amp_order = -1  
        for i, coeff in enumerate(amp_coeffs):
            if coeff is not None and abs(coeff) > 1e-12:
                max_amp_order = i
                
        required_order = max(max_freq_order, max_amp_order)
        
        if required_order > self.max_ramping_order:
            raise PhysicsViolationError(
                f"RWG device '{self.name}' supports maximum ramping order {self.max_ramping_order}, "
                f"but coefficients require order {required_order}"
            )
        
        # Validate coefficient magnitudes
        for i, coeff in enumerate(freq_coeffs):
            if coeff is not None and abs(coeff) > self.max_freq_mhz * (10 ** i):
                raise PhysicsViolationError(
                    f"RWG device '{self.name}' frequency coefficient F{i} = {coeff} exceeds hardware limits"
                )
                
        for i, coeff in enumerate(amp_coeffs):
            if coeff is not None and abs(coeff) > self.max_amp_fs * (10 ** i):
                raise PhysicsViolationError(
                    f"RWG device '{self.name}' amplitude coefficient A{i} = {coeff} exceeds hardware limits"
                )
        
        # Check amplitude lock constraint if enabled
        if self.amplitude_locked:
            for i, coeff in enumerate(amp_coeffs[1:], 1):  # A1, A2, A3
                if coeff is not None and abs(coeff) > 1e-12:
                    raise PhysicsViolationError(
                        f"Amplitude-locked RWG device '{self.name}' prohibits amplitude modulation, "
                        f"but A{i} = {coeff} is non-zero"
                    )