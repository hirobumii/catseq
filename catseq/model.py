from typing import TypeVar, Generic, Tuple, Self, Protocol, Optional
from dataclasses import dataclass, field

@dataclass(frozen=True)
class State:
    pass

class Dynamics(Protocol):
    """
    A marker protocol for any object intended as a Morphism's dynamics.
    
    All process description classes, like WaveformParams or StaticWaveform,
    should conform to this protocol.
    """
    pass

class HardwareInterface(Protocol):
    def validate_transition(self, from_state: State, to_state: State) -> None:
        ...

class ResourceIdentifier(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def instance(self) -> HardwareInterface:
        ...

ChannelT = TypeVar('ChannelT', bound=ResourceIdentifier)

def get_name_for_resource_identifier(item: Tuple[ChannelT, State]) -> str:
    return item[0].name

@dataclass(frozen=True)
class Morphism(Generic[ChannelT]):
    name: str
    dom: Tuple[Tuple[ChannelT, State], ...]
    cod: Tuple[Tuple[ChannelT, State], ...]
    duration: float
    dynamics: Optional[Tuple[Dynamics, ...]]
    """
    A tuple of "process description" objects. Each object in the tuple
    must conform to the Dynamics protocol.
    """

    def __repr__(self) -> str:
        return self.name
    
    def __or__(self, other: Self) -> "TensorMorphism[ChannelT]":
        f_resources = {res for res, state in self.dom}
        g_resources = {res for res, state in other.dom}

        if not f_resources.isdisjoint(g_resources):
            raise TypeError(
                f"Parallel Composition Error: Morphisms '{self.name}' and '{other.name}' "
                f"cannot operate in parallel as they share common resources: {f_resources.intersection(g_resources)}"
            )
        
        name = f"({self.name} | {other.name})"
        dom = tuple(sorted(self.dom + other.dom, key=get_name_for_resource_identifier))
        cod = tuple(sorted(self.cod + other.cod, key=get_name_for_resource_identifier))
        duration = max(self.duration, other.duration)
        return TensorMorphism(name=name, dom=dom, cod=cod, duration=duration, dynamics=None, f=self, g=other)
    
    def __matmul__(self, other: Self) -> "CompositionMorphism[ChannelT]":
        available_resources = {res: state for res, state in self.cod}

        for item in other.dom:
            required_res_enum: ChannelT = item[0]
            required_state: State = item[1]
            if required_res_enum not in available_resources:
                raise TypeError(f"Resource Mismatch: Operation '{other.name}' requires '{required_res_enum.name}' which is not available")
            
            available_state = available_resources[required_res_enum]

            hw_instance = required_res_enum.instance
            hw_instance.validate_transition(from_state=available_state, to_state=required_state)

        required_resources_map = {res: state for res, state in other.dom}
        passthrough_resources = {res: state for res, state in self.cod if res not in required_resources_map}
        final_resources = passthrough_resources
        for res, state in other.cod:
            final_resources[res] = state
        new_cod = tuple(sorted(final_resources.items(), key=get_name_for_resource_identifier))
        name = f"({self.name} @ {other.name})"
        duration = self.duration + other.duration
        return CompositionMorphism(name=name, dom=self.dom, cod=new_cod, duration=duration, dynamics=None, f=self, g=other)


@dataclass(frozen=True)
class TensorMorphism(Morphism[ChannelT]):
    f: Morphism[ChannelT] = field(compare=False)
    g: Morphism[ChannelT] = field(compare=False)

@dataclass(frozen=True)
class CompositionMorphism(Morphism[ChannelT]):
    f: Morphism[ChannelT] = field(compare=False)
    g: Morphism[ChannelT] = field(compare=False)