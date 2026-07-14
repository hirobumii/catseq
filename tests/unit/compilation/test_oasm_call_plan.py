from catseq.compilation.execution import oasm_call_plan_to_calls
from catseq.compilation.types import OASMAddress, OASMFunction
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

    calls = oasm_call_plan_to_calls(
        plan, opaque_callables={"test.calibration": opaque}
    )[OASMAddress.RWG8]

    assert [call.dsl_func for call in calls] == [
        OASMFunction.RWG_LOAD_WAVEFORM,
        OASMFunction.USER_DEFINED_FUNC,
    ]
    waveform = calls[0].args[0]
    assert isinstance(waveform, WaveformParams)
    assert waveform.freq_coeffs == (1.0, None, None, None)
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
        oasm_call_plan_to_calls(plan)
    except ValueError as error:
        assert "No host callable is registered" in str(error)
    else:
        raise AssertionError("missing opaque binding was accepted")
