//! Request-local registration of exact Python definitions with parsed NAC3 source.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use nac3ast::{ExcepthandlerKind, Location, Stmt, StmtKind};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegisteredDefinitionRole {
    Kernel,
    MorphismDefinition,
    Atomic,
}

#[derive(Clone, Debug)]
pub struct ModuleRegistrationInput {
    pub id: usize,
    pub import_name: String,
    pub file_name: String,
    pub source: Arc<str>,
}

#[derive(Clone, Debug)]
pub struct DefinitionRegistrationInput {
    pub id: usize,
    pub module_id: usize,
    pub qualified_name: String,
    pub source_start_line: usize,
    pub role: RegisteredDefinitionRole,
    pub atomic_symbol: Option<String>,
}

#[derive(Clone, Debug)]
pub struct RegistrationInput {
    pub modules: Vec<ModuleRegistrationInput>,
    pub definitions: Vec<DefinitionRegistrationInput>,
    pub entry_definition_id: usize,
}

#[derive(Clone, Debug)]
pub struct RegisteredModule {
    id: usize,
    import_name: String,
    file_name: String,
    source: Arc<str>,
    suite: Vec<Stmt>,
    indexed_definitions: Vec<IndexedDefinition>,
}

impl RegisteredModule {
    pub const fn id(&self) -> usize {
        self.id
    }

    pub fn import_name(&self) -> &str {
        &self.import_name
    }

    pub fn file_name(&self) -> &str {
        &self.file_name
    }

    pub const fn source(&self) -> &Arc<str> {
        &self.source
    }

    pub fn suite(&self) -> &[Stmt] {
        &self.suite
    }
}

#[derive(Clone, Debug)]
pub struct RegisteredDefinition {
    id: usize,
    module_id: usize,
    qualified_name: String,
    role: RegisteredDefinitionRole,
    atomic_symbol: Option<String>,
    location: Location,
    ast_definition_index: usize,
}

impl RegisteredDefinition {
    pub const fn id(&self) -> usize {
        self.id
    }

    pub const fn module_id(&self) -> usize {
        self.module_id
    }

    pub fn qualified_name(&self) -> &str {
        &self.qualified_name
    }

    pub const fn role(&self) -> RegisteredDefinitionRole {
        self.role
    }

    pub fn atomic_symbol(&self) -> Option<&str> {
        self.atomic_symbol.as_deref()
    }

    pub const fn location(&self) -> Location {
        self.location
    }
}

#[derive(Clone, Debug)]
pub struct RegisteredKernelModules {
    modules: Vec<RegisteredModule>,
    definitions: Vec<RegisteredDefinition>,
    entry_definition_id: usize,
}

impl RegisteredKernelModules {
    pub fn modules(&self) -> &[RegisteredModule] {
        &self.modules
    }

    pub fn definitions(&self) -> &[RegisteredDefinition] {
        &self.definitions
    }

    pub const fn entry_definition_id(&self) -> usize {
        self.entry_definition_id
    }

    pub fn definition(&self, id: usize) -> Option<&RegisteredDefinition> {
        self.definitions
            .iter()
            .find(|definition| definition.id == id)
    }

    pub fn definition_ast(&self, id: usize) -> Option<&Stmt> {
        let definition = self.definition(id)?;
        let module = self
            .modules
            .iter()
            .find(|module| module.id == definition.module_id)
            .expect("registered definitions always refer to retained modules");
        Some(&module.indexed_definitions[definition.ast_definition_index].statement)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistrationError {
    Parse {
        module: String,
        file_name: String,
        message: String,
    },
    DefinitionModuleMissing {
        definition: String,
        module_id: usize,
    },
    DefinitionNotFound {
        definition: String,
        module: String,
        file_name: String,
        source_start_line: usize,
        source_start_column: usize,
    },
    DefinitionAmbiguous {
        definition: String,
        module: String,
        file_name: String,
        source_start_line: usize,
        source_start_column: usize,
    },
    EntryNotRegistered {
        definition_id: usize,
    },
}

impl Display for RegistrationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Parse {
                module,
                file_name,
                message,
            } => write!(
                formatter,
                "cannot parse registered module {module} at {file_name}: {message}"
            ),
            Self::DefinitionModuleMissing {
                definition,
                module_id,
            } => write!(
                formatter,
                "registered definition {definition} refers to missing module id {module_id}"
            ),
            Self::DefinitionNotFound {
                definition,
                module,
                file_name,
                source_start_line,
                source_start_column,
            } => write!(
                formatter,
                "registered definition {definition} in module {module} has no matching source definition at {file_name}:{source_start_line}:{source_start_column}"
            ),
            Self::DefinitionAmbiguous {
                definition,
                module,
                file_name,
                source_start_line,
                source_start_column,
            } => write!(
                formatter,
                "registered definition {definition} in module {module} has multiple matching source definitions at {file_name}:{source_start_line}:{source_start_column}"
            ),
            Self::EntryNotRegistered { definition_id } => write!(
                formatter,
                "registered Kernel entry id {definition_id} is absent from the definition catalog"
            ),
        }
    }
}

impl Error for RegistrationError {}

#[derive(Clone, Debug)]
struct IndexedDefinition {
    qualified_name: String,
    source_start_line: usize,
    statement: Stmt,
}

pub fn register_kernel_modules(
    input: RegistrationInput,
) -> Result<RegisteredKernelModules, RegistrationError> {
    let mut modules = Vec::with_capacity(input.modules.len());
    for module in input.modules {
        let suite = nac3parser::parser::parse_program(
            &module.source,
            nac3ast::FileName::from(module.file_name.clone()),
        )
        .map_err(|error| RegistrationError::Parse {
            module: module.import_name.clone(),
            file_name: module.file_name.clone(),
            message: error.to_string(),
        })?;
        let mut indexed_definitions = Vec::new();
        index_definitions(&suite, &mut Vec::new(), &mut indexed_definitions);
        modules.push(RegisteredModule {
            id: module.id,
            import_name: module.import_name,
            file_name: module.file_name,
            source: module.source,
            suite,
            indexed_definitions,
        });
    }

    let mut definitions = Vec::with_capacity(input.definitions.len());
    for definition in input.definitions {
        let module = modules
            .iter()
            .find(|module| module.id == definition.module_id)
            .ok_or_else(|| RegistrationError::DefinitionModuleMissing {
                definition: definition.qualified_name.clone(),
                module_id: definition.module_id,
            })?;
        let (ast_definition_index, indexed) = associate_definition(module, &definition)?;
        definitions.push(RegisteredDefinition {
            id: definition.id,
            module_id: definition.module_id,
            qualified_name: definition.qualified_name,
            role: definition.role,
            atomic_symbol: definition.atomic_symbol,
            location: indexed.statement.location,
            ast_definition_index,
        });
    }

    if !definitions
        .iter()
        .any(|definition| definition.id == input.entry_definition_id)
    {
        return Err(RegistrationError::EntryNotRegistered {
            definition_id: input.entry_definition_id,
        });
    }

    Ok(RegisteredKernelModules {
        modules,
        definitions,
        entry_definition_id: input.entry_definition_id,
    })
}

fn associate_definition<'a>(
    module: &'a RegisteredModule,
    definition: &DefinitionRegistrationInput,
) -> Result<(usize, &'a IndexedDefinition), RegistrationError> {
    let mut matches = module
        .indexed_definitions
        .iter()
        .enumerate()
        .filter(|(_, candidate)| {
            candidate.qualified_name == definition.qualified_name
                && candidate.source_start_line == definition.source_start_line
        });
    let source_start_column = module
        .source
        .lines()
        .nth(definition.source_start_line.saturating_sub(1))
        .and_then(|line| {
            line.char_indices()
                .find(|(_, character)| !character.is_whitespace())
                .map(|(column, _)| column + 1)
        })
        .unwrap_or(1);
    let Some(first) = matches.next() else {
        return Err(RegistrationError::DefinitionNotFound {
            definition: definition.qualified_name.clone(),
            module: module.import_name.clone(),
            file_name: module.file_name.clone(),
            source_start_line: definition.source_start_line,
            source_start_column,
        });
    };
    if matches.next().is_some() {
        return Err(RegistrationError::DefinitionAmbiguous {
            definition: definition.qualified_name.clone(),
            module: module.import_name.clone(),
            file_name: module.file_name.clone(),
            source_start_line: definition.source_start_line,
            source_start_column,
        });
    }
    Ok(first)
}

fn index_definitions(
    suite: &[Stmt],
    lexical_path: &mut Vec<String>,
    indexed: &mut Vec<IndexedDefinition>,
) {
    for statement in suite {
        match &statement.node {
            StmtKind::FunctionDef {
                name,
                body,
                decorator_list,
                ..
            }
            | StmtKind::AsyncFunctionDef {
                name,
                body,
                decorator_list,
                ..
            } => {
                lexical_path.push(name.to_string());
                indexed.push(IndexedDefinition {
                    qualified_name: lexical_path.join("."),
                    source_start_line: decorator_list
                        .first()
                        .map_or(statement.location.row, |decorator| decorator.location.row),
                    statement: statement.clone(),
                });
                lexical_path.push("<locals>".to_owned());
                index_definitions(body, lexical_path, indexed);
                lexical_path.pop();
                lexical_path.pop();
            }
            StmtKind::ClassDef { name, body, .. } => {
                lexical_path.push(name.to_string());
                index_definitions(body, lexical_path, indexed);
                lexical_path.pop();
            }
            StmtKind::For { body, orelse, .. }
            | StmtKind::AsyncFor { body, orelse, .. }
            | StmtKind::While { body, orelse, .. }
            | StmtKind::If { body, orelse, .. } => {
                index_definitions(body, lexical_path, indexed);
                index_definitions(orelse, lexical_path, indexed);
            }
            StmtKind::With { body, .. } | StmtKind::AsyncWith { body, .. } => {
                index_definitions(body, lexical_path, indexed);
            }
            StmtKind::Try {
                body,
                handlers,
                orelse,
                finalbody,
                ..
            } => {
                index_definitions(body, lexical_path, indexed);
                for handler in handlers {
                    let ExcepthandlerKind::ExceptHandler { body, .. } = &handler.node;
                    index_definitions(body, lexical_path, indexed);
                }
                index_definitions(orelse, lexical_path, indexed);
                index_definitions(finalbody, lexical_path, indexed);
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ambiguous_association_fails_with_source_provenance() {
        let source = Arc::<str>::from("class Owner:\n    def helper(self):\n        return None\n");
        let suite = nac3parser::parser::parse_program(
            &source,
            nac3ast::FileName::from("/project/helpers.py".to_owned()),
        )
        .expect("test source should parse");
        let mut indexed_definitions = Vec::new();
        index_definitions(&suite, &mut Vec::new(), &mut indexed_definitions);
        let indexed = indexed_definitions
            .pop()
            .expect("class method should be indexed");
        let module = RegisteredModule {
            id: 0,
            import_name: "helpers".to_owned(),
            file_name: "/project/helpers.py".to_owned(),
            source,
            suite,
            indexed_definitions: vec![indexed.clone(), indexed],
        };
        let definition = DefinitionRegistrationInput {
            id: 0,
            module_id: 0,
            qualified_name: "Owner.helper".to_owned(),
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
            atomic_symbol: None,
        };

        assert!(matches!(
            associate_definition(&module, &definition),
            Err(RegistrationError::DefinitionAmbiguous {
                definition,
                module,
                file_name,
                source_start_line: 2,
                source_start_column: 5,
            }) if definition == "Owner.helper"
                && module == "helpers"
                && file_name == "/project/helpers.py"
        ));
    }
}
