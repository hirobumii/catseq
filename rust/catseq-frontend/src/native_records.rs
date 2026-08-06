//! Closed schemas for compiler-owned Native Record values.

use std::fmt::{Display, Formatter};

use crate::typed::SourceType;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum NativeRecordFieldType {
    Bool,
    Int64,
    Float64,
    OptionalInt64,
    OptionalFloat64,
    AggregateOfOptionalFloat64,
}

impl NativeRecordFieldType {
    pub(crate) fn accepts(self, source_type: &SourceType) -> bool {
        match self {
            Self::Bool => source_type == &SourceType::Bool,
            Self::Int64 => source_type == &SourceType::Int64,
            Self::Float64 => matches!(source_type, SourceType::Int64 | SourceType::Float64),
            Self::OptionalInt64 => match source_type {
                SourceType::Unit | SourceType::Int64 => true,
                SourceType::Optional(inner) => inner.as_ref() == &SourceType::Int64,
                _ => false,
            },
            Self::OptionalFloat64 => match source_type {
                SourceType::Unit | SourceType::Int64 | SourceType::Float64 => true,
                SourceType::Optional(inner) => {
                    matches!(inner.as_ref(), SourceType::Int64 | SourceType::Float64)
                }
                _ => false,
            },
            Self::AggregateOfOptionalFloat64 => source_type == &SourceType::FixedAggregate,
        }
    }

    pub(crate) const fn aggregate_element_type(self) -> Option<Self> {
        match self {
            Self::AggregateOfOptionalFloat64 => Some(Self::OptionalFloat64),
            _ => None,
        }
    }
}

impl Display for NativeRecordFieldType {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::Bool => "Bool",
            Self::Int64 => "Int64",
            Self::Float64 => "Float64",
            Self::OptionalInt64 => "Optional<Int64>",
            Self::OptionalFloat64 => "Optional<Float64>",
            Self::AggregateOfOptionalFloat64 => "Aggregate<Optional<Float64>>",
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct NativeRecordField {
    name: &'static str,
    field_type: NativeRecordFieldType,
}

impl NativeRecordField {
    pub(crate) const fn name(self) -> &'static str {
        self.name
    }

    pub(crate) const fn field_type(self) -> NativeRecordFieldType {
        self.field_type
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct NativeRecordSchema {
    name: &'static str,
    constructor_identities: &'static [&'static str],
    fields: &'static [NativeRecordField],
}

impl NativeRecordSchema {
    pub(crate) const fn name(self) -> &'static str {
        self.name
    }

    pub(crate) fn has_constructor_identity(self, identity: &str) -> bool {
        self.constructor_identities.contains(&identity)
    }

    pub(crate) fn field(self, name: &str) -> Option<NativeRecordField> {
        self.fields.iter().copied().find(|field| field.name == name)
    }

    pub(crate) fn field_at(self, position: usize) -> Option<NativeRecordField> {
        self.fields.get(position).copied()
    }

    pub(crate) const fn fields(self) -> &'static [NativeRecordField] {
        self.fields
    }

    pub(crate) fn populate_defaults(self, record: &mut serde_json::Map<String, serde_json::Value>) {
        match self.name {
            "StaticWaveform" => {
                record.entry("freq").or_insert(serde_json::Value::Null);
                record.entry("amp").or_insert(serde_json::Value::Null);
                record.entry("sbg_id").or_insert(serde_json::Value::Null);
                record.entry("phase").or_insert(0.0.into());
                record.entry("fct").or_insert(serde_json::Value::Null);
            }
            "WaveformParams" => {
                record
                    .entry("freq_coeffs")
                    .or_insert(serde_json::json!([0.0, null, null, null]));
                record
                    .entry("amp_coeffs")
                    .or_insert(serde_json::json!([0.0, null, null, null]));
                record
                    .entry("initial_phase")
                    .or_insert(serde_json::Value::Null);
                record.entry("phase_reset").or_insert(false.into());
                record.entry("fct").or_insert(serde_json::Value::Null);
            }
            "RSPPIDConfig" => {
                record.entry("kp").or_insert((-1.0).into());
                record.entry("ki").or_insert((-0.02).into());
                record.entry("kd").or_insert(0.0.into());
                record.entry("output_max").or_insert(0.01.into());
            }
            "RSPWaveformParams" => {
                record.entry("output_max").or_insert(0.01.into());
            }
            _ => {}
        }
    }
}

const STATIC_WAVEFORM_FIELDS: &[NativeRecordField] = &[
    NativeRecordField {
        name: "freq",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
    NativeRecordField {
        name: "amp",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
    NativeRecordField {
        name: "sbg_id",
        field_type: NativeRecordFieldType::OptionalInt64,
    },
    NativeRecordField {
        name: "phase",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
    NativeRecordField {
        name: "fct",
        field_type: NativeRecordFieldType::OptionalInt64,
    },
];

const STATIC_WAVEFORM_CONSTRUCTORS: &[&str] = &[
    "catseq.types.StaticWaveform",
    "catseq.types.rwg.StaticWaveform",
    "catseq.hardware.rwg.StaticWaveform",
];

const WAVEFORM_PARAMS_FIELDS: &[NativeRecordField] = &[
    NativeRecordField {
        name: "sbg_id",
        field_type: NativeRecordFieldType::Int64,
    },
    NativeRecordField {
        name: "freq_coeffs",
        field_type: NativeRecordFieldType::AggregateOfOptionalFloat64,
    },
    NativeRecordField {
        name: "amp_coeffs",
        field_type: NativeRecordFieldType::AggregateOfOptionalFloat64,
    },
    NativeRecordField {
        name: "initial_phase",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
    NativeRecordField {
        name: "phase_reset",
        field_type: NativeRecordFieldType::Bool,
    },
    NativeRecordField {
        name: "fct",
        field_type: NativeRecordFieldType::OptionalInt64,
    },
];

const WAVEFORM_PARAMS_CONSTRUCTORS: &[&str] = &[
    "catseq.types.WaveformParams",
    "catseq.types.rwg.WaveformParams",
    "catseq.hardware.rwg.WaveformParams",
];

const RSP_PID_CONFIG_FIELDS: &[NativeRecordField] = &[
    NativeRecordField {
        name: "adc_in",
        field_type: NativeRecordFieldType::Int64,
    },
    NativeRecordField {
        name: "rf_out",
        field_type: NativeRecordFieldType::Int64,
    },
    NativeRecordField {
        name: "dgt_source",
        field_type: NativeRecordFieldType::Int64,
    },
    NativeRecordField {
        name: "setpoint",
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "kp",
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "ki",
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "kd",
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "output_max",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
];

const RSP_PID_CONFIG_CONSTRUCTORS: &[&str] = &[
    "catseq.types.RSPPIDConfig",
    "catseq.types.rsp.RSPPIDConfig",
    "catseq.hardware.rsp.RSPPIDConfig",
];

const RSP_WAVEFORM_PARAMS_FIELDS: &[NativeRecordField] = &[
    NativeRecordField {
        name: "rf_out",
        field_type: NativeRecordFieldType::Int64,
    },
    NativeRecordField {
        name: "amp",
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "output_max",
        field_type: NativeRecordFieldType::OptionalFloat64,
    },
];

const RSP_WAVEFORM_PARAMS_CONSTRUCTORS: &[&str] = &[
    "catseq.types.RSPWaveformParams",
    "catseq.types.rsp.RSPWaveformParams",
    "catseq.hardware.rsp.RSPWaveformParams",
];

const SCHEMAS: &[NativeRecordSchema] = &[
    NativeRecordSchema {
        name: "StaticWaveform",
        constructor_identities: STATIC_WAVEFORM_CONSTRUCTORS,
        fields: STATIC_WAVEFORM_FIELDS,
    },
    NativeRecordSchema {
        name: "WaveformParams",
        constructor_identities: WAVEFORM_PARAMS_CONSTRUCTORS,
        fields: WAVEFORM_PARAMS_FIELDS,
    },
    NativeRecordSchema {
        name: "RSPPIDConfig",
        constructor_identities: RSP_PID_CONFIG_CONSTRUCTORS,
        fields: RSP_PID_CONFIG_FIELDS,
    },
    NativeRecordSchema {
        name: "RSPWaveformParams",
        constructor_identities: RSP_WAVEFORM_PARAMS_CONSTRUCTORS,
        fields: RSP_WAVEFORM_PARAMS_FIELDS,
    },
];

pub(crate) fn schema(name: &str) -> Option<NativeRecordSchema> {
    SCHEMAS.iter().copied().find(|schema| schema.name == name)
}

pub(crate) fn schema_for_constructor(identity: &str) -> Option<NativeRecordSchema> {
    SCHEMAS
        .iter()
        .copied()
        .find(|schema| schema.has_constructor_identity(identity))
}
