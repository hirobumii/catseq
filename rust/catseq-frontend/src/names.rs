//! Import and source-path resolution without loading Python modules.

use std::collections::HashMap;

use catseq_core::definitions::RuntimeValueId;
use tree_sitter::Node;

use crate::{ExpressionId, HirKind, SequenceHir};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PathRoot {
    Imported,
    Parameter,
    ModuleGlobal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedPath {
    root: PathRoot,
    qualified_name: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScanSlotUse {
    expression: ExpressionId,
    runtime_value: RuntimeValueId,
    key: String,
}

impl ScanSlotUse {
    pub const fn expression(&self) -> ExpressionId {
        self.expression
    }

    pub const fn runtime_value(&self) -> RuntimeValueId {
        self.runtime_value
    }

    pub fn key(&self) -> &str {
        &self.key
    }
}

impl ResolvedPath {
    pub const fn root(&self) -> PathRoot {
        self.root
    }

    pub fn qualified_name(&self) -> &str {
        &self.qualified_name
    }
}

pub(crate) fn discover_imports(root: Node<'_>, source: &str) -> HashMap<String, String> {
    let mut imports = HashMap::new();
    let mut cursor = root.walk();
    for statement in root.named_children(&mut cursor) {
        match statement.kind() {
            "import_statement" => discover_direct_imports(statement, source, &mut imports),
            "import_from_statement" => discover_from_imports(statement, source, &mut imports),
            _ => {}
        }
    }
    imports
}

pub(crate) fn resolve_path(
    imports: &HashMap<String, String>,
    hir: &SequenceHir,
    expression: ExpressionId,
) -> Option<ResolvedPath> {
    let mut current = expression;
    let mut segments = Vec::new();
    loop {
        match hir.expression(current).kind() {
            HirKind::Attribute { object, name } => {
                segments.push(name.as_str());
                current = *object;
            }
            HirKind::Symbol(name) => {
                segments.push(name.as_str());
                break;
            }
            _ => return None,
        }
    }
    segments.reverse();
    let first = segments.first().copied()?;
    if let Some(imported) = imports.get(first) {
        let mut qualified_name = imported.clone();
        for segment in &segments[1..] {
            qualified_name.push('.');
            qualified_name.push_str(segment);
        }
        return Some(ResolvedPath {
            root: PathRoot::Imported,
            qualified_name,
        });
    }
    let root = if hir.parameters().iter().any(|parameter| parameter == first) {
        PathRoot::Parameter
    } else {
        PathRoot::ModuleGlobal
    };
    Some(ResolvedPath {
        root,
        qualified_name: segments.join("."),
    })
}

pub(crate) fn discover_scan_slots(
    imports: &HashMap<String, String>,
    hir: &SequenceHir,
) -> Vec<ScanSlotUse> {
    let mut runtime_values = HashMap::<String, RuntimeValueId>::new();
    let mut uses = Vec::new();
    for (index, expression) in hir.expressions().iter().enumerate() {
        let HirKind::Subscript { value, index: key } = expression.kind() else {
            continue;
        };
        let Some(container) = resolve_path(imports, hir, *value) else {
            continue;
        };
        if container.root != PathRoot::Parameter || container.qualified_name != "params" {
            continue;
        }
        let Some(key) = resolve_path(imports, hir, *key) else {
            continue;
        };
        let next_index = runtime_values.len() as u32;
        let runtime_value = *runtime_values
            .entry(key.qualified_name.clone())
            .or_insert_with(|| RuntimeValueId::from_index(next_index));
        uses.push(ScanSlotUse {
            expression: ExpressionId::from_index(index as u32),
            runtime_value,
            key: key.qualified_name,
        });
    }
    uses
}

fn discover_direct_imports(
    statement: Node<'_>,
    source: &str,
    imports: &mut HashMap<String, String>,
) {
    let mut cursor = statement.walk();
    for imported in statement.named_children(&mut cursor) {
        match imported.kind() {
            "aliased_import" => {
                if let Some((qualified, alias)) = aliased_names(imported, source) {
                    imports.insert(alias.to_owned(), qualified.to_owned());
                }
            }
            "dotted_name" => {
                if let Some(qualified) = text(imported, source) {
                    let local = qualified.split('.').next().unwrap_or(qualified);
                    imports.insert(local.to_owned(), local.to_owned());
                }
            }
            _ => {}
        }
    }
}

fn discover_from_imports(statement: Node<'_>, source: &str, imports: &mut HashMap<String, String>) {
    let Some(module_node) = statement.child_by_field_name("module_name") else {
        return;
    };
    let Some(module) = text(module_node, source) else {
        return;
    };
    let module_range = module_node.byte_range();
    let mut cursor = statement.walk();
    for imported in statement.named_children(&mut cursor) {
        if imported.byte_range() == module_range {
            continue;
        }
        match imported.kind() {
            "aliased_import" => {
                if let Some((name, alias)) = aliased_names(imported, source) {
                    imports.insert(alias.to_owned(), join_qualified(module, name));
                }
            }
            "dotted_name" => {
                if let Some(name) = text(imported, source) {
                    let local = name.rsplit('.').next().unwrap_or(name);
                    imports.insert(local.to_owned(), join_qualified(module, name));
                }
            }
            _ => {}
        }
    }
}

fn aliased_names<'source>(
    node: Node<'_>,
    source: &'source str,
) -> Option<(&'source str, &'source str)> {
    let name = node.child_by_field_name("name")?;
    let alias = node.child_by_field_name("alias")?;
    Some((text(name, source)?, text(alias, source)?))
}

fn join_qualified(module: &str, name: &str) -> String {
    if module.ends_with('.') {
        format!("{module}{name}")
    } else {
        format!("{module}.{name}")
    }
}

fn text<'source>(node: Node<'_>, source: &'source str) -> Option<&'source str> {
    node.utf8_text(source.as_bytes()).ok()
}
