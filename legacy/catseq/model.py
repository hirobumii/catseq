from typing import Tuple, Self, Optional, Dict
from dataclasses import dataclass, field, replace
import functools
from catseq.protocols import Channel, State, Dynamics
from catseq.pending import fill_in_pending_state

# --- Helper Functions ---


def get_name_for_resource_identifier(item: Tuple[Channel, State]) -> str:
    """Helper function for sorting resource tuples by channel name."""
    return item[0].name


# --- Core Morphism Classes ---


@dataclass(frozen=True)
class PrimitiveMorphism:
    """
    Represents the absolute atomic unit of an operation on a single channel.
    """

    name: str
    dom: Tuple[Tuple[Channel, State], ...]
    cod: Tuple[Tuple[Channel, State], ...]
    duration: float
    dynamics: Optional[Dynamics] = None

    def __post_init__(self):
        if len(self.dom) != 1 or len(self.cod) != 1:
            raise ValueError("PrimitiveMorphism must operate on exactly one channel.")
        if self.dom[0][0] != self.cod[0][0]:
            raise ValueError(
                "PrimitiveMorphism channel must be consistent for dom and cod."
            )

    @property
    def channel(self) -> Channel:
        return self.dom[0][0]

    def __repr__(self) -> str:
        return self.name

    def __or__(self, other: Self | "LaneMorphism") -> "LaneMorphism":
        return LaneMorphism.from_primitive(self) | other

    def __matmul__(self, other: Self | "LaneMorphism") -> "LaneMorphism":
        return LaneMorphism.from_primitive(self) @ other


@dataclass(frozen=True)
class IdentityMorphism(PrimitiveMorphism):
    """A special primitive morphism that represents a hold on a channel."""

    pass


@dataclass(frozen=True)
class LaneMorphism:
    """
    The main user-facing class representing a set of synchronized parallel lanes.
    """

    lanes: Dict[Channel, Tuple[PrimitiveMorphism, ...]] = field(compare=False)

    @functools.cached_property
    def dom(self) -> Tuple[Tuple[Channel, State], ...]:
        return tuple(
            sorted(
                ((ch, lane[0].dom[0][1]) for ch, lane in self.lanes.items()),
                key=get_name_for_resource_identifier,
            )
        )

    @functools.cached_property
    def cod(self) -> Tuple[Tuple[Channel, State], ...]:
        return tuple(
            sorted(
                ((ch, lane[-1].cod[0][1]) for ch, lane in self.lanes.items()),
                key=get_name_for_resource_identifier,
            )
        )

    @functools.cached_property
    def duration(self) -> float:
        if not self.lanes:
            return 0.0
        first_lane = next(iter(self.lanes.values()))
        return sum(m.duration for m in first_lane)

    @classmethod
    def from_primitive(cls, prim: PrimitiveMorphism) -> Self:
        return cls(lanes={prim.channel: (prim,)})

    def __or__(self, other: Self | PrimitiveMorphism) -> Self:
        other_lanes = (
            other.lanes
            if isinstance(other, LaneMorphism)
            else {other.channel: (other,)}
        )

        self_ch = set(self.lanes.keys())
        other_ch = set(other_lanes.keys())
        if not self_ch.isdisjoint(other_ch):
            raise TypeError(
                f"Parallel Composition Error: Channels overlap {self_ch.intersection(other_ch)}"
            )

        new_lanes = self.lanes.copy()
        new_lanes.update(other_lanes)

        lane_durations = {
            ch: sum(m.duration for m in lane) for ch, lane in new_lanes.items()
        }
        max_duration = max(lane_durations.values()) if lane_durations else 0

        for ch, dur in lane_durations.items():
            if abs(dur - max_duration) > 1e-12:
                padding_needed = max_duration - dur
                last_state = new_lanes[ch][-1].cod[0][1]
                padding = IdentityMorphism(
                    f"Pad({ch.name})",
                    dom=((ch, last_state),),
                    cod=((ch, last_state),),
                    duration=padding_needed,
                )
                new_lanes[ch] = new_lanes[ch] + (padding,)

        return type(self)(lanes=new_lanes)

    def __matmul__(self, other: Self | PrimitiveMorphism) -> Self:
        # If other is a PrimitiveMorphism, wrap it in a LaneMorphism
        other_morphism = (
            other
            if isinstance(other, LaneMorphism)
            else LaneMorphism.from_primitive(other)
        )

        # Create a mutable copy of the other morphism's lanes for potential modification
        reconstructed_other_lanes = other_morphism.lanes.copy()

        self_cod_map = {ch: lane[-1].cod[0][1] for ch, lane in self.lanes.items()}

        # --- V4 INFERENCE AND VALIDATION ---
        for ch, other_lane in reconstructed_other_lanes.items():
            if ch not in self_cod_map:
                raise TypeError(
                    f"Composition Error: Channel {ch.name} not present in the preceding morphism."
                )

            from_state = self_cod_map[ch]
            to_state_template = other_lane[0].dom[0][1]

            # Attempt to fill in pending fields
            filled_to_state = fill_in_pending_state(to_state_template, from_state)

            # Strict validation: the preceding state must exactly match the (now filled) subsequent state
            if from_state != filled_to_state:
                # If they don't match, try a hardware-level validation for a more specific error
                try:
                    ch.instance.validate_transition(from_state, to_state_template)
                except Exception as e:
                    # Re-raise the specific hardware validation error
                    raise TypeError(
                        f"Invalid transition on channel {ch.name} from {from_state} to {to_state_template}"
                    ) from e

                # If hardware validation passes but they still don't match, it's a logical error
                raise TypeError(
                    f"Composition Error on channel {ch.name}: State mismatch. "
                    f"Cannot transition from {from_state} to {filled_to_state} (inferred from {to_state_template})."
                )

            # --- V4 RECONSTRUCTION ---
            # If inference resulted in a new state, reconstruct the primitive and the lane
            if filled_to_state is not to_state_template:
                original_prim = other_lane[0]
                # Create a new primitive with the inferred dom state
                new_prim = replace(original_prim, dom=((ch, filled_to_state),))
                # Reconstruct the lane with the new primitive at the start
                reconstructed_other_lanes[ch] = (new_prim,) + other_lane[1:]

        # --- V2 CORE COMPOSITION AND SYNCHRONIZATION ---
        new_lanes = self.lanes.copy()

        # Append the (potentially reconstructed) lanes from the other morphism
        for ch, lane_to_append in reconstructed_other_lanes.items():
            new_lanes[ch] = new_lanes.get(ch, ()) + lane_to_append

        # Calculate the new total durations for all lanes
        lane_durations = {
            ch: sum(m.duration for m in lane) for ch, lane in new_lanes.items()
        }
        max_duration = max(lane_durations.values()) if lane_durations else 0

        # Synchronize lanes by padding shorter ones with IdentityMorphisms
        for ch in list(new_lanes.keys()):
            dur = lane_durations.get(ch, 0)
            if abs(dur - max_duration) > 1e-12:
                padding_needed = max_duration - dur
                last_state = new_lanes[ch][-1].cod[0][1]
                padding = IdentityMorphism(
                    f"Pad({ch.name})",
                    dom=((ch, last_state),),
                    cod=((ch, last_state),),
                    duration=padding_needed,
                )
                new_lanes[ch] = new_lanes[ch] + (padding,)

        return type(self)(lanes=new_lanes)

    def __repr__(self) -> str:
        if not self.lanes:
            return "Identity"

        sorted_lanes = sorted(self.lanes.items(), key=lambda item: item[0].name)

        if len(sorted_lanes) == 1:
            ch, lane = sorted_lanes[0]
            lane_str = " @ ".join(m.name for m in lane)
            return f"({lane_str})" if len(lane) > 1 else lane_str

        else:
            lane_strs = []
            for ch, lane in sorted_lanes:
                lane_str = " @ ".join(m.name for m in lane)
                if len(lane) > 1:
                    lane_str = f"({lane_str})"
                lane_strs.append(lane_str)

            return f"({' | '.join(lane_strs)})"
