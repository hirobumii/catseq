# tests/conftest.py
import pytest
from enum import Enum
from typing import Set
from dataclasses import dataclass

from catseq.model import State
from catseq.hardware.base import BaseHardware
from catseq.states.common import Uninitialized


# 1. 创建一个用于测试的极简硬件类
class DummyDevice(BaseHardware):
    """一个简单的、用于测试的硬件设备，其规则是拼接点状态必须完全相等。"""
    def validate_transition(self, from_state: State, to_state: State) -> None:
        if from_state != to_state:
            raise TypeError("State mismatch for DummyDevice")

# 2. 创建一个用于测试的 Channel 枚举
DUMMY_DEVICE_A = DummyDevice(name="dummy_A")
DUMMY_DEVICE_B = DummyDevice(name="dummy_B")

class DummyChannel(Enum):
    A = DUMMY_DEVICE_A
    B = DUMMY_DEVICE_B

    @property
    def name(self) -> str: return self.value.name
    @property
    def instance(self) -> BaseHardware: return self.value

# 3. 创建可被测试函数注入的 fixture
@pytest.fixture
def dummy_channel_a():
    return DummyChannel.A

@pytest.fixture
def dummy_channel_b():
    return DummyChannel.B

@pytest.fixture
def uninitialized_state():
    return Uninitialized()

@pytest.fixture
def dummy_state_1():
    @dataclass(frozen=True)
    class DummyState1(State):
        pass
    return DummyState1()

@pytest.fixture
def dummy_state_2():
    @dataclass(frozen=True)
    class DummyState2(State):
        pass
    return DummyState2()