# tests/states/test_dac.py

"""
Test suite for DAC states defined in `catseq/states/dac.py`.

This file tests the data classes related to the Digital-to-Analog Converter
(DAC) states, including:
- `DACState`: The base state for the DAC.
- `DACOff`: The state representing the DAC being off.
- `DACStatic`: The state representing the DAC holding a static voltage.

Tests verify correct instantiation, attribute values, and immutability.
"""

import pytest
from dataclasses import FrozenInstanceError
from catseq.protocols import State
from catseq.states.dac import DACState, DACOff, DACStatic


def test_dac_off_state():
    """
    Tests the properties of the DACOff state.
    - It should be a subclass of DACState and State.
    - It should be instantiable.
    - It must be immutable (frozen).
    """
    assert issubclass(DACOff, DACState)
    assert issubclass(DACOff, State)

    # Instantiate the state
    dac_off_state = DACOff()
    assert isinstance(dac_off_state, DACOff)

    # Verify that it is frozen (immutable)
    with pytest.raises(FrozenInstanceError):
        dac_off_state.new_attribute = "test"  # type: ignore


def test_dac_static_state():
    """
    Tests the properties of the DACStatic state.
    - It should be a subclass of DACState and State.
    - It should correctly store the 'voltage' attribute.
    - It must be immutable (frozen).
    """
    assert issubclass(DACStatic, DACState)
    assert issubclass(DACStatic, State)

    # Instantiate the state with a specific voltage
    voltage = 1.23
    dac_static_state = DACStatic(voltage=voltage)
    assert isinstance(dac_static_state, DACStatic)
    assert dac_static_state.voltage == voltage

    # Verify that it is frozen (immutable)
    with pytest.raises(FrozenInstanceError):
        dac_static_state.voltage = 4.56  # type: ignore
