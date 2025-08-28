"""
A simple demonstration of the refactored CatSeq framework for TTL control.
"""

# 1. Import necessary components from the framework
from catseq.core import Channel, SystemState
from catseq.hardware.ttl import TTLDevice
from catseq.states.ttl import TTLOn, TTLOff
from catseq.morphisms.common import hold
from catseq.morphisms.ttl import pulse, initialize

def main():
    """
    Runs a demonstration of creating and composing TTL morphisms.
    """
    print("--- CatSeq TTL Framework Demonstration ---")

    # 2. Create a Channel for our TTL device.
    # The Channel is a singleton, so this can be defined once and reused.
    # The TTLDevice is the validation model for this channel.
    print("\n1. Defining hardware channel 'ttl0'...")
    ttl0 = Channel("ttl0", TTLDevice("ttl0"))
    print(f"   - Created channel: {ttl0}")

    # 3. Create basic morphisms using the factory functions.
    # These factories create fully-defined Morphism objects.
    print("\n2. Creating basic building blocks (morphisms)...")

    # A pulse that starts from OFF, goes ON for 10us, then returns to OFF.
    pulse_10us = pulse(ttl0, duration=10e-6)
    print(f"   - Created a {pulse_10us.duration * 1e6:.0f}us pulse: {pulse_10us}")

    # A hold that keeps the channel in the OFF state for 50us.
    # Note: We must explicitly provide the state for the hold.
    hold_50us_off = hold(ttl0, state=TTLOff(), duration=50e-6)
    print(f"   - Created a {hold_50us_off.duration * 1e6:.0f}us hold: {hold_50us_off}")

    # 4. Compose morphisms together using the '@' (serial) operator.
    # The framework validates that the states match at the composition boundary.
    # The sequence is: (pulse) -> (hold) -> (pulse)
    print("\n3. Composing morphisms into a complex sequence...")
    sequence = pulse_10us @ hold_50us_off @ pulse_10us
    print(f"   - Created sequence: {sequence}")

    # 5. Print the properties of the final composed morphism.
    print("\n4. Analyzing the final sequence...")
    print(f"   - Total duration: {sequence.duration * 1e6:.0f} microseconds")
    print(f"   - Starting state (dom): {sequence.dom}")
    print(f"   - Ending state (cod): {sequence.cod}")

    # Show the underlying atomic operations for the channel
    print("\n   - Atomic operations for channel 'ttl0':")
    for op in sequence.get_lane_operations(ttl0):
        print(f"     - {op.from_state} -> {op.to_state}, duration: {op.duration * 1e6:.1f}us")

    print("\n--- Demonstration Complete ---")


if __name__ == "__main__":
    main()
