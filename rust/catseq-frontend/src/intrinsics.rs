//! Closed registry for source-level CatSeq intrinsics and special forms.

use crate::typed::SourceType;

pub(crate) const REGISTRY_SEMANTIC_VERSION: u32 = 3;

#[derive(Clone, Copy)]
enum ResultRule {
    Morphism,
    MorphismTemplate,
    Float64,
    Int64,
    Bool,
    FixedAggregate,
    NativeRecord(&'static str),
    ReplaceFirstArgument,
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
        leaf: "replace",
        result: ResultRule::ReplaceFirstArgument,
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
    Intrinsic {
        leaf: "StaticWaveform",
        result: ResultRule::NativeRecord("StaticWaveform"),
    },
];

pub(crate) fn return_type(path: &str, first_argument: Option<&SourceType>) -> Option<SourceType> {
    if path == "numpy.load" || path == "np.load" {
        return Some(SourceType::NativeRecord("CalibrationSnapshot".to_owned()));
    }
    let leaf = path.rsplit('.').next().unwrap_or(path);
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
        ResultRule::FixedAggregate => SourceType::FixedAggregate,
        ResultRule::NativeRecord(schema) => SourceType::NativeRecord(schema.to_owned()),
        ResultRule::ReplaceFirstArgument => first_argument
            .cloned()
            .unwrap_or_else(|| SourceType::NativeRecord("dataclass".to_owned())),
    })
}

pub(crate) fn is_registered(path: &str) -> bool {
    return_type(path, None).is_some()
}

pub(crate) fn is_compiler_special_form(resolved: &str) -> bool {
    resolved == "rb1system.utils.dict_to_morphism"
}
