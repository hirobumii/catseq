//! Incremental source frontend session.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use catseq_core::arena::{ArenaError, ArenaStore, SegmentKind, TemplateId};

use crate::{
    ArenaLoweringError, FrontendError, LoweringError, ResolvedPath, ScanSlotUse,
    SourceArenaProgram, SourceModule, ValidationError, lower_sequence_hir,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CacheStatus {
    Compiled,
    SourceReused,
    HirReused,
}

#[derive(Clone, Debug)]
pub struct CompiledSourceSequence {
    entry: String,
    program: SourceArenaProgram,
    template: TemplateId,
    scan_slots: Vec<ScanSlotUse>,
    resolved_paths: Vec<ResolvedPath>,
    call_targets: Vec<ResolvedPath>,
}

impl CompiledSourceSequence {
    pub fn entry(&self) -> &str {
        &self.entry
    }

    pub fn program(&self) -> &SourceArenaProgram {
        &self.program
    }

    pub const fn template(&self) -> TemplateId {
        self.template
    }

    pub fn scan_slots(&self) -> &[ScanSlotUse] {
        &self.scan_slots
    }

    pub fn call_targets(&self) -> &[ResolvedPath] {
        &self.call_targets
    }

    pub fn resolved_paths(&self) -> &[ResolvedPath] {
        &self.resolved_paths
    }
}

#[derive(Clone, Debug)]
pub struct SourceCompileOutcome {
    status: CacheStatus,
    artifact: Arc<CompiledSourceSequence>,
}

impl SourceCompileOutcome {
    pub const fn status(&self) -> CacheStatus {
        self.status
    }

    pub fn artifact(&self) -> &Arc<CompiledSourceSequence> {
        &self.artifact
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct DefinitionCacheKey {
    file_name: String,
    entry: String,
}

#[derive(Clone, Debug)]
struct CachedSequence {
    source: String,
    artifact: Arc<CompiledSourceSequence>,
}

#[derive(Clone, Debug)]
struct CachedModule {
    source: String,
    module: Arc<SourceModule>,
}

/// A long-lived compiler session that owns one shared arena and source-HIR
/// frontend artifacts.
///
/// Runtime scan values are deliberately absent from `compile_source`; they are
/// bound later by the RTMQ linker and therefore cannot invalidate this cache.
#[derive(Debug, Default)]
pub struct SourceCompilerSession {
    arena: ArenaStore,
    modules: HashMap<String, CachedModule>,
    cache: HashMap<DefinitionCacheKey, CachedSequence>,
}

impl SourceCompilerSession {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn arena(&self) -> &ArenaStore {
        &self.arena
    }

    pub fn compile_source(
        &mut self,
        file_name: &str,
        source: &str,
        entry: &str,
    ) -> Result<SourceCompileOutcome, SourceCompileError> {
        let key = DefinitionCacheKey {
            file_name: file_name.to_owned(),
            entry: entry.to_owned(),
        };
        if let Some(cached) = self.cache.get(&key) {
            if cached.source == source {
                return Ok(SourceCompileOutcome {
                    status: CacheStatus::SourceReused,
                    artifact: Arc::clone(&cached.artifact),
                });
            }
        }

        let module = self.source_module(file_name, source)?;
        let hir = Arc::new(module.lower_sequence(entry)?);
        module.validate_sequence_hir(&hir)?;
        let scan_slots = module.scan_slots(&hir);
        let resolved_paths = module.resolved_paths(&hir);
        let call_targets = module.resolved_call_targets(&hir);
        if let Some(cached) = self.cache.get_mut(&key) {
            let hir_matches = cached.artifact.program.hir() == hir.as_ref()
                && cached.artifact.scan_slots == scan_slots
                && cached.artifact.resolved_paths == resolved_paths
                && cached.artifact.call_targets == call_targets;
            if hir_matches {
                cached.source = source.to_owned();
                return Ok(SourceCompileOutcome {
                    status: CacheStatus::HirReused,
                    artifact: Arc::clone(&cached.artifact),
                });
            }
        }

        let segment = self.arena.create_segment(SegmentKind::Template);
        let program = lower_sequence_hir(hir, &self.arena, segment)?;
        let template = self.arena.publish_template(program.root(), 0)?;
        let artifact = Arc::new(CompiledSourceSequence {
            entry: entry.to_owned(),
            program,
            template,
            scan_slots,
            resolved_paths,
            call_targets,
        });
        self.cache.insert(
            key,
            CachedSequence {
                source: source.to_owned(),
                artifact: Arc::clone(&artifact),
            },
        );
        Ok(SourceCompileOutcome {
            status: CacheStatus::Compiled,
            artifact,
        })
    }

    pub fn cached_artifact_count(&self) -> usize {
        self.cache.len()
    }

    fn source_module(
        &mut self,
        file_name: &str,
        source: &str,
    ) -> Result<Arc<SourceModule>, FrontendError> {
        if let Some(cached) = self.modules.get(file_name) {
            if cached.source == source {
                return Ok(Arc::clone(&cached.module));
            }
        }
        let module = Arc::new(SourceModule::parse(file_name, source)?);
        self.modules.insert(
            file_name.to_owned(),
            CachedModule {
                source: source.to_owned(),
                module: Arc::clone(&module),
            },
        );
        Ok(module)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceCompileError {
    Parse(FrontendError),
    Hir(LoweringError),
    Validation(ValidationError),
    ArenaLowering(ArenaLoweringError),
    Arena(ArenaError),
}

impl Display for SourceCompileError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Parse(error) => Display::fmt(error, formatter),
            Self::Hir(error) => Display::fmt(error, formatter),
            Self::Validation(error) => Display::fmt(error, formatter),
            Self::ArenaLowering(error) => Display::fmt(error, formatter),
            Self::Arena(error) => Display::fmt(error, formatter),
        }
    }
}

impl Error for SourceCompileError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Parse(error) => Some(error),
            Self::Hir(error) => Some(error),
            Self::Validation(error) => Some(error),
            Self::ArenaLowering(error) => Some(error),
            Self::Arena(error) => Some(error),
        }
    }
}

impl From<FrontendError> for SourceCompileError {
    fn from(error: FrontendError) -> Self {
        Self::Parse(error)
    }
}

impl From<LoweringError> for SourceCompileError {
    fn from(error: LoweringError) -> Self {
        Self::Hir(error)
    }
}

impl From<ValidationError> for SourceCompileError {
    fn from(error: ValidationError) -> Self {
        Self::Validation(error)
    }
}

impl From<ArenaLoweringError> for SourceCompileError {
    fn from(error: ArenaLoweringError) -> Self {
        Self::ArenaLowering(error)
    }
}

impl From<ArenaError> for SourceCompileError {
    fn from(error: ArenaError) -> Self {
        Self::Arena(error)
    }
}
