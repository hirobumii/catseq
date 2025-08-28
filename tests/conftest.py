import pytest

from catseq.core.protocols import Channel
from catseq.hardware.ttl import TTLDevice

# --- Test Fixtures and Dummy Classes ---

# Concrete Channel instances for use in all tests
# The device itself needs a name, which can be the same as the channel name.
TTL_0 = Channel("TTL_0", TTLDevice("TTL_0"))
TTL_1 = Channel("TTL_1", TTLDevice("TTL_1"))

# Fixtures now provide concrete channel instances
@pytest.fixture
def ch_a() -> Channel:
    return TTL_0


@pytest.fixture
def ch_b() -> Channel:
    return TTL_1


@pytest.fixture
def ttl_channel() -> Channel:
    return TTL_0
