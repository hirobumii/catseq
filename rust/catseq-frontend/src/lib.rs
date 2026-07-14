//! Restricted Python source frontend for CatSeq sequence definitions.
//!
//! Parsing accepts a complete Python file, but CatSeq semantics are applied
//! only to functions explicitly marked with `@arena_build`. This lets an
//! experiment module keep host-side setup and analysis code without granting
//! that code execution privileges inside the sequence compiler.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::ops::Range;

use tree_sitter::{Node, Parser, Point, Tree};

mod arena_lowering;
mod hir;
mod incremental;
mod intrinsics;
mod morphism_lowering;
mod names;
mod session;
mod source_hir;
mod typed;
mod validate;

pub use arena_lowering::{ArenaLoweringError, SourceArenaProgram, lower_sequence_hir};
pub use hir::{
    BinaryOperator, CompositionKind, ExpressionId, HirExpression, HirKind, KeywordArgument,
    Literal, LoweringError, SequenceHir, SourceSpan, UnaryOperator,
};
pub use incremental::{
    IncrementalCheckError, check_typed_bundle_entry_incremental,
    check_typed_bundle_entry_incremental_with_loader, check_typed_bundle_entry_summary_incremental,
    check_typed_bundle_entry_summary_incremental_with_loader, check_typed_entry_incremental,
    check_typed_entry_summary_incremental,
};
pub use morphism_lowering::{
    MorphismLoweringError, lower_typed_report_to_native_arenas,
    specialize_typed_report_to_native_arenas,
};
pub use names::{PathRoot, ResolvedPath, ScanSlotUse};
pub use session::{
    CacheStatus, CompiledSourceSequence, SourceCompileError, SourceCompileOutcome,
    SourceCompilerSession,
};
pub use source_hir::{
    ComparisonOperation, DependencyRole, MorphismComposition, SemanticFact, SourceAnchor,
    SourceHirKind, SourceHirNode, SourceLiteral, TypedSourceHir, ValueAvailability, ValueOperation,
};
pub use typed::{
    IncrementalStats, SourceType, TypeSignature, TypedCheckError, TypedCheckReport,
    TypedCheckSummary, TypedDefinition, TypedParameter, check_typed_bundle_entry,
    check_typed_bundle_entry_with_loader, check_typed_entry,
};
pub use validate::{TopologyContext, ValidationError};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceEntry {
    qualified_name: String,
    source: String,
    byte_range: Range<usize>,
}

impl SequenceEntry {
    pub fn qualified_name(&self) -> &str {
        &self.qualified_name
    }

    pub fn source(&self) -> &str {
        &self.source
    }

    pub fn byte_range(&self) -> Range<usize> {
        self.byte_range.clone()
    }
}

#[derive(Clone, Debug)]
pub struct SourceModule {
    file_name: String,
    imports: HashMap<String, String>,
    sequence_entries: Vec<SequenceEntry>,
    source: String,
    tree: Tree,
}

impl SourceModule {
    pub fn parse(file_name: impl Into<String>, source: &str) -> Result<Self, FrontendError> {
        let file_name = file_name.into();
        let mut parser = Parser::new();
        parser
            .set_language(&tree_sitter_python::LANGUAGE.into())
            .map_err(|error| FrontendError::ParserInitialization(error.to_string()))?;
        let tree = parser
            .parse(source, None)
            .ok_or(FrontendError::ParserCancelled)?;
        let root = tree.root_node();
        if root.has_error() {
            let point = first_syntax_error(root).unwrap_or(root.start_position());
            return Err(FrontendError::Syntax {
                file_name,
                line: point.row + 1,
                column: point.column + 1,
            });
        }

        let imports = names::discover_imports(root, source);
        let sequence_entries = discover_sequence_entries(root, source);
        Ok(Self {
            file_name,
            imports,
            sequence_entries,
            source: source.to_owned(),
            tree,
        })
    }

    pub fn file_name(&self) -> &str {
        &self.file_name
    }

    pub fn sequence_entries(&self) -> &[SequenceEntry] {
        &self.sequence_entries
    }

    pub fn sequence_entry(&self, qualified_name: &str) -> Option<&SequenceEntry> {
        self.sequence_entries
            .iter()
            .find(|entry| entry.qualified_name == qualified_name)
    }

    pub fn lower_sequence(&self, qualified_name: &str) -> Result<SequenceHir, LoweringError> {
        let entry =
            self.sequence_entry(qualified_name)
                .ok_or_else(|| LoweringError::EntryNotFound {
                    file_name: self.file_name.clone(),
                    entry: qualified_name.to_owned(),
                })?;
        hir::lower_entry(&self.file_name, entry, &self.tree, &self.source)
    }

    pub fn resolved_paths(&self, hir: &SequenceHir) -> Vec<ResolvedPath> {
        let reachable = hir.reachable_mask();
        hir.expressions()
            .iter()
            .enumerate()
            .filter_map(|(index, _expression)| {
                reachable[index].then(|| {
                    names::resolve_path(&self.imports, hir, ExpressionId::from_index(index as u32))
                })?
            })
            .collect()
    }

    pub fn resolved_call_targets(&self, hir: &SequenceHir) -> Vec<ResolvedPath> {
        let reachable = hir.reachable_mask();
        hir.expressions()
            .iter()
            .enumerate()
            .filter_map(|(index, expression)| match expression.kind() {
                _ if !reachable[index] => None,
                HirKind::Call { function, .. } => {
                    names::resolve_path(&self.imports, hir, *function)
                }
                _ => None,
            })
            .collect()
    }

    pub fn scan_slots(&self, hir: &SequenceHir) -> Vec<ScanSlotUse> {
        names::discover_scan_slots(&self.imports, hir)
    }

    pub fn validate_sequence_hir(&self, hir: &SequenceHir) -> Result<(), ValidationError> {
        validate::validate_scan_topology(&self.file_name, hir, &self.scan_slots(hir))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrontendError {
    ParserInitialization(String),
    ParserCancelled,
    Syntax {
        file_name: String,
        line: usize,
        column: usize,
    },
}

impl Display for FrontendError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ParserInitialization(message) => {
                write!(formatter, "failed to initialize Python parser: {message}")
            }
            Self::ParserCancelled => formatter.write_str("Python parser was cancelled"),
            Self::Syntax {
                file_name,
                line,
                column,
            } => write!(
                formatter,
                "Python syntax error at {file_name}:{line}:{column}"
            ),
        }
    }
}

impl Error for FrontendError {}

fn first_syntax_error(root: Node<'_>) -> Option<Point> {
    let mut stack = vec![root];
    while let Some(node) = stack.pop() {
        if node.is_error() || node.is_missing() {
            return Some(node.start_position());
        }
        if !node.has_error() {
            continue;
        }
        let mut cursor = node.walk();
        stack.extend(node.children(&mut cursor));
    }
    None
}

fn discover_sequence_entries(root: Node<'_>, source: &str) -> Vec<SequenceEntry> {
    let mut entries = Vec::new();
    let mut scopes = vec![(root, Vec::<String>::new())];
    while let Some((scope_node, scope_names)) = scopes.pop() {
        let mut cursor = scope_node.walk();
        for child in scope_node.named_children(&mut cursor) {
            match child.kind() {
                "class_definition" => {
                    push_class_scope(&mut scopes, child, &scope_names, source);
                }
                "decorated_definition" => {
                    if let Some(function) = decorated_function(child) {
                        if has_arena_build_decorator(child, source) {
                            entries.push(sequence_entry(function, &scope_names, source));
                        }
                    } else if let Some(class) = decorated_class(child) {
                        push_class_scope(&mut scopes, class, &scope_names, source);
                    }
                }
                _ => {}
            }
        }
    }
    entries.sort_by_key(|entry| entry.byte_range.start);
    entries
}

fn decorated_function(node: Node<'_>) -> Option<Node<'_>> {
    let mut cursor = node.walk();
    node.named_children(&mut cursor)
        .find(|child| child.kind() == "function_definition")
}

fn decorated_class(node: Node<'_>) -> Option<Node<'_>> {
    let mut cursor = node.walk();
    node.named_children(&mut cursor)
        .find(|child| child.kind() == "class_definition")
}

fn has_arena_build_decorator(node: Node<'_>, source: &str) -> bool {
    let mut cursor = node.walk();
    node.named_children(&mut cursor)
        .filter(|child| child.kind() == "decorator")
        .filter_map(|decorator| decorator.utf8_text(source.as_bytes()).ok())
        .map(str::trim)
        .map(|decorator| decorator.strip_prefix('@').unwrap_or(decorator))
        .any(|decorator| decorator == "arena_build" || decorator.ends_with(".arena_build"))
}

fn push_class_scope<'tree>(
    scopes: &mut Vec<(Node<'tree>, Vec<String>)>,
    class: Node<'tree>,
    parent_names: &[String],
    source: &str,
) {
    let (Some(name), Some(body)) = (
        class.child_by_field_name("name"),
        class.child_by_field_name("body"),
    ) else {
        return;
    };
    let Ok(name) = name.utf8_text(source.as_bytes()) else {
        return;
    };
    let mut class_names = parent_names.to_vec();
    class_names.push(name.to_owned());
    scopes.push((body, class_names));
}

fn sequence_entry(function: Node<'_>, scope_names: &[String], source: &str) -> SequenceEntry {
    let name = function
        .child_by_field_name("name")
        .and_then(|name| name.utf8_text(source.as_bytes()).ok())
        .unwrap_or("<missing>");
    let mut qualified = scope_names.to_vec();
    qualified.push(name.to_owned());
    let byte_range = function.byte_range();
    SequenceEntry {
        qualified_name: qualified.join("."),
        source: source[byte_range.clone()].to_owned(),
        byte_range,
    }
}
