import pytest
import time
from dataclasses import dataclass

from catseq.model import (
    State, PrimitiveMorphism, LaneMorphism, IdentityMorphism,
    ResourceIdentifier, HardwareInterface
)
from catseq.hardware.ttl import TTLDevice
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff

# --- Test Fixtures and Dummy Classes ---

class DummyHardware(HardwareInterface, ResourceIdentifier):
    def __init__(self, name: str):
        self._name = name
    @property
    def name(self) -> str: return self._name
    @property
    def instance(self) -> "DummyHardware": return self
    def validate_transition(self, from_state: State, to_state: State) -> None: pass

@dataclass(frozen=True)
class StateA(State): pass
@dataclass(frozen=True)
class StateB(State): pass
@dataclass(frozen=True)
class StateC(State): pass

@pytest.fixture
def ch_a() -> DummyHardware: return DummyHardware("CH_A")
@pytest.fixture
def ch_b() -> DummyHardware: return DummyHardware("CH_B")

# --- Corrected Fixtures ---

@pytest.fixture
def m_a1(ch_a) -> PrimitiveMorphism:
    return PrimitiveMorphism(name="A1", dom=((ch_a, StateA()),), cod=((ch_a, StateB()),), duration=1.0)
@pytest.fixture
def m_a2(ch_a) -> PrimitiveMorphism:
    return PrimitiveMorphism(name="A2", dom=((ch_a, StateB()),), cod=((ch_a, StateC()),), duration=1.5)
@pytest.fixture
def m_b1(ch_b) -> PrimitiveMorphism:
    return PrimitiveMorphism(name="B1", dom=((ch_b, StateA()),), cod=((ch_b, StateB()),), duration=2.0)
@pytest.fixture
def m_b2(ch_b) -> PrimitiveMorphism:
    return PrimitiveMorphism(name="B2", dom=((ch_b, StateB()),), cod=((ch_b, StateC()),), duration=2.5)

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
    assert lane_a[1].duration == pytest.approx(1.0)

def test_smart_composition_auto_hold(m_a1, m_b1):
    seq1 = m_a1 | m_b1
    m_a2_long = PrimitiveMorphism("A2_long", dom=((m_a1.channel, StateB()),), cod=((m_a1.channel, StateC()),), duration=1.5)
    final_seq = seq1 @ m_a2_long
    assert final_seq.duration == pytest.approx(3.5)
    final_cod_map = {res.name: state for res, state in final_seq.cod}
    assert final_cod_map["CH_A"] == StateC()
    assert final_cod_map["CH_B"] == StateB()

def test_distributive_like_composition(m_a1, m_a2, m_b1, m_b2):
    seq1 = m_a1 | m_b1
    seq2 = m_a2 | m_b2
    final_seq = seq1 @ seq2
    assert final_seq.duration == pytest.approx(4.5)
    lane_a_duration = sum(m.duration for m in final_seq.lanes[m_a1.channel])
    lane_b_duration = sum(m.duration for m in final_seq.lanes[m_b1.channel])
    assert lane_a_duration == pytest.approx(4.5)
    assert lane_b_duration == pytest.approx(4.5)

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
    assert long_sequence.duration == pytest.approx(num_compositions * step.duration)
    assert elapsed_time < 0.05
