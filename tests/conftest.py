import pytest
from dataclasses import dataclass

from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism
from catseq.hardware.ttl import TTLDevice
from .helpers import StateA, StateB, StateC

# --- Test Fixtures and Dummy Classes ---

# Concrete Channel instances for use in all tests
TTL_0 = Channel("TTL_0", TTLDevice)
TTL_1 = Channel("TTL_1", TTLDevice)

# Fixtures now provide concrete channel instances
@pytest.fixture
def ch_a() -> Channel: return TTL_0
@pytest.fixture
def ch_b() -> Channel: return TTL_1

@pytest.fixture
def ttl_channel() -> Channel:
    return TTL_0
