//! Validated Python-free Morphism and Value Expression arena pair.
//!
//! This is an intermediate work product. It deliberately does not use the
//! `CanonicalProgram` domain name because Morphism Effects, native schemas and
//! complete provenance have not been attached yet.

use serde::{Deserialize, Serialize};

use crate::morphism_arena::{MorphismArena, MorphismArenaError, MorphismPayload};
use crate::value_expr::{ValueExprArena, ValueExprError};

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeArenas {
    morphisms: MorphismArena,
    values: ValueExprArena,
}

impl NativeArenas {
    pub fn new(
        morphisms: MorphismArena,
        values: ValueExprArena,
    ) -> Result<Self, NativeArenasError> {
        morphisms.validate()?;
        values.validate()?;
        for payload in morphisms.payloads() {
            match payload {
                MorphismPayload::Wait { duration } => {
                    values.node(*duration)?;
                }
                MorphismPayload::Atomic { .. } | MorphismPayload::DefinitionRef { .. } => {
                    for argument in morphisms.payload_arguments(payload)? {
                        values.node(*argument)?;
                    }
                }
                MorphismPayload::Instantiate { .. } => {}
                MorphismPayload::Loop { count } => {
                    values.node(*count)?;
                }
            }
        }
        Ok(Self { morphisms, values })
    }

    pub fn morphisms(&self) -> &MorphismArena {
        &self.morphisms
    }

    pub fn values(&self) -> &ValueExprArena {
        &self.values
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeArenasError(String);

impl std::fmt::Display for NativeArenasError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for NativeArenasError {}

impl From<MorphismArenaError> for NativeArenasError {
    fn from(error: MorphismArenaError) -> Self {
        Self(error.to_string())
    }
}

impl From<ValueExprError> for NativeArenasError {
    fn from(error: ValueExprError) -> Self {
        Self(error.to_string())
    }
}
