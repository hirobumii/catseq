//! Exact registered-source frontend for CatSeq kernel definitions.

mod compute_validation;
mod registered_analysis;
mod registered_modules;
mod source_hir;
mod typed;

pub use compute_validation::{
    ComputeSourceProvenance, ComputeType, ComputeTypedUnit, ComputeUnitStore, ComputeValidation,
    ComputeValidationError, FrozenComputeSourceUnit, ValidatedComputeInterface,
    validate_compute_roots,
};
pub use registered_analysis::{
    RegisteredAnalysisError, RegisteredEntryAnalysis, RegisteredRequestResolver,
    RequestResolutionError, ResolvedExternalRead, ResolvedSourceCallable, analyze_registered_entry,
};
pub use registered_modules::{
    BuiltinNameBindingInput, DefinitionNameBindingInput, DefinitionRegistrationInput,
    ModuleRegistrationInput, RegisteredBuiltin, RegisteredDefinition, RegisteredDefinitionRole,
    RegisteredKernelModules, RegisteredModule, RegistrationError, RegistrationInput,
    register_kernel_modules,
};
pub use source_hir::{
    ComputeCallReference, DefinitionCallEdge, DependencyRole, ExternalRead, MorphismComposition,
    ResolvedCallTarget, SemanticFact, SourceAnchor, SourceHirKind, SourceHirNode, SourceIntrinsic,
    SourceLiteral, SourceType, TopologyEffect, TypedSourceHir, ValueAvailability,
};
pub use typed::{TypeSignature, TypedCheckReport, TypedDefinition, TypedParameter};
