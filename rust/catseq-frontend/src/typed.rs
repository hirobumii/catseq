//! Immutable typed report for one exact registered entry request.

use serde::{Deserialize, Serialize};

use crate::registered_modules::{RegisteredDefinition, RegisteredDefinitionRole, RegisteredModule};
use crate::source_hir::{
    ComputeCallReference, DefinitionCallEdge, ExternalRead, SourceAnchor, SourceBinding,
    SourceLiteral, TypedSourceHir, ValueType,
};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ParameterKind {
    PositionalOnly,
    PositionalOrKeyword,
    KeywordOnly,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypedParameter {
    name: String,
    binding: SourceBinding,
    kind: ParameterKind,
    default: Option<SourceLiteral>,
}

impl TypedParameter {
    pub(crate) fn new(
        name: String,
        binding: SourceBinding,
        kind: ParameterKind,
        default: Option<SourceLiteral>,
    ) -> Self {
        Self {
            name,
            binding,
            kind,
            default,
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub const fn binding(&self) -> &SourceBinding {
        &self.binding
    }

    pub const fn value_type(&self) -> Option<&ValueType> {
        self.binding.value_type()
    }

    pub const fn kind(&self) -> ParameterKind {
        self.kind
    }

    pub const fn default(&self) -> Option<&SourceLiteral> {
        self.default.as_ref()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypeSignature {
    parameters: Vec<TypedParameter>,
    return_type: ValueType,
}

impl TypeSignature {
    pub(crate) fn new(parameters: Vec<TypedParameter>, return_type: ValueType) -> Self {
        Self {
            parameters,
            return_type,
        }
    }

    pub fn parameters(&self) -> &[TypedParameter] {
        &self.parameters
    }

    pub const fn return_type(&self) -> &ValueType {
        &self.return_type
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TypedDefinition {
    definition_id: usize,
    role: RegisteredDefinitionRole,
    module: String,
    qualified_name: String,
    atomic_symbol: Option<String>,
    anchor: SourceAnchor,
    signature: TypeSignature,
    hir: TypedSourceHir,
}

impl TypedDefinition {
    pub(crate) fn from_registered(
        definition: &RegisteredDefinition,
        module: &RegisteredModule,
        signature: TypeSignature,
        hir: TypedSourceHir,
    ) -> Self {
        let location = definition.location();
        Self {
            definition_id: definition.id(),
            role: definition.role(),
            module: module.import_name().to_owned(),
            qualified_name: definition.qualified_name().to_owned(),
            atomic_symbol: definition.atomic_symbol().map(str::to_owned),
            anchor: SourceAnchor::new(
                module.import_name(),
                module.file_name(),
                location.row,
                location.column,
            ),
            signature,
            hir,
        }
    }

    pub const fn definition_id(&self) -> usize {
        self.definition_id
    }

    pub const fn role(&self) -> RegisteredDefinitionRole {
        self.role
    }

    pub fn module(&self) -> &str {
        &self.module
    }

    pub fn qualified_name(&self) -> &str {
        &self.qualified_name
    }

    pub fn atomic_symbol(&self) -> Option<&str> {
        self.atomic_symbol.as_deref()
    }

    pub const fn anchor(&self) -> &SourceAnchor {
        &self.anchor
    }

    pub const fn signature(&self) -> &TypeSignature {
        &self.signature
    }

    pub const fn hir(&self) -> &TypedSourceHir {
        &self.hir
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedCheckReport {
    entry_definition_id: usize,
    entry: String,
    definitions: Vec<TypedDefinition>,
    call_edges: Vec<DefinitionCallEdge>,
    external_reads: Vec<ExternalRead>,
    compute_calls: Vec<ComputeCallReference>,
    queried_modules: Vec<String>,
}

impl TypedCheckReport {
    pub(crate) fn new(
        entry_definition_id: usize,
        entry: String,
        definitions: Vec<TypedDefinition>,
        call_edges: Vec<DefinitionCallEdge>,
        external_reads: Vec<ExternalRead>,
        compute_calls: Vec<ComputeCallReference>,
        queried_modules: Vec<String>,
    ) -> Self {
        Self {
            entry_definition_id,
            entry,
            definitions,
            call_edges,
            external_reads,
            compute_calls,
            queried_modules,
        }
    }

    pub const fn entry_definition_id(&self) -> usize {
        self.entry_definition_id
    }

    pub fn entry(&self) -> &str {
        &self.entry
    }

    pub fn definitions(&self) -> &[TypedDefinition] {
        &self.definitions
    }

    pub fn call_edges(&self) -> &[DefinitionCallEdge] {
        &self.call_edges
    }

    pub fn external_reads(&self) -> &[ExternalRead] {
        &self.external_reads
    }

    pub fn compute_calls(&self) -> &[ComputeCallReference] {
        &self.compute_calls
    }

    pub fn queried_modules(&self) -> &[String] {
        &self.queried_modules
    }
}
