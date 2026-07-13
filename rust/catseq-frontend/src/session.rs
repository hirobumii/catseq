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
    resolution: ResolutionSnapshot,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ResolutionSnapshot {
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
        &self.resolution.scan_slots
    }

    pub fn call_targets(&self) -> &[ResolvedPath] {
        &self.resolution.call_targets
    }

    pub fn resolved_paths(&self) -> &[ResolvedPath] {
        &self.resolution.resolved_paths
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
        if let Some(reused) = self.reuse_exact_source(file_name, source, entry) {
            return Ok(reused);
        }

        let module = self.source_module(file_name, source)?;
        self.compile_module_entry(&module, entry)
    }

    /// Compile an entry from an already parsed module, sharing this session's
    /// arena and caches. This is the multi-entry `catseqc` path.
    pub fn compile_module_entry(
        &mut self,
        module: &SourceModule,
        entry: &str,
    ) -> Result<SourceCompileOutcome, SourceCompileError> {
        let file_name = module.file_name();
        let source = &module.source;
        if let Some(reused) = self.reuse_exact_source(file_name, source, entry) {
            return Ok(reused);
        }
        let key = DefinitionCacheKey {
            file_name: file_name.to_owned(),
            entry: entry.to_owned(),
        };
        let hir = Arc::new(module.lower_sequence(entry)?);
        module.validate_sequence_hir(&hir)?;
        let resolution = ResolutionSnapshot {
            scan_slots: module.scan_slots(&hir),
            resolved_paths: module.resolved_paths(&hir),
            call_targets: module.resolved_call_targets(&hir),
        };
        if let Some(cached) = self.cache.get_mut(&key) {
            let hir_matches = cached
                .artifact
                .program
                .hir()
                .structurally_eq_ignoring_spans(&hir)
                && cached.artifact.resolution == resolution;
            if hir_matches {
                let program = cached.artifact.program.rebind_hir(hir);
                let artifact = Arc::new(CompiledSourceSequence {
                    entry: entry.to_owned(),
                    program,
                    template: cached.artifact.template,
                    resolution,
                });
                cached.source = source.to_owned();
                cached.artifact = Arc::clone(&artifact);
                return Ok(SourceCompileOutcome {
                    status: CacheStatus::HirReused,
                    artifact,
                });
            }
        }

        let segment = self.arena.create_segment(SegmentKind::Template);
        let program = lower_sequence_hir(hir, &self.arena, segment)?;
        let template = self.arena.publish_template_with_owner(
            program.root(),
            0,
            Arc::clone(program.hir_arc()),
        )?;
        let artifact = Arc::new(CompiledSourceSequence {
            entry: entry.to_owned(),
            program,
            template,
            resolution,
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

    fn reuse_exact_source(
        &self,
        file_name: &str,
        source: &str,
        entry: &str,
    ) -> Option<SourceCompileOutcome> {
        let key = DefinitionCacheKey {
            file_name: file_name.to_owned(),
            entry: entry.to_owned(),
        };
        let cached = self.cache.get(&key)?;
        (cached.source == source).then(|| SourceCompileOutcome {
            status: CacheStatus::SourceReused,
            artifact: Arc::clone(&cached.artifact),
        })
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
