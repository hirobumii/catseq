//! Shared NAC3 AST parsing, traversal, and path helpers.

use nac3ast::{Expr, ExprKind, FileName, Stmt, StmtKind};

use super::model::TypedCheckError;

pub(super) fn parse_module(file_name: &str, source: &str) -> Result<Vec<Stmt>, TypedCheckError> {
    nac3parser::parser::parse_program(source, FileName::from(file_name.to_owned())).map_err(
        |error| TypedCheckError::Parse {
            file_name: file_name.to_owned(),
            message: error.to_string(),
        },
    )
}

pub(super) fn push_statement_analysis_children<'a>(
    statement: &'a Stmt,
    statements: &mut Vec<&'a Stmt>,
    expressions: &mut Vec<&'a Expr>,
) {
    match &statement.node {
        StmtKind::Return { value, .. } => expressions.extend(value.iter().map(Box::as_ref)),
        StmtKind::Assign { targets, value, .. } => {
            expressions.extend(targets);
            expressions.push(value);
        }
        StmtKind::AnnAssign { target, value, .. } => {
            expressions.push(target);
            expressions.extend(value.iter().map(Box::as_ref));
        }
        StmtKind::AugAssign { target, value, .. } => {
            expressions.push(target);
            expressions.push(value);
        }
        StmtKind::Expr { value, .. } => expressions.push(value),
        StmtKind::If {
            test, body, orelse, ..
        }
        | StmtKind::While {
            test, body, orelse, ..
        } => {
            expressions.push(test);
            statements.extend(body);
            statements.extend(orelse);
        }
        StmtKind::For {
            target,
            iter,
            body,
            orelse,
            ..
        } => {
            expressions.push(target);
            expressions.push(iter);
            statements.extend(body);
            statements.extend(orelse);
        }
        _ => {}
    }
}

pub(super) fn push_expression_analysis_children<'a>(
    expression: &'a Expr,
    stack: &mut Vec<&'a Expr>,
) {
    match &expression.node {
        ExprKind::Call {
            func,
            args,
            keywords,
        } => {
            stack.push(func);
            stack.extend(args);
            stack.extend(keywords.iter().map(|keyword| keyword.node.value.as_ref()));
        }
        ExprKind::BoolOp { values, .. }
        | ExprKind::List { elts: values, .. }
        | ExprKind::Tuple { elts: values, .. }
        | ExprKind::Set { elts: values } => stack.extend(values),
        ExprKind::NamedExpr { target, value }
        | ExprKind::BinOp {
            left: target,
            right: value,
            ..
        } => {
            stack.push(target);
            stack.push(value);
        }
        ExprKind::UnaryOp { operand, .. } | ExprKind::Attribute { value: operand, .. } => {
            stack.push(operand);
        }
        ExprKind::Lambda { body, .. } => stack.push(body),
        ExprKind::IfExp { test, body, orelse } => {
            stack.push(test);
            stack.push(body);
            stack.push(orelse);
        }
        ExprKind::Dict { keys, values } => {
            stack.extend(keys.iter().flatten().map(Box::as_ref));
            stack.extend(values);
        }
        ExprKind::Compare {
            left, comparators, ..
        } => {
            stack.push(left);
            stack.extend(comparators);
        }
        ExprKind::Subscript { value, slice, .. } => {
            stack.push(value);
            stack.push(slice);
        }
        ExprKind::ListComp { elt, generators }
        | ExprKind::SetComp { elt, generators }
        | ExprKind::GeneratorExp { elt, generators } => {
            stack.push(elt);
            for generator in generators {
                stack.push(&generator.target);
                stack.push(&generator.iter);
                stack.extend(&generator.ifs);
            }
        }
        ExprKind::DictComp {
            key,
            value,
            generators,
        } => {
            stack.push(key);
            stack.push(value);
            for generator in generators {
                stack.push(&generator.target);
                stack.push(&generator.iter);
                stack.extend(&generator.ifs);
            }
        }
        _ => {}
    }
}

pub(super) fn expression_path(expression: &Expr) -> Option<String> {
    match &expression.node {
        ExprKind::Name { id, .. } => Some(id.to_string()),
        ExprKind::Attribute { value, attr, .. } => {
            let mut path = expression_path(value)?;
            path.push('.');
            path.push_str(&attr.to_string());
            Some(path)
        }
        ExprKind::Constant {
            value: nac3ast::Constant::None,
            ..
        } => Some("None".to_owned()),
        _ => None,
    }
}

pub(super) fn callable_path(expression: &Expr) -> Option<String> {
    expression_path(expression).or_else(|| match &expression.node {
        ExprKind::Attribute { attr, .. } => Some(attr.to_string()),
        _ => None,
    })
}
