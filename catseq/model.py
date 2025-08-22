from __future__ import annotations
from typing import TypeVar, Generic, Tuple, Self, Protocol, Optional, Dict, List
from dataclasses import dataclass, field, replace
from collections import defaultdict
import functools

# --- Protocols and Base Classes ---

@dataclass(frozen=True)
class State:
    """Base class for all hardware state representations."""
    pass

class Dynamics(Protocol):
    """A marker protocol for any object intended as a Morphism's dynamics."""
    pass

class HardwareInterface(Protocol):
    """A protocol that concrete hardware classes must implement for validation."""
    def validate_transition(self, from_state: State, to_state: State) -> None: ...

class ResourceIdentifier(Protocol):
    """A protocol that hardware channel enumerations must implement."""
    @property
    def name(self) -> str: ...
    @property
    def instance(self) -> HardwareInterface: ...

ChannelT = TypeVar('ChannelT', bound=ResourceIdentifier)

def get_name_for_resource_identifier(item: Tuple[ChannelT, State]) -> str:
    """Helper function for sorting resource tuples by channel name."""
    return item[0].name

# --- Core Morphism Classes ---

@dataclass(frozen=True)
class PrimitiveMorphism(Generic[ChannelT]):
    """
    Represents the absolute atomic unit of an operation on a single channel.
    This is the fundamental building block for all complex sequences.
    """
    name: str
    dom: Tuple[Tuple[ChannelT, State], ...]
    cod: Tuple[Tuple[ChannelT, State], ...]
    duration: float
    dynamics: Optional[Dynamics] = None

    def __post_init__(self):
        """Validates that a primitive morphism acts on exactly one channel."""
        if len(self.dom) != 1 or len(self.cod) != 1:
            raise ValueError("PrimitiveMorphism must operate on exactly one channel.")
        if self.dom[0][0] != self.cod[0][0]:
            raise ValueError("PrimitiveMorphism channel must be consistent for dom and cod.")

    @property
    def channel(self) -> ChannelT:
        """The channel this primitive morphism operates on."""
        return self.dom[0][0]

    def __repr__(self) -> str:
        return self.name

    def __or__(self, other: Self | LaneMorphism) -> "LaneMorphism[ChannelT]":
        """Promotes this primitive to a LaneMorphism and performs a parallel composition."""
        return LaneMorphism.from_primitive(self) | other

    def __matmul__(self, other: Self | LaneMorphism) -> "LaneMorphism[ChannelT]":
        """Promotes this primitive to a LaneMorphism and performs a sequential composition."""
        return LaneMorphism.from_primitive(self) @ other

@dataclass(frozen=True)
class IdentityMorphism(PrimitiveMorphism[ChannelT]):
    """A special primitive morphism that represents a hold on a channel."""
    pass

@dataclass(frozen=True)
class LaneMorphism(Generic[ChannelT]):
    """
    The main user-facing class representing a set of synchronized parallel lanes.
    Each lane is a sequence of primitive morphisms on a single channel.
    ALL LANES in this object are guaranteed to have the same total duration.
    """
    lanes: Dict[ChannelT, Tuple[PrimitiveMorphism[ChannelT], ...]] = field(compare=False)
    name: str = "LaneMorphism"

    @functools.cached_property
    def dom(self) -> Tuple[Tuple[ChannelT, State], ...]:
        """The initial state of the system, composed of the first state of each lane."""
        return tuple(sorted(
            ((ch, lane[0].dom[0][1]) for ch, lane in self.lanes.items()),
            key=get_name_for_resource_identifier
        ))

    @functools.cached_property
    def cod(self) -> Tuple[Tuple[ChannelT, State], ...]:
        """The final state of the system, composed of the last state of each lane."""
        return tuple(sorted(
            ((ch, lane[-1].cod[0][1]) for ch, lane in self.lanes.items()),
            key=get_name_for_resource_identifier
        ))
    
    @functools.cached_property
    def duration(self) -> float:
        """The total duration of the morphism. All lanes are guaranteed to have the same duration."""
        if not self.lanes: return 0.0
        first_lane = next(iter(self.lanes.values()))
        return sum(m.duration for m in first_lane)

    @classmethod
    def from_primitive(cls, prim: PrimitiveMorphism) -> Self:
        """Convenience constructor to create a LaneMorphism from a single primitive."""
        return cls(lanes={prim.channel: (prim,)}, name=prim.name)

    def __or__(self, other: Self | PrimitiveMorphism) -> Self:
        """
        Performs a parallel composition (|).
        
        This operator merges the lanes of two morphisms. Crucially, it ensures
        all lanes in the resulting morphism are synchronized to the same total
        duration by padding shorter lanes with IdentityMorphisms.
        """
        other_lanes = other.lanes if isinstance(other, LaneMorphism) else {other.channel: (other,)}

        self_ch = set(self.lanes.keys())
        other_ch = set(other_lanes.keys())
        if not self_ch.isdisjoint(other_ch):
            raise TypeError(f"Parallel Composition Error: Channels overlap {self_ch.intersection(other_ch)}")

        new_lanes = self.lanes.copy()
        new_lanes.update(other_lanes)

        lane_durations = {ch: sum(m.duration for m in lane) for ch, lane in new_lanes.items()}
        max_duration = max(lane_durations.values()) if lane_durations else 0

        for ch, dur in lane_durations.items():
            if abs(dur - max_duration) > 1e-12: # Epsilon for float comparison
                padding_needed = max_duration - dur
                last_state = new_lanes[ch][-1].cod[0][1]
                padding = IdentityMorphism(f"Pad({ch.name})", dom=((ch, last_state),), cod=((ch, last_state),), duration=padding_needed)
                new_lanes[ch] = new_lanes[ch] + (padding,)

        return LaneMorphism(lanes=new_lanes, name=f"({self.name} | {other.name})")

    def __matmul__(self, other: Self | PrimitiveMorphism) -> Self:
        """
        Performs a sequential composition (@).

        This smart operator appends the lanes of the `other` morphism to the
        corresponding lanes of this one. It automatically handles passthrough
        channels by padding them with IdentityMorphisms to ensure all lanes
        remain synchronized.
        """
        other_lanes = other.lanes if isinstance(other, LaneMorphism) else {other.channel: (other,)}

        new_lanes = self.lanes.copy()

        self_cod_map = {ch: lane[-1].cod[0][1] for ch, lane in self.lanes.items()}
        for ch, other_lane in other_lanes.items():
            if ch not in self_cod_map:
                raise TypeError(f"Composition Error: Channel {ch.name} not present in the preceding morphism.")

            from_state = self_cod_map[ch]
            to_state = other_lane[0].dom[0][1]
            if from_state != to_state:
                ch.instance.validate_transition(from_state, to_state)

        for ch, other_lane in other_lanes.items():
            new_lanes[ch] = new_lanes[ch] + other_lane

        lane_durations = {ch: sum(m.duration for m in lane) for ch, lane in new_lanes.items()}
        max_duration = max(lane_durations.values()) if lane_durations else 0

        for ch in list(new_lanes.keys()):
            dur = lane_durations.get(ch, 0)
            if abs(dur - max_duration) > 1e-12:
                padding_needed = max_duration - dur
                last_state = new_lanes[ch][-1].cod[0][1]
                padding = IdentityMorphism(f"Pad({ch.name})", dom=((ch, last_state),), cod=((ch, last_state),), duration=padding_needed)
                new_lanes[ch] = new_lanes[ch] + (padding,)

        return LaneMorphism(lanes=new_lanes, name=f"({self.name} @ {other.name})")

    def __repr__(self) -> str:
        return self.name
