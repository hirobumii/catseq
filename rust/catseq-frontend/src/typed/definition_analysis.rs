//! Reachable morphism definition and call-graph analysis.

use std::collections::{HashMap, HashSet};

use nac3ast::{Expr, ExprKind, Stmt, StmtKind};

use crate::source_hir::lower_definition_hir;

use super::ast_util::{
    callable_path, expression_path, push_expression_analysis_children,
    push_statement_analysis_children,
};
use super::compile_values::{ClassFields, class_fields};
use super::model::{TypedCheckError, TypedDefinition};
use super::signatures::signature;
use super::validation::validate_restricted_statements;

pub(super) fn definition_exists(statements: &[Stmt], requested: &str) -> bool {
    let mut pending = vec![(statements, Vec::<String>::new())];
    while let Some((statements, scope)) = pending.pop() {
        for statement in statements {
            match &statement.node {
                StmtKind::ClassDef { name, body, .. } => {
                    let mut nested = scope.clone();
                    nested.push(name.to_string());
                    pending.push((body, nested));
                }
                StmtKind::FunctionDef { name, .. } => {
                    let mut qualified = scope.clone();
                    qualified.push(name.to_string());
                    if qualified.join(".") == requested {
                        return true;
                    }
                }
                _ => {}
            }
        }
    }
    false
}

pub(super) fn definition_contains_call(
    statements: &[Stmt],
    requested: &str,
    call_leaf: &str,
) -> bool {
    let mut pending = vec![(statements, Vec::<String>::new())];
    while let Some((statements, scope)) = pending.pop() {
        for statement in statements {
            match &statement.node {
                StmtKind::ClassDef { name, body, .. } => {
                    let mut nested = scope.clone();
                    nested.push(name.to_string());
                    pending.push((body, nested));
                }
                StmtKind::FunctionDef { name, body, .. } => {
                    let mut qualified = scope.clone();
                    qualified.push(name.to_string());
                    if qualified.join(".") != requested {
                        continue;
                    }
                    let mut statements: Vec<_> = body.iter().collect();
                    let mut expressions = Vec::new();
                    while let Some(statement) = statements.pop() {
                        push_statement_analysis_children(
                            statement,
                            &mut statements,
                            &mut expressions,
                        );
                    }
                    while let Some(expression) = expressions.pop() {
                        if let ExprKind::Call { func, .. } = &expression.node
                            && callable_path(func)
                                .is_some_and(|path| path.rsplit('.').next() == Some(call_leaf))
                        {
                            return true;
                        }
                        push_expression_analysis_children(expression, &mut expressions);
                    }
                    return false;
                }
                _ => {}
            }
        }
    }
    false
}

pub(super) struct DefinitionAnalysis {
    pub(super) definition: TypedDefinition,
    pub(super) calls: Vec<ReachableCall>,
    pub(super) property_reads: Vec<String>,
}

pub(super) struct ReachableCall {
    pub(super) source_path: String,
    pub(super) target_path: String,
}

pub(super) fn find_definition(
    file_name: &str,
    statements: &[Stmt],
    scope: &mut Vec<String>,
    requested: &str,
    class_context: Option<&ClassFields>,
) -> Result<Option<DefinitionAnalysis>, TypedCheckError> {
    for statement in statements {
        match &statement.node {
            StmtKind::ClassDef { name, body, .. } => {
                scope.push(name.to_string());
                let fields = class_fields(body);
                let found = find_definition(file_name, body, scope, requested, Some(&fields))?;
                scope.pop();
                if found.is_some() {
                    return Ok(found);
                }
            }
            StmtKind::FunctionDef {
                name,
                args,
                body,
                returns,
                ..
            } => {
                let mut qualified = scope.clone();
                qualified.push(name.to_string());
                let qualified_name = qualified.join(".");
                if qualified_name != requested {
                    continue;
                }
                validate_restricted_statements(file_name, &qualified_name, body)?;
                let mut signature = signature(
                    file_name,
                    &qualified_name,
                    scope.last().map(String::as_str),
                    args,
                    body,
                    returns.as_deref(),
                )?;
                let erased_state_names = legacy_state_bindings(body);
                let hir = lower_definition_hir(
                    file_name,
                    &qualified_name,
                    body,
                    &signature,
                    class_context.map_or(&HashMap::new(), |fields| &fields.types),
                    class_context.map_or(&HashMap::new(), |fields| &fields.values),
                    &erased_state_names,
                );
                if returns.is_none() {
                    if let Some(inferred) = hir.inferred_return_type() {
                        signature.return_type = inferred;
                    }
                }
                if let Some(anchor) = hir.first_link_structural_use() {
                    return Err(TypedCheckError::LinkControlledTopology {
                        file_name: file_name.to_owned(),
                        definition: qualified_name,
                        line: anchor.line(),
                        column: anchor.column(),
                    });
                }
                let property_reads = class_context.map_or_else(Vec::new, |fields| {
                    hir.referenced_attributes(&fields.properties)
                });
                return Ok(Some(DefinitionAnalysis {
                    definition: TypedDefinition {
                        module: file_name.to_owned(),
                        signature,
                        qualified_name,
                        return_type_is_explicit: returns.is_some(),
                        hir,
                    },
                    calls: calls_in_statements(body, &erased_state_names, class_context),
                    property_reads,
                }));
            }
            _ => {}
        }
    }
    Ok(None)
}

fn legacy_state_bindings(statements: &[Stmt]) -> HashSet<String> {
    let mut candidates = HashSet::new();
    let mut statement_stack: Vec<_> = statements.iter().collect();
    let mut expressions = Vec::<&Expr>::new();
    while let Some(statement) = statement_stack.pop() {
        if let StmtKind::Assign { targets, value, .. } = &statement.node {
            if is_legacy_state_initializer(value) {
                for target in targets {
                    if let ExprKind::Name { id, .. } = &target.node {
                        candidates.insert(id.to_string());
                    }
                }
            }
        }
        push_statement_analysis_children(statement, &mut statement_stack, &mut expressions);
    }

    let mut used_as_call_argument = HashSet::new();
    while let Some(expression) = expressions.pop() {
        if let ExprKind::Call { args, keywords, .. } = &expression.node {
            for argument in args
                .iter()
                .chain(keywords.iter().map(|keyword| keyword.node.value.as_ref()))
            {
                if let ExprKind::Name { id, .. } = &argument.node {
                    if candidates.contains(&id.to_string()) {
                        used_as_call_argument.insert(id.to_string());
                    }
                }
            }
        }
        push_expression_analysis_children(expression, &mut expressions);
    }
    candidates
        .intersection(&used_as_call_argument)
        .cloned()
        .collect()
}

fn is_get_end_state_call(expression: &Expr) -> bool {
    let ExprKind::Call { func, .. } = &expression.node else {
        return false;
    };
    expression_path(func).is_some_and(|path| path.rsplit('.').next() == Some("get_end_state"))
}

fn is_legacy_state_initializer(expression: &Expr) -> bool {
    if is_get_end_state_call(expression) {
        return true;
    }
    let ExprKind::Call {
        func,
        args,
        keywords,
    } = &expression.node
    else {
        return false;
    };
    args.is_empty()
        && keywords.is_empty()
        && expression_path(func).is_some_and(|path| {
            path.ends_with(".default_states.copy") || path.ends_with(".default_state.copy")
        })
}

fn is_erased_state_expression(expression: &Expr, erased_names: &HashSet<String>) -> bool {
    is_legacy_state_initializer(expression)
        || matches!(&expression.node, ExprKind::Name { id, .. } if erased_names.contains(&id.to_string()))
}

fn calls_in_statements(
    statements: &[Stmt],
    erased_state_names: &HashSet<String>,
    class_context: Option<&ClassFields>,
) -> Vec<ReachableCall> {
    let mut calls = Vec::new();
    let bindings = HashMap::new();
    for statement in statements {
        visit_statement_calls(
            statement,
            erased_state_names,
            class_context,
            &bindings,
            &mut calls,
        );
    }
    calls
}

fn visit_statement_calls(
    statement: &Stmt,
    erased_state_names: &HashSet<String>,
    class_context: Option<&ClassFields>,
    bindings: &HashMap<String, Vec<String>>,
    calls: &mut Vec<ReachableCall>,
) {
    match &statement.node {
        StmtKind::Return {
            value: Some(value),
            ..
        } => visit_expression_calls(
            value,
            erased_state_names,
            class_context,
            bindings,
            calls,
        ),
        StmtKind::Return { value: None, .. } => {}
        StmtKind::Assign { targets, value, .. }
            if targets.iter().any(|target| {
                matches!(&target.node, ExprKind::Name { id, .. } if erased_state_names.contains(&id.to_string()))
            }) && is_legacy_state_initializer(value) => {}
        StmtKind::Assign { value, .. } | StmtKind::Expr { value, .. } => {
            visit_expression_calls(
                value,
                erased_state_names,
                class_context,
                bindings,
                calls,
            );
        }
        StmtKind::AnnAssign {
            value: Some(value),
            ..
        } => visit_expression_calls(
            value,
            erased_state_names,
            class_context,
            bindings,
            calls,
        ),
        StmtKind::AnnAssign { value: None, .. } => {}
        StmtKind::AugAssign { value, .. } => {
            visit_expression_calls(
                value,
                erased_state_names,
                class_context,
                bindings,
                calls,
            );
        }
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            visit_expression_calls(
                test,
                erased_state_names,
                class_context,
                bindings,
                calls,
            );
            for statement in body.iter().chain(orelse) {
                visit_statement_calls(
                    statement,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
        }
        StmtKind::For {
            iter, body, orelse, ..
        } => {
            visit_expression_calls(
                iter,
                erased_state_names,
                class_context,
                bindings,
                calls,
            );
            for statement in body.iter().chain(orelse) {
                visit_statement_calls(
                    statement,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
        }
        _ => {}
    }
}

fn visit_expression_calls(
    expression: &Expr,
    erased_state_names: &HashSet<String>,
    class_context: Option<&ClassFields>,
    bindings: &HashMap<String, Vec<String>>,
    calls: &mut Vec<ReachableCall>,
) {
    match &expression.node {
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            let compile_environment_load =
                expression_path(func).is_some_and(|path| path == "np.load" || path == "numpy.load");
            if let Some(path) = callable_path(func) {
                let mut segments = path.split('.');
                let first = segments.next().unwrap_or(&path);
                let remainder = segments.collect::<Vec<_>>().join(".");
                if let Some(targets) = bindings.get(first) {
                    calls.extend(targets.iter().map(|target| ReachableCall {
                        source_path: path.clone(),
                        target_path: if remainder.is_empty() {
                            target.clone()
                        } else {
                            format!("{target}.{remainder}")
                        },
                    }));
                } else {
                    calls.push(ReachableCall {
                        source_path: path.clone(),
                        target_path: path,
                    });
                }
            }
            if compile_environment_load {
                return;
            }
            if matches!(func.node, ExprKind::Call { .. }) {
                visit_expression_calls(func, erased_state_names, class_context, bindings, calls);
            }
            for argument in args {
                if is_erased_state_expression(argument, erased_state_names) {
                    continue;
                }
                visit_expression_calls(
                    argument,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
            for keyword in keywords {
                if is_erased_state_expression(&keyword.node.value, erased_state_names) {
                    continue;
                }
                visit_expression_calls(
                    &keyword.node.value,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
        }
        ExprKind::BoolOp { values, .. }
        | ExprKind::List { elts: values, .. }
        | ExprKind::Tuple { elts: values, .. }
        | ExprKind::Set { elts: values } => {
            for value in values {
                visit_expression_calls(value, erased_state_names, class_context, bindings, calls);
            }
        }
        ExprKind::NamedExpr { target, value }
        | ExprKind::BinOp {
            left: target,
            right: value,
            ..
        } => {
            visit_expression_calls(target, erased_state_names, class_context, bindings, calls);
            visit_expression_calls(value, erased_state_names, class_context, bindings, calls);
        }
        ExprKind::UnaryOp { operand, .. } => {
            visit_expression_calls(operand, erased_state_names, class_context, bindings, calls);
        }
        ExprKind::Lambda { body, .. } => {
            visit_expression_calls(body, erased_state_names, class_context, bindings, calls)
        }
        ExprKind::IfExp { test, body, orelse } => {
            for expression in [test.as_ref(), body.as_ref(), orelse.as_ref()] {
                visit_expression_calls(
                    expression,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
        }
        ExprKind::Dict { keys, values } => {
            for key in keys.iter().flatten() {
                visit_expression_calls(key, erased_state_names, class_context, bindings, calls);
            }
            for value in values {
                visit_expression_calls(value, erased_state_names, class_context, bindings, calls);
            }
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            visit_expression_calls(left, erased_state_names, class_context, bindings, calls);
            for comparator in comparators {
                visit_expression_calls(
                    comparator,
                    erased_state_names,
                    class_context,
                    bindings,
                    calls,
                );
            }
        }
        ExprKind::Attribute { value, .. } => {
            visit_expression_calls(value, erased_state_names, class_context, bindings, calls);
        }
        ExprKind::Subscript { value, slice, .. } => {
            visit_expression_calls(value, erased_state_names, class_context, bindings, calls);
            visit_expression_calls(slice, erased_state_names, class_context, bindings, calls);
        }
        ExprKind::ListComp { elt, generators }
        | ExprKind::SetComp { elt, generators }
        | ExprKind::GeneratorExp { elt, generators } => visit_comprehension_calls(
            &[elt.as_ref()],
            generators,
            erased_state_names,
            class_context,
            bindings,
            calls,
        ),
        ExprKind::DictComp {
            key,
            value,
            generators,
        } => visit_comprehension_calls(
            &[key.as_ref(), value.as_ref()],
            generators,
            erased_state_names,
            class_context,
            bindings,
            calls,
        ),
        _ => {}
    }
}

fn visit_comprehension_calls(
    elements: &[&Expr],
    generators: &[nac3ast::Comprehension],
    erased_state_names: &HashSet<String>,
    class_context: Option<&ClassFields>,
    outer_bindings: &HashMap<String, Vec<String>>,
    calls: &mut Vec<ReachableCall>,
) {
    let mut bindings = outer_bindings.clone();
    for generator in generators {
        visit_expression_calls(
            &generator.iter,
            erased_state_names,
            class_context,
            &bindings,
            calls,
        );
        if let (ExprKind::Name { id, .. }, Some(iter_path), Some(class_context)) = (
            &generator.target.node,
            expression_path(&generator.iter),
            class_context,
        ) && let Some(property) = iter_path.strip_prefix("self.")
            && let Some(targets) = class_context.property_elements.get(property)
        {
            bindings.insert(id.to_string(), targets.clone());
        }
        for condition in &generator.ifs {
            visit_expression_calls(
                condition,
                erased_state_names,
                class_context,
                &bindings,
                calls,
            );
        }
    }
    for element in elements {
        visit_expression_calls(element, erased_state_names, class_context, &bindings, calls);
    }
}
