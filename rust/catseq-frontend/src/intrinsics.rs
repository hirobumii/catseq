//! Closed registry for source-level CatSeq intrinsics and special forms.

use crate::native_records;
use crate::typed::SourceType;

pub(crate) const REGISTRY_SEMANTIC_VERSION: u32 = 8;
const NATIVE_RECORD_REPLACE: &str = "catseq.replace";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum NativeMorphismTemplate {
    Hold,
    TtlPulse,
    RwgSetState,
    RwgRfPulse,
    RwgLinearRamp,
}

#[derive(Clone, Copy)]
enum ResultRule {
    Morphism,
    MorphismTemplate,
    Float64,
    Int64,
    Bool,
    Duration,
    FixedAggregate,
}

#[derive(Clone, Copy)]
struct Intrinsic {
    leaf: &'static str,
    result: ResultRule,
}

const INTRINSICS: &[Intrinsic] = &[
    Intrinsic {
        leaf: "identity",
        result: ResultRule::Morphism,
    },
    Intrinsic {
        leaf: "dict_to_morphism",
        result: ResultRule::Morphism,
    },
    Intrinsic {
        leaf: "repeat_morphism",
        result: ResultRule::Morphism,
    },
    Intrinsic {
        leaf: "reduce",
        result: ResultRule::Morphism,
    },
    Intrinsic {
        leaf: "hold",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "cycles",
        result: ResultRule::Duration,
    },
    Intrinsic {
        leaf: "pulse",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "set_state",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "set_high",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "set_low",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "rf_on",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "rf_off",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "rf_pulse",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "linear_ramp",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "global_sync",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "pid_config",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "pid_start",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "pid_hold",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "pid_release",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "pid_relink",
        result: ResultRule::MorphismTemplate,
    },
    Intrinsic {
        leaf: "arccos",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "arcsin",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "cos",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "sin",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "sqrt",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "float",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "len",
        result: ResultRule::Int64,
    },
    Intrinsic {
        leaf: "int",
        result: ResultRule::Int64,
    },
    Intrinsic {
        leaf: "bool",
        result: ResultRule::Bool,
    },
    Intrinsic {
        leaf: "range",
        result: ResultRule::FixedAggregate,
    },
    Intrinsic {
        leaf: "enumerate",
        result: ResultRule::FixedAggregate,
    },
    Intrinsic {
        leaf: "zip",
        result: ResultRule::FixedAggregate,
    },
    Intrinsic {
        leaf: "tuple",
        result: ResultRule::FixedAggregate,
    },
    Intrinsic {
        leaf: "ones_like",
        result: ResultRule::FixedAggregate,
    },
    Intrinsic {
        leaf: "mod",
        result: ResultRule::Float64,
    },
    Intrinsic {
        leaf: "sum",
        result: ResultRule::Float64,
    },
];

pub(crate) fn return_type(path: &str, first_argument: Option<&SourceType>) -> Option<SourceType> {
    if path == "numpy.load" || path == "np.load" {
        return Some(SourceType::NativeRecord("CalibrationSnapshot".to_owned()));
    }
    if is_native_record_replace(path) {
        return first_argument.and_then(|source_type| match source_type {
            SourceType::NativeRecord(schema) => Some(SourceType::NativeRecord(schema.clone())),
            _ => None,
        });
    }
    if let Some(schema) = native_records::schema_for_constructor(path) {
        return Some(SourceType::NativeRecord(schema.name().to_owned()));
    }
    let leaf = path.rsplit('.').next().unwrap_or(path);
    if leaf == "cycles" && path != "cycles" && path != "catseq.time_utils.cycles" {
        return None;
    }
    let intrinsic = INTRINSICS.iter().find(|intrinsic| intrinsic.leaf == leaf);
    if intrinsic.is_none() && path.starts_with("catseq.hardware.") {
        return Some(SourceType::MorphismTemplate);
    }
    let intrinsic = intrinsic?;
    Some(match intrinsic.result {
        ResultRule::Morphism => SourceType::Morphism,
        ResultRule::MorphismTemplate => SourceType::MorphismTemplate,
        ResultRule::Float64 => SourceType::Float64,
        ResultRule::Int64 => SourceType::Int64,
        ResultRule::Bool => SourceType::Bool,
        ResultRule::Duration => SourceType::Duration,
        ResultRule::FixedAggregate => SourceType::FixedAggregate,
    })
}

pub(crate) fn parameter_types(path: &str) -> Vec<(usize, &'static str, SourceType)> {
    match path {
        "catseq.hardware.common.hold"
        | "catseq.hardware.rwg.hold"
        | "catseq.hardware.rwg.rf_pulse"
        | "catseq.hardware.ttl.hold"
        | "catseq.hardware.ttl.pulse" => {
            vec![(0, "duration", SourceType::Duration)]
        }
        "catseq.hardware.rwg.linear_ramp" => {
            vec![(1, "duration", SourceType::Duration)]
        }
        "catseq.time_utils.cycles" => vec![(0, "count", SourceType::Int64)],
        _ => Vec::new(),
    }
}

pub(crate) fn is_duration_unit(path: &str) -> bool {
    matches!(
        path,
        "catseq.time_utils.s"
            | "catseq.time_utils.ms"
            | "catseq.time_utils.us"
            | "catseq.time_utils.ns"
    )
}

pub(crate) fn is_identity(path: &str) -> bool {
    matches!(
        path,
        "catseq.morphism.identity" | "catseq.morphism.core.identity"
    )
}

pub(crate) fn is_registered(path: &str) -> bool {
    return_type(path, None).is_some()
}

pub(crate) fn is_native_record_replace(path: &str) -> bool {
    path == NATIVE_RECORD_REPLACE
}

pub(crate) fn is_compiler_special_form(resolved: &str) -> bool {
    is_native_record_replace(resolved)
        || matches!(
            resolved,
            "rb1system.utils.dict_to_morphism" | "catseq.time_utils.cycles"
        )
}

/// Return the precompiled template body associated with a composite hardware
/// API. Everything else in ``catseq.hardware`` is an Atomic Schema unless it
/// is handled as a compiler Special Form above.
pub(crate) fn native_morphism_template(path: &str) -> Option<NativeMorphismTemplate> {
    match path {
        "catseq.hardware.common.hold" | "catseq.hardware.rwg.hold" | "catseq.hardware.ttl.hold" => {
            Some(NativeMorphismTemplate::Hold)
        }
        "catseq.hardware.ttl.pulse" => Some(NativeMorphismTemplate::TtlPulse),
        "catseq.hardware.rwg.set_state" => Some(NativeMorphismTemplate::RwgSetState),
        "catseq.hardware.rwg.rf_pulse" => Some(NativeMorphismTemplate::RwgRfPulse),
        "catseq.hardware.rwg.linear_ramp" => Some(NativeMorphismTemplate::RwgLinearRamp),
        _ => None,
    }
}
