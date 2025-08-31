# tests/minimal_bug_repro.py
import sys

print("Python version:")
print(sys.version)
print("-" * 20)

# We need to import the components
from catseq.compilation.types import OASMCall, OASMFunction, OASMAddress
from catseq.compilation.functions import ttl_set

print("--- Minimal Reproducible Example ---")
print("Attempting to create an OASMCall object directly.")
print(f"Enum member to be used: {OASMFunction.TTL_SET}")
print(f"Type of enum member: {type(OASMFunction.TTL_SET)}")
print(f"Value of enum member: {OASMFunction.TTL_SET.value}")
print(f"ID of enum member's value: {id(OASMFunction.TTL_SET.value)}")
print(f"ID of imported ttl_set function: {id(ttl_set)}")
print("-" * 20)

try:
    # This is the line that reproduces the bug.
    # The compiler calls this, and it triggers the faulty __post_init__
    print("Instantiating OASMCall(dsl_func=OASMFunction.TTL_SET)...")
    call_object = OASMCall(
        adr=OASMAddress.RWG0,
        dsl_func=OASMFunction.TTL_SET, # Passing the enum member
        args=(1, 1)
    )
    print("✅ SUCCESS: OASMCall object created without error.")
    print(f"Resulting dsl_func: {call_object.dsl_func}")

except TypeError as e:
    print(f"❌ FAILURE: Caught expected TypeError.")
    print(e)

print("-" * 20)
print("This script demonstrates the core issue:")
print("Even when explicitly passing the Enum member `OASMFunction.TTL_SET` to the constructor,")
print("the `__post_init__` method receives it as a raw function and fails to match it back to the enum.")
