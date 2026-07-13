//! Stable template definitions and demand-driven specialization caching.
//!
//! Python executes the CatSeq DSL and resolves Python objects into stable IDs.
//! This module starts after that boundary: it contains no Python or backend
//! types, and its cache keys deliberately exclude runtime scan values.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use crate::arena::TemplateId;

/// Slot populated when an experiment supplies scan values at link time.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RuntimeValueId(u32);

impl RuntimeValueId {
    pub const fn from_index(index: u32) -> Self {
        Self(index)
    }

    pub const fn index(self) -> u32 {
        self.0
    }
}

/// Stable index into a compiler session's definition table.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct DefinitionId(u32);

impl DefinitionId {
    pub const fn from_index(index: u32) -> Self {
        Self(index)
    }

    pub const fn index(self) -> u32 {
        self.0
    }
}

/// Parameter shape known before a template is specialized.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TemplateSignature {
    scan_slots: u32,
    structural_slots: u32,
}

impl TemplateSignature {
    pub const fn new(scan_slots: u32, structural_slots: u32) -> Self {
        Self {
            scan_slots,
            structural_slots,
        }
    }

    pub const fn scan_slots(self) -> u32 {
        self.scan_slots
    }

    pub const fn structural_slots(self) -> u32 {
        self.structural_slots
    }
}

/// One immutable template registered by the Python frontend.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TemplateDefinition {
    template: TemplateId,
    signature: TemplateSignature,
}

impl TemplateDefinition {
    pub const fn template(self) -> TemplateId {
        self.template
    }

    pub const fn signature(self) -> TemplateSignature {
        self.signature
    }
}

/// Append-only table whose IDs remain valid for the compiler session lifetime.
#[derive(Debug, Default)]
pub struct DefinitionRegistry {
    templates: Vec<TemplateDefinition>,
}

impl DefinitionRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register_template(
        &mut self,
        template: TemplateId,
        signature: TemplateSignature,
    ) -> DefinitionId {
        let definition = DefinitionId(self.templates.len() as u32);
        self.templates.push(TemplateDefinition {
            template,
            signature,
        });
        definition
    }

    pub fn template(
        &self,
        definition: DefinitionId,
    ) -> Result<TemplateDefinition, DefinitionError> {
        self.templates
            .get(definition.0 as usize)
            .copied()
            .ok_or(DefinitionError(definition))
    }

    pub fn len(&self) -> usize {
        self.templates.len()
    }

    pub fn is_empty(&self) -> bool {
        self.templates.is_empty()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DefinitionError(DefinitionId);

impl Display for DefinitionError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "unknown template definition {}", self.0.index())
    }
}

impl Error for DefinitionError {}

/// Inputs that can change the generated template artifact.
///
/// Runtime scan values are intentionally absent. A scan update reuses this
/// artifact and is applied by the RTMQ linker. Structural parameters, hardware
/// maps, and calibration snapshots remain explicit invalidation boundaries.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct SpecializationKey {
    definition: DefinitionId,
    structural_digest: u64,
    hardware_map_digest: u64,
    calibration_digest: u64,
}

impl SpecializationKey {
    pub const fn new(
        definition: DefinitionId,
        structural_digest: u64,
        hardware_map_digest: u64,
        calibration_digest: u64,
    ) -> Self {
        Self {
            definition,
            structural_digest,
            hardware_map_digest,
            calibration_digest,
        }
    }

    pub const fn definition(self) -> DefinitionId {
        self.definition
    }
}

/// Demand-driven template specialization cache.
///
/// Artifacts are reference counted so callers can retain compiled templates
/// while the session grows. A failed compile is not cached.
#[derive(Debug)]
pub struct SpecializationCache<Artifact> {
    artifacts: HashMap<SpecializationKey, Arc<Artifact>>,
}

impl<Artifact> Default for SpecializationCache<Artifact> {
    fn default() -> Self {
        Self {
            artifacts: HashMap::new(),
        }
    }
}

impl<Artifact> SpecializationCache<Artifact> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get(&self, key: SpecializationKey) -> Option<Arc<Artifact>> {
        self.artifacts.get(&key).cloned()
    }

    pub fn get_or_try_compile<CompileError>(
        &mut self,
        key: SpecializationKey,
        compile: impl FnOnce() -> Result<Artifact, CompileError>,
    ) -> Result<Arc<Artifact>, CompileError> {
        if let Some(artifact) = self.artifacts.get(&key) {
            return Ok(Arc::clone(artifact));
        }
        let artifact = Arc::new(compile()?);
        self.artifacts.insert(key, Arc::clone(&artifact));
        Ok(artifact)
    }

    pub fn len(&self) -> usize {
        self.artifacts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.artifacts.is_empty()
    }
}
