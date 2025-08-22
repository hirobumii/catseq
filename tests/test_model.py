import pytest
import time
from dataclasses import dataclass

from catseq.protocols import State, HardwareInterface, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism, IdentityMorphism

# Import the dummy states from conftest
from conftest import StateA, StateB, StateC

# All fixtures are now in conftest.py

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
    seq_a = m_a1 @ m_a2
    assert repr(seq_a) == "(A1 @ A2)"
    seq_b = m_a1 | m_b1
    assert repr(seq_b) == "((A1 @ Pad(TTL_0)) | B1)"

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
    assert elapsed_time < 0.2
