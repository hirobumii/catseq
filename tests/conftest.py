import pytest
from dataclasses import dataclass
from functools import partial

from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism
from catseq.hardware.ttl import TTLDevice
from catseq.hardware.rwg import RWGDevice
from .helpers import StateA, StateB, StateC

# --- Test Fixtures and Dummy Classes ---

# Create a pre-configured RWGDevice type for testing purposes
TestRWGDevice = partial(RWGDevice, available_sbgs={0, 1, 2, 3}, max_ramping_order=3)

# Concrete Channel instances for use in all tests
TTL_0 = Channel("TTL_0", TTLDevice)
TTL_1 = Channel("TTL_1", TTLDevice)
RWG_0 = Channel("RWG_0", TestRWGDevice)


# Fixtures now provide concrete channel instances
@pytest.fixture
def ch_a() -> Channel: return TTL_0
@pytest.fixture
def ch_b() -> Channel: return TTL_1
@pytest.fixture
def ch_rwg() -> Channel: return RWG_0


@pytest.fixture
def ttl_channel() -> Channel:
    return TTL_0
