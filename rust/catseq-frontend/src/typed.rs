//! Typed declaration surface produced from NAC3's Python AST.
//!
//! This module is the first production seam of the 0.3 source frontend.  It
//! deliberately owns CatSeq types instead of leaking NAC3 AST nodes past the
//! parsing/indexing boundary.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};

use crate::intrinsics;

mod ast_util;
mod compile_attributes;
mod compile_values;
mod definition_analysis;
mod model;
mod resolution;
mod signatures;
mod validation;

use ast_util::parse_module;
use compile_attributes::{load_referenced_compile_modules, resolve_bundle_compile_attributes};
use definition_analysis::{definition_contains_call, definition_exists, find_definition};
use resolution::{
    load_source_module, locate_source_definition, module_imports, resolve_call_path,
    resolve_compile_instance_call, resolve_self_call,
};

pub(crate) use model::IncrementalStatsSnapshot;
pub use model::{
    IncrementalStats, SourceType, TypeSignature, TypedCheckError, TypedCheckReport,
    TypedCheckSummary, TypedDefinition, TypedParameter,
};

pub fn check_typed_entry(
    file_name: &str,
    source: &str,
    requested_entry: &str,
) -> Result<TypedCheckReport, TypedCheckError> {
    let modules = BTreeMap::from([(file_name.to_owned(), source.to_owned())]);
    check_typed_bundle_entry(file_name, &modules, requested_entry)
}

pub fn check_typed_bundle_entry(
    entry_module: &str,
    modules: &BTreeMap<String, String>,
    requested_entry: &str,
) -> Result<TypedCheckReport, TypedCheckError> {
    let mut loader = |module: &str| Ok(modules.get(module).cloned());
    check_typed_bundle_entry_with_loader(entry_module, requested_entry, &mut loader)
}

pub fn check_typed_bundle_entry_with_loader<F>(
    entry_module: &str,
    requested_entry: &str,
    loader: &mut F,
) -> Result<TypedCheckReport, TypedCheckError>
where
    F: FnMut(&str) -> Result<Option<String>, String>,
{
    let mut pending = VecDeque::from([(entry_module.to_owned(), requested_entry.to_owned())]);
    let mut visited = HashSet::new();
    let mut parsed = HashMap::new();
    let mut sources = HashMap::<String, String>::new();
    let mut definitions = Vec::new();

    while let Some((module_name, lexical_name)) = pending.pop_front() {
        if !visited.insert((module_name.clone(), lexical_name.clone())) {
            continue;
        }
        if !load_source_module(&module_name, &mut sources, loader)? {
            return Err(TypedCheckError::EntryNotFound {
                file_name: module_name.clone(),
                entry: lexical_name.clone(),
            });
        }
        if !parsed.contains_key(&module_name) {
            let source = &sources[&module_name];
            parsed.insert(module_name.clone(), parse_module(&module_name, source)?);
        }
        let suite = &parsed[&module_name];
        let imports = module_imports(&module_name, suite);
        let mut analysis =
            find_definition(&module_name, suite, &mut Vec::new(), &lexical_name, None)?
                .ok_or_else(|| TypedCheckError::EntryNotFound {
                    file_name: module_name.clone(),
                    entry: lexical_name.clone(),
                })?;

        if module_name != entry_module || lexical_name != requested_entry {
            analysis.definition.qualified_name = format!("{module_name}.{lexical_name}");
        }
        for source_property in analysis.property_reads {
            let property = resolve_self_call(&lexical_name, &source_property);
            let resolved = resolve_call_path(&module_name, &imports, &property);
            analysis
                .definition
                .hir
                .resolve_attribute(&source_property, &resolved);
            if let Some((target_module, target_definition)) =
                locate_source_definition(&resolved, &mut sources, loader)?
            {
                if !parsed.contains_key(&target_module) {
                    let source = &sources[&target_module];
                    parsed.insert(target_module.clone(), parse_module(&target_module, source)?);
                }
                if definition_exists(&parsed[&target_module], &target_definition) {
                    pending.push_back((target_module, target_definition));
                }
            }
        }
        for source_call in analysis.calls {
            let call = resolve_self_call(&lexical_name, &source_call.target_path);
            let resolved = resolve_call_path(&module_name, &imports, &call);
            let resolved =
                resolve_compile_instance_call(&mut sources, &mut parsed, loader, &resolved)?;
            analysis
                .definition
                .hir
                .resolve_call(&source_call.source_path, &resolved);
            if resolved == "rb1system.utils.get_end_state" {
                return Err(TypedCheckError::MigrationRequired {
                    file_name: module_name,
                    definition: lexical_name,
                    construct: "get_end_state".to_owned(),
                });
            }
            if intrinsics::is_compiler_special_form(&resolved) {
                continue;
            }
            if let Some((target_module, target_definition)) =
                locate_source_definition(&resolved, &mut sources, loader)?
            {
                if !parsed.contains_key(&target_module) {
                    let source = &sources[&target_module];
                    parsed.insert(target_module.clone(), parse_module(&target_module, source)?);
                }
                if definition_contains_call(
                    &parsed[&target_module],
                    &target_definition,
                    "oasm_black_box",
                ) {
                    analysis
                        .definition
                        .hir
                        .resolve_opaque_atomic_call(&source_call.source_path, &resolved);
                    continue;
                }
                if definition_exists(&parsed[&target_module], &target_definition) {
                    pending.push_back((target_module, target_definition));
                    continue;
                }
            }
            if intrinsics::is_registered(&resolved) {
                continue;
            }
            let anchor = analysis
                .definition
                .hir
                .call_anchor(&source_call.source_path)
                .expect("a collected call must have a Source HIR node");
            return Err(TypedCheckError::ReachableHostCall {
                file_name: module_name,
                definition: lexical_name,
                target: resolved,
                line: anchor.line(),
                column: anchor.column(),
            });
        }
        definitions.push(analysis.definition);
    }

    load_referenced_compile_modules(&definitions, &mut sources, &mut parsed, loader)?;
    resolve_bundle_compile_attributes(&parsed, &mut definitions);

    for _ in 0..=definitions.len() {
        let return_types: HashMap<_, _> = definitions
            .iter()
            .map(|definition| {
                (
                    format!("{}.{}", definition.module, definition.hir.definition()),
                    definition.signature.return_type.clone(),
                )
            })
            .collect();
        let mut changed = false;
        for definition in &mut definitions {
            definition.hir.apply_definition_signatures(&return_types);
            if !definition.return_type_is_explicit
                && let Some(inferred) = definition.hir.inferred_return_type()
                && definition.signature.return_type != inferred
            {
                definition.signature.return_type = inferred;
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    for definition in &definitions {
        if !definition.return_type_is_explicit {
            continue;
        }
        if let Some((anchor, found)) = definition
            .hir
            .first_return_type_mismatch(definition.signature.return_type())
        {
            return Err(TypedCheckError::TypeMismatch {
                file_name: definition.module.clone(),
                definition: definition.qualified_name.clone(),
                expected: Box::new(definition.signature.return_type().clone()),
                found: Box::new(found.clone()),
                line: anchor.line(),
                column: anchor.column(),
            });
        }
    }
    let executed = parsed.len() as u64 + definitions.len() as u64;
    let mut queried_modules: Vec<_> = parsed.into_keys().collect();
    queried_modules.sort();
    Ok(TypedCheckReport {
        entry: requested_entry.to_owned(),
        incremental: IncrementalStats::new(executed, 0),
        definitions,
        diagnostics: Vec::new(),
        queried_modules,
    })
}
