//! Closed schemas for compiler-owned Native Record values.

use std::fmt::{Display, Formatter};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum NativeRecordFieldType {
    Bool,
    Int64,
    Float64,
    OptionalInt64,
    OptionalFloat64,
    AggregateOfOptionalFloat64,
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
    fields: &'static [NativeRecordField],
}

impl NativeRecordSchema {
    pub(crate) const fn name(self) -> &'static str {
        self.name
    }

    pub(crate) fn field(self, name: &str) -> Option<NativeRecordField> {
        self.fields.iter().copied().find(|field| field.name == name)
    }

    pub(crate) fn field_at(self, position: usize) -> Option<NativeRecordField> {
        self.fields.get(position).copied()
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
        field_type: NativeRecordFieldType::Float64,
    },
    NativeRecordField {
        name: "fct",
        field_type: NativeRecordFieldType::OptionalInt64,
    },
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

const SCHEMAS: &[NativeRecordSchema] = &[
    NativeRecordSchema {
        name: "StaticWaveform",
        fields: STATIC_WAVEFORM_FIELDS,
    },
    NativeRecordSchema {
        name: "WaveformParams",
        fields: WAVEFORM_PARAMS_FIELDS,
    },
    NativeRecordSchema {
        name: "RSPPIDConfig",
        fields: RSP_PID_CONFIG_FIELDS,
    },
    NativeRecordSchema {
        name: "RSPWaveformParams",
        fields: RSP_WAVEFORM_PARAMS_FIELDS,
    },
];

pub(crate) fn schema(name: &str) -> Option<NativeRecordSchema> {
    SCHEMAS.iter().copied().find(|schema| schema.name == name)
}
