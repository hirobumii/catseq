from catseq.compilation.execution import (
    assemble_oasm_calls,
    decode_oasm_call_plan,
)
from catseq.compilation.types import OASMAddress, OASMCall, OASMFunction
from catseq.types.rwg import WaveformParams


def test_native_oasm_call_plan_is_converted_to_executable_python_calls():
    invoked = []

    def opaque(calibration, *, mode):
        invoked.append((calibration, mode))

    plan = {
        "schema_version": 1,
        "epochs": [
            {
                "id": 0,
                "origin_cycles": 0,
                "boards": [
                    {
                        "address": "rwg8",
                        "calls": [
                            {
                                "offset_cycles": 0,
                                "function": "rwg_load_waveform",
                                "args": [
                                    {
                                        "$type": "WaveformParams",
                                        "sbg_id": 32,
                                        "freq_coeffs": [1.0, None, None, None],
                                        "amp_coeffs": [0.5, None, None, None],
                                        "initial_phase": 0.25,
                                        "phase_reset": True,
                                        "fct": 1,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": 1,
                "origin_cycles": 100,
                "boards": [
                    {
                        "address": "rwg8",
                        "calls": [
                            {
                                "offset_cycles": 0,
                                "function": "user_defined_func",
                                "args": [
                                    "test.calibration",
                                    [{"x": [1.0], "y": [2.0]}],
                                    {"mode": "fast"},
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }

    calls = decode_oasm_call_plan(
        plan, opaque_callables={"test.calibration": opaque}
    )[OASMAddress.RWG8]

    assert [call.dsl_func for call in calls] == [
        OASMFunction.RWG_LOAD_WAVEFORM,
        OASMFunction.USER_DEFINED_FUNC,
    ]
    waveform = calls[0].args[0]
    assert isinstance(waveform, WaveformParams)
    assert waveform.freq_coeffs == (1.0, None, None, None)
    assert invoked == []
    user_func, args, kwargs = calls[1].args
    user_func(*args, **kwargs)
    assert invoked == [({"x": (1.0,), "y": (2.0,)}, "fast")]


def test_native_oasm_call_plan_requires_opaque_registry_binding():
    plan = {
        "schema_version": 1,
        "epochs": [
            {
                "id": 0,
                "origin_cycles": 0,
                "boards": [
                    {
                        "address": "rwg8",
                        "calls": [
                            {
                                "offset_cycles": 0,
                                "function": "user_defined_func",
                                "args": ["missing", [], {}],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    try:
        decode_oasm_call_plan(plan)
    except ValueError as error:
        assert "No host callable is registered" in str(error)
    else:
        raise AssertionError("missing opaque binding was accepted")


def test_typed_oasm_calls_are_submitted_to_the_explicit_assembler():
    class RecordingAssembler:
        def __init__(self):
            self.cleared = False
            self.invocations = []

        def clear(self):
            self.cleared = True

        def __call__(self, address, function, *args, **kwargs):
            self.invocations.append((address, function.__name__, args, kwargs))

    calls = {
        OASMAddress.MAIN: [
            OASMCall(
                adr=OASMAddress.MAIN,
                dsl_func=OASMFunction.WAIT,
                args=(25,),
            )
        ]
    }
    assembler = RecordingAssembler()

    result = assemble_oasm_calls(calls, assembler)

    assert result is assembler
    assert assembler.cleared is True
    assert assembler.invocations == [("main", "wait_mu", (25,), {})]
