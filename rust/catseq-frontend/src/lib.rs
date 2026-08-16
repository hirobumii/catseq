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
    RequestResolutionError, ResolvedExternalRead, analyze_registered_entry,
};
pub use registered_modules::{
    BuiltinNameBindingInput, DefinitionNameBindingInput, DefinitionRegistrationInput,
    ModuleRegistrationInput, RegisteredBuiltin, RegisteredDefinition, RegisteredDefinitionRole,
    RegisteredKernelModules, RegisteredModule, RegistrationError, RegistrationInput,
    register_kernel_modules,
};
pub use source_hir::{
    CallArgumentBinding, CallArgumentOrigin, ComputeCallReference, DefinitionCallEdge,
    DependencyRole, ExternalRead, MorphismComposition, ResolvedCallTarget, SemanticFact,
    SourceAnchor, SourceBinding, SourceHirKind, SourceHirNode, SourceIntrinsic, SourceLiteral,
    TopologyEffect, TypedSourceHir, ValueAvailability, ValueType, ValueTypeConstructor,
};
pub use typed::{ParameterKind, TypeSignature, TypedCheckReport, TypedDefinition, TypedParameter};
