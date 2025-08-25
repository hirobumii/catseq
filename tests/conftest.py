import pytest

from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice
from catseq.hardware.rwg import RWGDevice, RWGChannel

# --- Test Fixtures and Dummy Classes ---

class TestRWGDevice(RWGDevice):
    """
    A concrete RWGDevice class for testing that provides default parameters
    to satisfy the RWGDevice.__init__ signature.
    """
    def __init__(self, name: str):
        super().__init__(
            name=name,
            available_sbgs={0, 1, 2, 3},
            max_ramping_order=3
        )

# Concrete Channel instances for use in all tests
TTL_0 = Channel("TTL_0", TTLDevice)
TTL_1 = Channel("TTL_1", TTLDevice)
RWG_0 = RWGChannel("RWG_0", TestRWGDevice, sbg_ids=(0,))


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
