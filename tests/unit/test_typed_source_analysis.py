from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

import pytest

from catseq import _native
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.hardware.rwg import initialize as rwg_initialize
from catseq.hardware.sync import global_sync
from catseq.hardware.ttl import initialize as ttl_initialize
from catseq.hardware.ttl import pulse as ttl_pulse
from catseq.morphism import Morphism, atomic_morphism, identity, morphism
from catseq.morphism.core import compute, kernel
from catseq.time_utils import cycles


@kernel
def _make_delay(width: int) -> Morphism:
    return identity(cycles(width)) >> identity(cycles(2))


@kernel
def _unreachable_invalid(flag: bool) -> Morphism:
    if flag:
        return identity(cycles(1))
    return identity(cycles(2))


@dataclass
class _SourceHirExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")
    unused_width: ClassVar[ExpParam[object]] = ExpParam("unused_width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        width = params[self.width]
        return _make_delay(width)


@compute
def _normalize_width(width: int) -> int:
    if width < 1:
        return 1
    return width


_normalize_width_alias = _normalize_width


@dataclass
class _ComputeSourceHirExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        width = _normalize_width(params[self.width])
        return identity(cycles(width))


@dataclass
class _DeduplicatedComputeExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        first = identity(cycles(_normalize_width(params[self.width])))
        return first >> identity(cycles(_normalize_width_alias(params[self.width])))


@kernel
def _first_delay(width: int) -> Morphism:
    return identity(cycles(width))


@kernel
def _second_delay(width: int) -> Morphism:
    return identity(cycles(width)) >> identity(cycles(1))


_selected_delay = _first_delay


@dataclass
class _AliasExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _selected_delay(params[self.width])


@dataclass
class _MethodExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def delay(self, width: int) -> Morphism:
        return identity(cycles(width))

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return self.delay(params[self.width])


@dataclass
class _AliasedMethodExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def delay(self, width: int) -> Morphism:
        return identity(cycles(width))

    alias = delay
    delay = object()

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return self.alias(params[self.width])


@atomic_morphism("typed_source_leaf")
def _atomic_leaf(width: int) -> Morphism:
    raise AssertionError("an Atomic body must not execute")


@morphism
def _registered_morphism(width: int) -> Morphism:
    return _atomic_leaf(width)


@morphism
def _invalid_morphism_result() -> int:
    return 1


@atomic_morphism("invalid_atomic_result")
def _invalid_atomic_result() -> int:
    raise AssertionError("an Atomic body must not execute")


@dataclass
class _MorphismDefinitionExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _registered_morphism(params[self.width])


@dataclass
class _InvalidMorphismResultExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(_invalid_morphism_result()))


@dataclass
class _InvalidAtomicResultExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(_invalid_atomic_result()))


@dataclass
class _TtlAtomicExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return ttl_initialize()


@dataclass
class _TtlDurationExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return ttl_pulse(cycles(1))


@dataclass
class _RwgDefaultExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return rwg_initialize(100e6)


@dataclass
class _ShippedIntrinsicExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return global_sync()


@dataclass
class _UnsupportedStatementExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        if params[self.width] > 0:
            return identity(cycles(1))
        return identity(cycles(2))


_host_helper_executed = False


def _host_helper(width: int) -> int:
    global _host_helper_executed
    _host_helper_executed = True
    return width


@dataclass
class _HostRpcExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(_host_helper(params[self.width])))


@dataclass
class _HostMethodRpcExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    def host_helper(self, width: int) -> int:
        global _host_helper_executed
        _host_helper_executed = True
        return width

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(self.host_helper(params[self.width])))


@compute
def _invalid_compute_leaf(width: int) -> int:
    return width / 2


@compute
def _invalid_compute_root(width: int) -> int:
    return _invalid_compute_leaf(width)


@dataclass
class _InvalidComputeExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(_invalid_compute_root(params[self.width])))


@dataclass
class _MissingParamExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(params[self.width]))


@dataclass
class _IndirectCallExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        selected = _first_delay
        return selected(params[self.width])


@dataclass
class _InvalidCallShapeExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _first_delay(width=params[self.width])


@dataclass
class _UnsupportedSubscriptExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(params[self.width][0]))


@dataclass
class _ExtraEntryArgumentExperiment(BaseExp):
    @kernel
    def build_sequence(
        self,
        params: ExpParams,
        never_bound: int,
    ) -> Morphism:
        return identity(cycles(never_bound))


_aliased_width = ExpParam[int]("aliased_width")


@dataclass
class _AliasedExpParamExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = _aliased_width
    width_alias: ClassVar[ExpParam[int]] = _aliased_width

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        first = identity(cycles(params[self.width]))
        return first >> identity(cycles(params[self.width_alias]))


@dataclass
class _ReboundParamsExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        params = 0
        return identity(cycles(params[self.width]))


@kernel
def _foreign_self(self: int) -> Morphism:
    return self.real_delay(self)


@dataclass
class _ForeignSelfExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def real_delay(self, width: int) -> Morphism:
        return identity(cycles(width))

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _foreign_self(params[self.width])


@dataclass
class _UnboundOwnerMethodExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def delay(self, width: int) -> Morphism:
        return identity(cycles(width))

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _unbound_owner_delay(params[self.width])


_unbound_owner_delay = _UnboundOwnerMethodExperiment.delay


@dataclass
class _StaticEntryExperiment(BaseExp):
    @staticmethod
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(1))


@kernel
def _global_delay_with_unused_class_alias(width: int) -> Morphism:
    return identity(cycles(width))


@dataclass
class _UnusedClassAliasExperiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")
    unused_class_alias = _global_delay_with_unused_class_alias

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _global_delay_with_unused_class_alias(params[self.width])


def test_registered_entry_analysis_publishes_only_reachable_loop_free_source() -> None:
    frontend = _native._FrontendSession({"unused": object()})
    experiment = _SourceHirExperiment(
        h5_writer=cast(Any, object()),
    )
    params = ExpParams(
        {
            _SourceHirExperiment.width: 4,
            _SourceHirExperiment.unused_width: object(),
        }
    )

    analysis = frontend._analyze_registered_kernel(experiment, params)

    entry_name = f"{__name__}._SourceHirExperiment.build_sequence"
    helper_name = f"{__name__}._make_delay"
    assert analysis._entry_name == entry_name
    assert analysis._body_definitions == [
        (entry_name, "kernel"),
        (helper_name, "kernel"),
    ]
    assert analysis._call_edges == [(entry_name, helper_name, "kernel")]
    assert analysis._external_reads == [("width", "i32", "compile", 4)]
    assert analysis._morphism_compositions == [(helper_name, "auto_serial")]
    assert analysis._compute_source_profile_id is None
    assert analysis._compute_unit_count == 0
    assert analysis._compute_source_unit_count == 0
    assert not hasattr(analysis, "__dict__")


def test_registered_entry_analysis_seals_compute_interface_without_copying_body(
) -> None:
    frontend = _native._FrontendSession({})
    experiment = _ComputeSourceHirExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_ComputeSourceHirExperiment.width: 4}),
    )

    entry_name = f"{__name__}._ComputeSourceHirExperiment.build_sequence"
    compute_name = f"{__name__}._normalize_width"
    assert analysis._body_definitions == [(entry_name, "kernel")]
    assert analysis._call_edges == [(entry_name, compute_name, "compute")]
    assert analysis._compute_source_profile_id == "catseq-int32-v1"
    assert analysis._compute_unit_count == 1
    assert analysis._compute_source_unit_count == 1

    [call] = analysis._compute_calls
    [interface] = analysis._compute_interfaces
    assert call[1] == interface[0]
    assert call[2:4] == ("compile", "empty")
    assert call[4].endswith("test_typed_source_analysis.py")
    assert call[5] > 0
    assert interface[1:4] == (["i32"], "i32", "(i32)->i32")
    assert len(interface[4]) == 64
    assert interface[5].endswith("test_typed_source_analysis.py")
    assert interface[6] > 0


def test_registered_entry_analysis_resolves_final_exact_alias_binding() -> None:
    global _selected_delay

    frontend = _native._FrontendSession({})
    experiment = _AliasExperiment(
        h5_writer=cast(Any, object()),
    )
    params = ExpParams({_AliasExperiment.width: 4})
    first_name = f"{__name__}._first_delay"
    second_name = f"{__name__}._second_delay"

    _selected_delay = _first_delay
    first = frontend._analyze_registered_kernel(experiment, params)
    try:
        _selected_delay = _second_delay
        second = frontend._analyze_registered_kernel(experiment, params)
    finally:
        _selected_delay = _first_delay

    assert first._call_edges[0][1] == first_name
    assert second._call_edges[0][1] == second_name


def test_registered_entry_analysis_deduplicates_compute_roots_not_calls() -> None:
    frontend = _native._FrontendSession({})
    experiment = _DeduplicatedComputeExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_DeduplicatedComputeExperiment.width: 4}),
    )

    assert analysis._compute_unit_count == 1
    assert analysis._compute_source_unit_count == 1
    assert len(analysis._compute_calls) == 2
    assert {call[1] for call in analysis._compute_calls} == {
        analysis._compute_interfaces[0][0]
    }


def test_registered_entry_analysis_accepts_exact_registered_owner_method() -> None:
    frontend = _native._FrontendSession({})
    experiment = _MethodExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_MethodExperiment.width: 4}),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._MethodExperiment.build_sequence", "kernel"),
        (f"{__name__}._MethodExperiment.delay", "kernel"),
    ]


def test_registered_entry_analysis_uses_final_exact_owner_method_alias() -> None:
    frontend = _native._FrontendSession({})
    experiment = _AliasedMethodExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_AliasedMethodExperiment.width: 4}),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._AliasedMethodExperiment.build_sequence", "kernel"),
        (f"{__name__}._AliasedMethodExperiment.delay", "kernel"),
    ]


def test_registered_entry_analysis_retains_morphism_definition_and_atomic_leaf() -> None:
    frontend = _native._FrontendSession({})
    experiment = _MorphismDefinitionExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_MorphismDefinitionExperiment.width: 4}),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._MorphismDefinitionExperiment.build_sequence", "kernel"),
        (f"{__name__}._registered_morphism", "morphism_definition"),
        (f"{__name__}._atomic_leaf", "atomic"),
    ]
    [atomic] = analysis._atomic_definitions
    assert atomic[:2] == (f"{__name__}._atomic_leaf", "typed_source_leaf")
    assert atomic[2].endswith("test_typed_source_analysis.py")
    assert atomic[3] > 0


@pytest.mark.parametrize(
    ("experiment_type", "role_name"),
    [
        pytest.param(
            _InvalidMorphismResultExperiment,
            "Morphism Definition",
            id="morphism-definition",
        ),
        pytest.param(
            _InvalidAtomicResultExperiment,
            "Atomic Morphism",
            id="atomic-morphism",
        ),
    ],
)
def test_registered_entry_analysis_rejects_non_morphism_sequencing_results(
    experiment_type: type[BaseExp], role_name: str
) -> None:
    experiment = experiment_type(h5_writer=cast(Any, object()))

    with pytest.raises(
        RuntimeError,
        match=rf"{role_name} return annotation must be Morphism",
    ) as raised:
        _native._FrontendSession({})._analyze_registered_kernel(
            experiment,
            ExpParams.empty(),
        )

    assert "test_typed_source_analysis.py:" in str(raised.value)


def test_registered_entry_analysis_admits_shipped_morphism_annotations() -> None:
    frontend = _native._FrontendSession({})

    atomic = frontend._analyze_registered_kernel(
        _TtlAtomicExperiment(h5_writer=cast(Any, object())),
        ExpParams.empty(),
    )
    duration = frontend._analyze_registered_kernel(
        _TtlDurationExperiment(h5_writer=cast(Any, object())),
        ExpParams.empty(),
    )

    assert atomic._body_definitions == [
        (f"{__name__}._TtlAtomicExperiment.build_sequence", "kernel"),
        ("catseq.hardware.ttl.initialize", "atomic"),
    ]
    assert duration._body_definitions == [
        (f"{__name__}._TtlDurationExperiment.build_sequence", "kernel"),
        ("catseq.hardware.ttl.pulse", "morphism_definition"),
        ("catseq.hardware.ttl.set_high", "atomic"),
        ("catseq.hardware.ttl.hold", "intrinsic"),
        ("catseq.hardware.ttl.set_low", "atomic"),
    ]


def test_registered_entry_analysis_applies_shipped_default_parameter() -> None:
    analysis = _native._FrontendSession({})._analyze_registered_kernel(
        _RwgDefaultExperiment(h5_writer=cast(Any, object())),
        ExpParams.empty(),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._RwgDefaultExperiment.build_sequence", "kernel"),
        ("catseq.hardware.rwg.initialize", "atomic"),
    ]


def test_registered_entry_analysis_classifies_shipped_intrinsic_before_rpc() -> None:
    analysis = _native._FrontendSession({})._analyze_registered_kernel(
        _ShippedIntrinsicExperiment(h5_writer=cast(Any, object())),
        ExpParams.empty(),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._ShippedIntrinsicExperiment.build_sequence", "kernel"),
        ("catseq.hardware.sync.global_sync", "intrinsic"),
    ]


def test_registered_entry_analysis_rejects_reachable_unsupported_syntax() -> None:
    frontend = _native._FrontendSession({})
    experiment = _UnsupportedStatementExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError) as raised:
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_UnsupportedStatementExperiment.width: 4}),
        )

    message = str(raised.value)
    assert "unsupported statement in the initial loop-free" in message
    assert "test_typed_source_analysis.py:" in message


def test_registered_entry_analysis_classifies_host_rpc_without_execution() -> None:
    global _host_helper_executed

    _host_helper_executed = False
    frontend = _native._FrontendSession({})
    experiment = _HostRpcExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="unimplemented: host RPC calls"):
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_HostRpcExperiment.width: 4}),
        )

    assert not _host_helper_executed


def test_registered_entry_analysis_classifies_host_method_without_execution() -> None:
    global _host_helper_executed

    _host_helper_executed = False
    frontend = _native._FrontendSession({})
    experiment = _HostMethodRpcExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="unimplemented: host RPC calls"):
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_HostMethodRpcExperiment.width: 4}),
        )

    assert not _host_helper_executed


def test_registered_entry_analysis_failure_does_not_publish_compute_result() -> None:
    frontend = _native._FrontendSession({})
    invalid = _InvalidComputeExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError) as raised:
        frontend._analyze_registered_kernel(
            invalid,
            ExpParams({_InvalidComputeExperiment.width: 4}),
        )

    message = str(raised.value)
    assert "operator `/` is not admitted by CatSeqInt32V1" in message
    assert "test_typed_source_analysis.py:" in message

    valid = _ComputeSourceHirExperiment(
        h5_writer=cast(Any, object()),
    )
    analysis = frontend._analyze_registered_kernel(
        valid,
        ExpParams({_ComputeSourceHirExperiment.width: 4}),
    )
    assert analysis._compute_unit_count == 1


@pytest.mark.parametrize(
    "params, expected",
    [
        (ExpParams.empty(), "ExpParams has no value for `width`"),
        (
            ExpParams({_MissingParamExperiment.width: object()}),
            "ExpParam `width` must contain an exact bool, i32 int, f64 float, or string",
        ),
    ],
)
def test_registered_entry_analysis_rejects_missing_or_unsupported_exp_param(
    params: ExpParams,
    expected: str,
) -> None:
    frontend = _native._FrontendSession({})
    experiment = _MissingParamExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError) as raised:
        frontend._analyze_registered_kernel(experiment, params)

    assert expected in str(raised.value)
    assert "test_typed_source_analysis.py:" in str(raised.value)


def test_registered_entry_analysis_rejects_indirect_local_call() -> None:
    frontend = _native._FrontendSession({})
    experiment = _IndirectCallExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError) as raised:
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_IndirectCallExperiment.width: 4}),
        )

    assert "indirect or dynamically selected calls are unsupported" in str(
        raised.value
    )
    assert "test_typed_source_analysis.py:" in str(raised.value)


def test_registered_entry_analysis_binds_keyword_call() -> None:
    frontend = _native._FrontendSession({})
    experiment = _InvalidCallShapeExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_InvalidCallShapeExperiment.width: 4}),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._InvalidCallShapeExperiment.build_sequence", "kernel"),
        (f"{__name__}._first_delay", "kernel"),
    ]


def test_registered_entry_analysis_rejects_unowned_subscript() -> None:
    frontend = _native._FrontendSession({})
    experiment = _UnsupportedSubscriptExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError) as raised:
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_UnsupportedSubscriptExperiment.width: 4}),
        )

    assert "only params[self.<ExpParam>] subscripts are admitted" in str(
        raised.value
    )
    assert "test_typed_source_analysis.py:" in str(raised.value)


def test_registered_entry_analysis_rejects_unbound_entry_arguments() -> None:
    frontend = _native._FrontendSession({})
    experiment = _ExtraEntryArgumentExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="entry signature must be"):
        frontend._analyze_registered_kernel(experiment, ExpParams.empty())


def test_registered_entry_analysis_deduplicates_exact_exp_param_aliases() -> None:
    frontend = _native._FrontendSession({})
    experiment = _AliasedExpParamExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_aliased_width: 4}),
    )

    assert analysis._external_reads == [("aliased_width", "i32", "compile", 4)]


def test_registered_entry_analysis_rejects_rebound_exp_params_authority() -> None:
    frontend = _native._FrontendSession({})
    experiment = _ReboundParamsExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="parameter reads require the exact"):
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_ReboundParamsExperiment.width: 4}),
        )


def test_registered_entry_analysis_does_not_authorize_self_by_spelling() -> None:
    frontend = _native._FrontendSession({})
    experiment = _ForeignSelfExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="indirect or dynamically selected calls"):
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_ForeignSelfExperiment.width: 4}),
        )


def test_registered_entry_analysis_keeps_unbound_owner_receiver_explicit() -> None:
    frontend = _native._FrontendSession({})
    experiment = _UnboundOwnerMethodExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="call is missing required parameters: width"):
        frontend._analyze_registered_kernel(
            experiment,
            ExpParams({_UnboundOwnerMethodExperiment.width: 4}),
        )


def test_registered_entry_analysis_rejects_static_entry_receiver() -> None:
    frontend = _native._FrontendSession({})
    experiment = _StaticEntryExperiment(
        h5_writer=cast(Any, object()),
    )

    with pytest.raises(RuntimeError, match="parameter `self` requires"):
        frontend._analyze_registered_kernel(experiment, ExpParams.empty())


def test_unused_class_alias_does_not_change_global_kernel_signature() -> None:
    frontend = _native._FrontendSession({})
    experiment = _UnusedClassAliasExperiment(
        h5_writer=cast(Any, object()),
    )

    analysis = frontend._analyze_registered_kernel(
        experiment,
        ExpParams({_UnusedClassAliasExperiment.width: 4}),
    )

    assert analysis._body_definitions == [
        (f"{__name__}._UnusedClassAliasExperiment.build_sequence", "kernel"),
        (f"{__name__}._global_delay_with_unused_class_alias", "kernel"),
    ]
