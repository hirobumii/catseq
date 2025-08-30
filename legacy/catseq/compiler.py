"""
Cat-SEQ to RTMQ Compiler

This module translates Cat-SEQ LaneMorphism objects into executable Python functions
that directly call OASM RTMQ2 DSL. This approach provides:

1. Python type checking and IDE support
2. Direct execution without string generation
3. Runtime validation of OASM calls
4. Better error handling and debugging
"""

from typing import Dict, List, Callable
from dataclasses import dataclass

# Import OASM RTMQ DSL modules
import oasm.dev.rwg as rwg_dsl
import oasm.dev.main as std_dsl

from catseq.model import LaneMorphism, IdentityMorphism
from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice
from catseq.hardware.rwg import RWGDevice
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.states.rwg import RWGActive, RWGReady, StaticWaveform


@dataclass
class CompiledMorphism:
    """
    A compiled morphism that can be executed on RTMQ hardware.
    Contains the executable function and metadata.
    """
    function: Callable[[], None]
    duration: float
    channels: List[Channel]
    morphism: LaneMorphism
    
    def execute(self) -> None:
        """Execute the compiled morphism."""
        return self.function()
    
    def __call__(self) -> None:
        """Make the compiled morphism callable."""
        return self.execute()


class RTMQCompiler:
    """Main compiler class that generates executable Python functions from LaneMorphism objects."""
    
    def __init__(self):
        self.device_translators = {
            TTLDevice: self._compile_ttl_lane,
            RWGDevice: self._compile_rwg_lane,
        }
    
    def compile(self, morphism: LaneMorphism) -> CompiledMorphism:
        """
        Compile a LaneMorphism to an executable Python function.
        
        Args:
            morphism: The LaneMorphism to compile
            
        Returns:
            CompiledMorphism object containing executable function
        """
        # Collect all operations for each lane
        lane_operations: Dict[Channel, List[Callable[[], None]]] = {}
        
        for channel, primitives in morphism.lanes.items():
            device_type = type(channel.instance)
            
            # Find appropriate translator by checking device inheritance
            translator = None
            for device_class, device_translator in self.device_translators.items():
                if isinstance(channel.instance, device_class):
                    translator = device_translator
                    break
            
            if translator:
                operations = translator(channel, primitives)
                lane_operations[channel] = operations
            else:
                raise NotImplementedError(f"No translator for device type {device_type}")
        
        # Create the executable function
        def compiled_morphism_function():
            """Generated function that executes the morphism using OASM DSL."""
            # Execute all lane operations
            for channel, operations in lane_operations.items():
                for operation in operations:
                    operation()
        
        return CompiledMorphism(
            function=compiled_morphism_function,
            duration=morphism.duration,
            channels=list(morphism.lanes.keys()),
            morphism=morphism
        )
    
    def _compile_ttl_lane(self, channel: Channel, primitives) -> List[Callable[[], None]]:
        """Compile a TTL lane into a list of executable operations."""
        operations: List[Callable[[], None]] = []
        
        for primitive in primitives:
            if isinstance(primitive, IdentityMorphism):
                # Identity morphism = delay
                duration_us = primitive.duration * 1e6
                operations.append(self._create_delay_operation(duration_us))
                
            else:
                # TTL state transition
                from_state = primitive.dom[0][1] 
                to_state = primitive.cod[0][1]
                
                if isinstance(from_state, TTLState) and isinstance(to_state, TTLState):
                    if not isinstance(to_state, type(from_state)):
                        ch_index = self._extract_channel_index(channel.name)
                        
                        if isinstance(to_state, TTLOutputOn):
                            operations.append(lambda idx=ch_index: rwg_dsl.ttl.on(idx))
                        elif isinstance(to_state, TTLOutputOff):
                            operations.append(lambda idx=ch_index: rwg_dsl.ttl.off(idx))
                
                # Add timing
                if primitive.duration > 0:
                    duration_us = primitive.duration * 1e6
                    operations.append(self._create_delay_operation(duration_us))
                    operations.append(lambda: std_dsl.nop(hp=1))  # Synchronization
        
        return operations
    
    def _compile_rwg_lane(self, channel: Channel, primitives) -> List[Callable[[], None]]:
        """Compile an RWG lane into a list of executable operations."""
        operations: List[Callable[[], None]] = []
        
        for primitive in primitives:
            if isinstance(primitive, IdentityMorphism):
                # Identity morphism = delay
                duration_us = primitive.duration * 1e6
                operations.append(self._create_delay_operation(duration_us))
                
            else:
                # RWG state transition - check both from and to states
                from_state = primitive.dom[0][1]
                to_state = primitive.cod[0][1]
                
                # Check for initialization: Uninitialized -> RWGReady
                if isinstance(from_state, Uninitialized) and isinstance(to_state, RWGReady):
                    # This is an RWG initialization morphism
                    carrier_freq = getattr(to_state, 'carrier_freq', 100.0)
                    
                    operations.extend([
                        lambda: rwg_dsl.rsm.on(spi=1),
                        lambda: rwg_dsl.pdm.source(1, 1, 1, 1),
                        lambda: self._configure_cds(),
                        lambda: rwg_dsl.rwg.rst_cic(0xF),
                        lambda freq=carrier_freq: rwg_dsl.rwg.carrier(0xF, freq, upd=True),
                        lambda: rwg_dsl.rwg.timer(5000, wait=False)
                    ])
                    
                    # Add timing if needed
                    if primitive.duration > 0:
                        duration_us = primitive.duration * 1e6
                        operations.append(self._create_delay_operation(duration_us))
                
                elif isinstance(to_state, RWGActive):
                    # Generate RWG waveform playback operations
                    carrier_freq = getattr(to_state, 'carrier_freq', 100.0)
                    duration_seconds = primitive.duration
                    
                    # Configure SBG waveforms
                    if hasattr(to_state, 'waveforms') and to_state.waveforms:
                        for waveform in to_state.waveforms:
                            if isinstance(waveform, StaticWaveform):
                                operations.extend(
                                    self._create_sbg_configuration(waveform)
                                )
                    
                    # Play operation
                    operations.append(
                        lambda dur=duration_seconds: rwg_dsl.rwg.play(dur, 0xF, 0xF, 0x0)
                    )
                    
                    # Cleanup
                    operations.append(lambda: rwg_dsl.pdm.source(0, 0, 0, 0))
                
                elif isinstance(to_state, RWGReady):
                    # Turn off RWG or transition to ready state
                    operations.append(lambda: rwg_dsl.pdm.source(0, 0, 0, 0))
                    
                    if primitive.duration > 0:
                        duration_us = primitive.duration * 1e6
                        operations.append(self._create_delay_operation(duration_us))
        
        return operations
    
    def _create_delay_operation(self, duration_us: float) -> Callable[[], None]:
        """Create a delay operation function."""
        def delay_func():
            # Based on test3.ipynb pattern: rwg.timer(round(t*rwg.us)&-2, wait=False)
            timer_val = round(duration_us * rwg_dsl.us) & -2
            rwg_dsl.rwg.timer(timer_val, wait=False)
        
        return delay_func
    
    def _configure_cds(self) -> None:
        """Configure CDS based on tones() pattern from test3.ipynb."""
        rwg_dsl.cds.mux((0, 0, 0, 0),
                        (0x00000000_00000000_00000000_FFFFFFFF,
                         0x00000000_00000000_FFFFFFFF_00000000,
                         0x00000000_FFFFFFFF_00000000_00000000,
                         0xFFFFFFFF_00000000_00000000_00000000))
    
    def _create_sbg_configuration(self, waveform: StaticWaveform) -> List[Callable[[], None]]:
        """Create SBG configuration operations for a waveform."""
        sbg_id = waveform.sbg_id
        freq = waveform.freq
        amp = waveform.amp
        phase = waveform.phase
        
        return [
            lambda: rwg_dsl.fte.cfg(sbg_id, 0, 0, 1),
            lambda: rwg_dsl.rwg.frq(None, [freq, 0, 0, 0], phase),
            lambda: rwg_dsl.rwg.amp(None, [amp, 0, 0, 0])
        ]
    
    def _extract_channel_index(self, channel_name: str) -> int:
        """Extract channel index from channel name (e.g., 'TTL_0' -> 0)."""
        try:
            return int(channel_name.split('_')[-1])
        except (ValueError, IndexError):
            return 0


def compile_morphism(morphism: LaneMorphism) -> CompiledMorphism:
    """
    Convenience function to compile a morphism to an executable CompiledMorphism.
    
    Args:
        morphism: The LaneMorphism to compile
        
    Returns:
        CompiledMorphism object that can be executed
    """
    compiler = RTMQCompiler()
    return compiler.compile(morphism)


def create_executable_morphism(morphism: LaneMorphism, name: str = "catseq_morphism") -> Callable[[], None]:
    """
    Create an executable function from a morphism, similar to test3.ipynb patterns.
    
    Args:
        morphism: The LaneMorphism to compile
        name: Name for the generated function
        
    Returns:
        Executable function that can be used with rwg_play()
    """
    compiled = compile_morphism(morphism)
    
    # Create a named function for better debugging
    def named_morphism_function():
        """Generated morphism function for RTMQ execution."""
        return compiled.execute()
    
    # Set the function name for debugging
    named_morphism_function.__name__ = name
    named_morphism_function.__doc__ = f"Generated from Cat-SEQ morphism - Duration: {morphism.duration*1e6:.3f} μs"
    
    return named_morphism_function