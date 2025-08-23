import pytest
import time
from dataclasses import dataclass

from catseq.protocols import State, HardwareInterface, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism, IdentityMorphism
from .helpers import StateA, StateB, StateC

# --- Correctness Tests for New Model ---

def test_primitive_composition(m_a1, m_a2):
    seq = m_a1 @ m_a2
    assert isinstance(seq, LaneMorphism)
    assert seq.duration == pytest.approx(2.5)
    assert seq.cod[0][1] == StateC()

def test_tensor_synchronization(m_a1, m_b1):
    seq = m_a1 | m_b1
    assert isinstance(seq, LaneMorphism)
    assert seq.duration == pytest.approx(2.0)
    lane_a = seq.lanes[m_a1.channel]
    assert len(lane_a) == 2
    assert isinstance(lane_a[1], IdentityMorphism)

def test_smart_composition_auto_hold(m_a1, m_b1):
    # m_a1 is on ch_a (TTL_0), m_b1 is on ch_b (TTL_1)
    # StateA -> StateB
    seq1 = m_a1 | m_b1

    # m_a2_long is on ch_a, StateB -> StateC
    m_a2_long = PrimitiveMorphism("A2_long", dom=((m_a1.channel, StateB()),), cod=((m_a1.channel, StateC()),), duration=1.5)

    final_seq = seq1 @ m_a2_long

    assert final_seq.duration == pytest.approx(3.5)

    final_cod_map = {res.name: state for res, state in final_seq.cod}
    assert final_cod_map["TTL_0"] == StateC()
    assert final_cod_map["TTL_1"] == StateB()

def test_distributive_like_composition(m_a1, m_a2, m_b1, m_b2):
    seq1 = m_a1 | m_b1
    seq2 = m_a2 | m_b2
    final_seq = seq1 @ seq2
    assert final_seq.duration == pytest.approx(4.5)

def test_repr_generation(m_a1, m_a2, m_b1):
    # Test single primitive
    assert repr(m_a1) == "A1"

    # Test LaneMorphism from single primitive
    seq_single = LaneMorphism.from_primitive(m_a1)
    assert repr(seq_single) == "A1"

    # Test serial composition
    seq_a = m_a1 @ m_a2
    assert repr(seq_a) == "(A1 @ A2)"

    # Test parallel composition with padding
    seq_b = m_a1 | m_b1
    # Note: The order in the repr depends on channel name sorting
    assert repr(seq_b) == "((A1 @ Pad(TTL_0)) | B1)"

    # Test empty LaneMorphism
    assert repr(LaneMorphism(lanes={})) == "Identity"

# --- Validation and Error Handling Tests ---

def test_primitive_post_init_validation(ch_a, ch_b):
    """Tests the validation logic in PrimitiveMorphism.__post_init__."""
    # Should fail if dom/cod have more than one channel
    with pytest.raises(ValueError, match="operate on exactly one channel"):
        PrimitiveMorphism("MultiDom", dom=((ch_a, StateA()), (ch_b, StateA())), cod=((ch_a, StateB()),), duration=1)

    # Should fail if channel is inconsistent
    with pytest.raises(ValueError, match="channel must be consistent"):
        PrimitiveMorphism("Inconsistent", dom=((ch_a, StateA()),), cod=((ch_b, StateB()),), duration=1)

def test_parallel_composition_fails_on_channel_overlap(m_a1, m_a2):
    """Tests that parallel composition raises TypeError on channel overlap."""
    with pytest.raises(TypeError, match="Channels overlap"):
        m_a1 | m_a2

def test_serial_composition_fails_on_missing_channel(m_a1, m_b2):
    """Tests that serial composition raises TypeError if a channel is missing."""
    seq = LaneMorphism.from_primitive(m_a1)
    with pytest.raises(TypeError, match="Channel TTL_1 not present"):
        seq @ m_b2

def test_serial_composition_validates_state_seam(ch_a, ch_b):
    """
    Tests that serial composition validates the transition between states
    at the composition seam, but only if the states are not identical.
    """
    class MockHardwareWithRules(HardwareInterface):
        def __init__(self, name: str): self.name = name
        def validate_transition(self, from_state: State, to_state: State) -> None:
            # This rule rejects any transition from StateB to StateC
            if isinstance(from_state, StateB) and isinstance(to_state, StateC):
                raise TypeError("Invalid hardware transition B->C")

    # Replace the default hardware instance with our mock
    ch_a._hardware_instance = MockHardwareWithRules(ch_a.name)

    # m1 ends in StateB
    m1 = PrimitiveMorphism("M1", dom=((ch_a, StateA()),), cod=((ch_a, StateB()),), duration=1)

    # m2 starts in StateA. Seam is B->A. States are different, so validate_transition
    # should be called. Our mock doesn't forbid B->A, so this should pass.
    m2_ok = PrimitiveMorphism("M2_ok", dom=((ch_a, StateA()),), cod=((ch_a, StateA()),), duration=1)
    m1 @ m2_ok

    # m3 starts in StateC. Seam is B->C. States are different.
    # The mock hardware rule should be triggered and raise an error.
    m3_bad = PrimitiveMorphism("M3_bad", dom=((ch_a, StateC()),), cod=((ch_a, StateA()),), duration=1)
    with pytest.raises(TypeError, match="Invalid hardware transition B->C"):
        m1 @ m3_bad

    # Restore the original hardware instance to not affect other tests
    from catseq.hardware.ttl import TTLDevice
    ch_a._hardware_instance = TTLDevice(ch_a.name)

def test_dom_cod_sorting(m_a1, m_b1):
    """
    Tests that the `dom` and `cod` properties are correctly sorted by channel name.
    TTL_0 (ch_a) should come before TTL_1 (ch_b).
    """
    seq = m_b1 | m_a1 # Compose with b first

    # DOM should be sorted: (ch_a, StateA), (ch_b, StateA)
    assert seq.dom[0][0].name == "TTL_0"
    assert seq.dom[1][0].name == "TTL_1"

    # COD should be sorted: (ch_a, StateB), (ch_b, StateB)
    assert seq.cod[0][0].name == "TTL_0"
    assert seq.cod[1][0].name == "TTL_1"

# --- Performance Test (final) ---

def test_long_composition_performance_final(ch_a):
    num_compositions = 1000
    step = PrimitiveMorphism("Step", dom=((ch_a, StateA()),), cod=((ch_a, StateA()),), duration=1e-6)

    print(f"\n--- Starting FINAL performance test for {num_compositions} compositions ---")
    start_time = time.perf_counter()
    long_sequence = LaneMorphism.from_primitive(step)
    for _ in range(num_compositions - 1):
        long_sequence = long_sequence @ step
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"--- FINAL elapsed time: {elapsed_time:.6f} seconds ---")

    assert isinstance(long_sequence, LaneMorphism)
    assert len(long_sequence.lanes[ch_a]) == num_compositions
    # Adjust assertion to a reasonable threshold for the more complex model
    # This can be environment-dependent, so we give it a generous buffer.
    assert elapsed_time < 0.8

def test_composition_with_invalid_types(m_a1):
    """
    Tests that composing with a non-morphism type raises an AttributeError.
    """
    with pytest.raises(AttributeError):
        m_a1 | "not a morphism"

    with pytest.raises(AttributeError):
        m_a1 @ 123

    with pytest.raises(AttributeError):
        LaneMorphism.from_primitive(None)
