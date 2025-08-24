import pytest
import time

from catseq.protocols import State, HardwareInterface, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism, IdentityMorphism
from catseq.builder import MorphismBuilder
from .helpers import StateA, StateB, StateC

# --- Builder Test Helpers ---

def simple_builder(name: str, from_state: State, to_state: State, duration: float) -> MorphismBuilder:
    """Creates a builder for a simple primitive morphism."""
    def generator(channel: Channel, gen_from_state: State) -> LaneMorphism:
        # The generator uses the state passed at call time, not definition time.
        m = PrimitiveMorphism(name, dom=((channel, gen_from_state),), cod=((channel, to_state),), duration=duration)
        return LaneMorphism.from_primitive(m)
    return MorphismBuilder(single_generator=generator)

# --- Correctness Tests for New Model ---

def test_builder_serial_composition(ch_a):
    """Tests serial composition of builders."""
    b1 = simple_builder("A1", from_state=StateA(), to_state=StateB(), duration=1.0)
    b2 = simple_builder("A2", from_state=StateB(), to_state=StateC(), duration=1.5)

    seq_builder = b1 @ b2
    seq = seq_builder(ch_a, from_state=StateA())

    assert isinstance(seq, LaneMorphism)
    assert seq.duration == pytest.approx(2.5)
    assert seq.cod[0][1] == StateC()

def test_tensor_synchronization(ch_a, ch_b):
    """Tests parallel composition of concrete morphisms, which triggers synchronization."""
    m_a1 = simple_builder("A1", StateA(), StateB(), 1.0)(ch_a, StateA())
    m_b1 = simple_builder("B1", StateA(), StateB(), 2.0)(ch_b, StateA())

    seq = m_a1 | m_b1
    assert isinstance(seq, LaneMorphism)
    assert seq.duration == pytest.approx(2.0)
    lane_a = seq.lanes[ch_a]
    assert len(lane_a) == 2
    assert isinstance(lane_a[1], IdentityMorphism)
    assert lane_a[1].duration == pytest.approx(1.0)

def test_smart_composition_auto_hold(ch_a, ch_b):
    """Tests serial composition after a parallel block, which triggers auto-hold."""
    m_a1 = simple_builder("A1", StateA(), StateB(), 1.0)(ch_a, StateA())
    m_b1 = simple_builder("B1", StateA(), StateB(), 2.0)(ch_b, StateA())
    seq1 = m_a1 | m_b1

    m_a2_long = simple_builder("A2_long", StateB(), StateC(), 1.5)(ch_a, StateB())
    final_seq = seq1 @ m_a2_long

    assert final_seq.duration == pytest.approx(3.5)
    final_cod_map = {res.name: state for res, state in final_seq.cod}
    assert final_cod_map["TTL_0"] == StateC()
    assert final_cod_map["TTL_1"] == StateB()

def test_distributive_like_composition(ch_a, ch_b):
    """Tests serial composition of two parallel morphisms."""
    m_a1 = simple_builder("A1", StateA(), StateB(), 1.0)(ch_a, StateA())
    m_a2 = simple_builder("A2", StateB(), StateC(), 1.5)(ch_a, StateB())
    m_b1 = simple_builder("B1", StateA(), StateB(), 2.0)(ch_b, StateA())
    m_b2 = simple_builder("B2", StateB(), StateC(), 2.5)(ch_b, StateB())

    seq1 = m_a1 | m_b1
    seq2 = m_a2 | m_b2
    final_seq = seq1 @ seq2
    assert final_seq.duration == pytest.approx(4.5)

def test_repr_generation(ch_a, ch_b):
    """Tests the __repr__ for various compositions."""
    b_a1 = simple_builder("A1", StateA(), StateB(), 1.0)
    b_a2 = simple_builder("A2", StateB(), StateC(), 1.5)
    m_a1 = b_a1(ch_a, StateA())
    m_b1 = simple_builder("B1", StateA(), StateB(), 2.0)(ch_b, StateA())

    assert repr(m_a1) == "A1"
    seq_a = (b_a1 @ b_a2)(ch_a, StateA())
    assert repr(seq_a) == "(A1 @ A2)"

    seq_b = m_a1 | m_b1
    assert repr(seq_b) == "((A1 @ Pad(TTL_0)) | B1)"
    assert repr(LaneMorphism(lanes={})) == "Identity"

# --- Validation and Error Handling Tests ---

def test_primitive_post_init_validation(ch_a, ch_b):
    """Tests the validation logic in PrimitiveMorphism.__post_init__."""
    with pytest.raises(ValueError, match="operate on exactly one channel"):
        PrimitiveMorphism("MultiDom", dom=((ch_a, StateA()), (ch_b, StateA())), cod=((ch_a, StateB()),), duration=1)

    with pytest.raises(ValueError, match="channel must be consistent"):
        PrimitiveMorphism("Inconsistent", dom=((ch_a, StateA()),), cod=((ch_b, StateB()),), duration=1)

def test_parallel_composition_fails_on_channel_overlap(ch_a):
    """Tests that parallel composition raises TypeError on channel overlap."""
    m1 = simple_builder("M1", StateA(), StateB(), 1)(ch_a, StateA())
    m2 = simple_builder("M2", StateB(), StateC(), 1)(ch_a, StateB())
    with pytest.raises(TypeError, match="Channels overlap"):
        m1 | m2

def test_serial_composition_fails_on_missing_channel(ch_a, ch_b):
    """Tests that serial composition raises TypeError if a channel is missing."""
    m1 = simple_builder("M1", StateA(), StateB(), 1)(ch_a, StateA())
    m2 = simple_builder("M2", StateB(), StateC(), 1)(ch_b, StateB())
    with pytest.raises(TypeError, match="Channel TTL_1 not present"):
        m1 @ m2

def test_serial_composition_validates_state_seam(ch_a):
    """Tests that serial composition validates the transition between states."""
    class MockHardwareWithRules(HardwareInterface):
        def __init__(self, name: str): self.name = name
        def validate_transition(self, from_state: State, to_state: State) -> None:
            if isinstance(from_state, StateB) and isinstance(to_state, StateC):
                raise TypeError("Invalid hardware transition B->C")

    ch_a._hardware_instance = MockHardwareWithRules(ch_a.name)

    # m1 ends in State B
    m1 = simple_builder("M1", StateA(), StateB(), 1)(ch_a, StateA())
    # m2 starts with State C
    m2 = simple_builder("M2", StateC(), StateA(), 1)(ch_a, StateC())

    # Composing m1 @ m2 should create a B->C transition on the seam for the
    # hardware to validate, which our mock forbids.
    with pytest.raises(TypeError, match="Invalid transition on channel TTL_0"):
        m1 @ m2

    # Restore original hardware to not affect other tests
    from catseq.hardware.ttl import TTLDevice
    ch_a._hardware_instance = TTLDevice(ch_a.name)

def test_dom_cod_sorting(ch_a, ch_b):
    """Tests that the `dom` and `cod` properties are correctly sorted by channel name."""
    m_a1 = simple_builder("A1", StateA(), StateB(), 1)(ch_a, StateA())
    m_b1 = simple_builder("B1", StateA(), StateB(), 2)(ch_b, StateA())
    seq = m_b1 | m_a1 # Compose with b first

    assert seq.dom[0][0].name == "TTL_0"
    assert seq.dom[1][0].name == "TTL_1"
    assert seq.cod[0][0].name == "TTL_0"
    assert seq.cod[1][0].name == "TTL_1"

def test_long_composition_performance_final(ch_a):
    """Tests performance of composing builders."""
    num_compositions = 1000
    step_builder = simple_builder("Step", StateA(), StateA(), 1e-6)

    print(f"\n--- Starting FINAL performance test for {num_compositions} compositions ---")
    start_time = time.perf_counter()

    long_sequence_builder = step_builder
    for _ in range(num_compositions - 1):
        long_sequence_builder = long_sequence_builder @ step_builder

    # Execution is now separate from definition
    final_sequence = long_sequence_builder(ch_a, StateA())
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"--- FINAL elapsed time: {elapsed_time:.6f} seconds ---")

    assert isinstance(final_sequence, LaneMorphism)
    assert len(final_sequence.lanes[ch_a]) == num_compositions
    assert elapsed_time < 0.8

def test_composition_with_invalid_types(ch_a):
    """Tests that composing with a non-morphism type raises an AttributeError."""
    m1 = simple_builder("M1", StateA(), StateB(), 1)(ch_a, StateA())
    with pytest.raises(AttributeError):
        m1 | "not a morphism"  # type: ignore

    with pytest.raises(AttributeError):
        m1 @ 123  # type: ignore

    with pytest.raises(AttributeError):
        LaneMorphism.from_primitive(None)  # type: ignore
