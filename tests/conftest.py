import pytest
from dataclasses import dataclass

from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism
from catseq.hardware.ttl import TTLDevice

# --- Test Fixtures and Dummy Classes ---

@dataclass(frozen=True)
class StateA(State): pass
@dataclass(frozen=True)
class StateB(State): pass
@dataclass(frozen=True)
class StateC(State): pass

# Concrete Channel instances for use in all tests
TTL_0 = Channel("TTL_0", TTLDevice)
TTL_1 = Channel("TTL_1", TTLDevice)

# Fixtures now provide concrete channel instances
@pytest.fixture
def ch_a() -> Channel: return TTL_0
@pytest.fixture
def ch_b() -> Channel: return TTL_1

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

@pytest.fixture
def ttl_channel() -> Channel:
    return TTL_0
