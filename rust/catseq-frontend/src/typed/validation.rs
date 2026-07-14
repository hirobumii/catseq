//! Validation of the restricted Python statement surface.

use nac3ast::{Expr, ExprKind, Stmt, StmtKind};

use super::ast_util::{push_expression_analysis_children, push_statement_analysis_children};
use super::model::TypedCheckError;

pub(super) fn validate_restricted_statements(
    file_name: &str,
    definition: &str,
    body: &[Stmt],
) -> Result<(), TypedCheckError> {
    let mut pending: Vec<_> = body.iter().rev().collect();
    while let Some(statement) = pending.pop() {
        match &statement.node {
            StmtKind::Return { .. }
            | StmtKind::Assign { .. }
            | StmtKind::AugAssign { .. }
            | StmtKind::AnnAssign { .. }
            | StmtKind::Expr { .. }
            | StmtKind::Pass { .. } => {}
            StmtKind::If { body, orelse, .. } | StmtKind::For { body, orelse, .. } => {
                pending.extend(orelse.iter().rev());
                pending.extend(body.iter().rev());
            }
            unsupported => {
                return Err(TypedCheckError::UnsupportedStatement {
                    file_name: file_name.to_owned(),
                    definition: definition.to_owned(),
                    statement: statement_kind_name(unsupported).to_owned(),
                    line: statement.location.row,
                    column: statement.location.column,
                });
            }
        }
    }
    let mut pending_statements: Vec<_> = body.iter().collect();
    let mut expressions = Vec::new();
    while let Some(statement) = pending_statements.pop() {
        push_statement_analysis_children(statement, &mut pending_statements, &mut expressions);
    }
    while let Some(expression) = expressions.pop() {
        if !is_supported_expression(expression) {
            return Err(TypedCheckError::UnsupportedExpression {
                file_name: file_name.to_owned(),
                definition: definition.to_owned(),
                expression: expression_kind_name(&expression.node).to_owned(),
                line: expression.location.row,
                column: expression.location.column,
            });
        }
        push_expression_analysis_children(expression, &mut expressions);
    }
    Ok(())
}

const fn is_supported_expression(expression: &Expr) -> bool {
    matches!(
        &expression.node,
        ExprKind::BoolOp { .. }
            | ExprKind::NamedExpr { .. }
            | ExprKind::BinOp { .. }
            | ExprKind::UnaryOp { .. }
            | ExprKind::Lambda { .. }
            | ExprKind::IfExp { .. }
            | ExprKind::Dict { .. }
            | ExprKind::Set { .. }
            | ExprKind::ListComp { .. }
            | ExprKind::SetComp { .. }
            | ExprKind::DictComp { .. }
            | ExprKind::GeneratorExp { .. }
            | ExprKind::Compare { .. }
            | ExprKind::Call { .. }
            | ExprKind::Constant { .. }
            | ExprKind::Attribute { .. }
            | ExprKind::Subscript { .. }
            | ExprKind::Name { .. }
            | ExprKind::List { .. }
            | ExprKind::Tuple { .. }
    )
}

const fn expression_kind_name(expression: &ExprKind) -> &'static str {
    match expression {
        ExprKind::BoolOp { .. } => "boolean operation",
        ExprKind::NamedExpr { .. } => "named",
        ExprKind::BinOp { .. } => "binary operation",
        ExprKind::UnaryOp { .. } => "unary operation",
        ExprKind::Lambda { .. } => "lambda",
        ExprKind::IfExp { .. } => "conditional",
        ExprKind::Dict { .. } => "dictionary",
        ExprKind::Set { .. } => "set",
        ExprKind::ListComp { .. } => "list comprehension",
        ExprKind::SetComp { .. } => "set comprehension",
        ExprKind::DictComp { .. } => "dictionary comprehension",
        ExprKind::GeneratorExp { .. } => "generator",
        ExprKind::Await { .. } => "await",
        ExprKind::Yield { .. } => "yield",
        ExprKind::YieldFrom { .. } => "yield from",
        ExprKind::Compare { .. } => "comparison",
        ExprKind::Call { .. } => "call",
        ExprKind::FormattedValue { .. } => "formatted string value",
        ExprKind::JoinedStr { .. } => "formatted string",
        ExprKind::Constant { .. } => "constant",
        ExprKind::Attribute { .. } => "attribute",
        ExprKind::Subscript { .. } => "subscript",
        ExprKind::Starred { .. } => "starred",
        ExprKind::Name { .. } => "name",
        ExprKind::List { .. } => "list",
        ExprKind::Tuple { .. } => "tuple",
        ExprKind::Slice { .. } => "slice",
    }
}

const fn statement_kind_name(statement: &StmtKind) -> &'static str {
    match statement {
        StmtKind::FunctionDef { .. } => "nested function",
        StmtKind::AsyncFunctionDef { .. } => "async function",
        StmtKind::ClassDef { .. } => "nested class",
        StmtKind::Return { .. } => "return",
        StmtKind::Delete { .. } => "del",
        StmtKind::Assign { .. } => "assignment",
        StmtKind::AugAssign { .. } => "augmented assignment",
        StmtKind::AnnAssign { .. } => "annotated assignment",
        StmtKind::For { .. } => "for",
        StmtKind::AsyncFor { .. } => "async for",
        StmtKind::While { .. } => "while",
        StmtKind::If { .. } => "if",
        StmtKind::With { .. } => "with",
        StmtKind::AsyncWith { .. } => "async with",
        StmtKind::Raise { .. } => "raise",
        StmtKind::Try { .. } => "try",
        StmtKind::Assert { .. } => "assert",
        StmtKind::Import { .. } => "import",
        StmtKind::ImportFrom { .. } => "from import",
        StmtKind::Global { .. } => "global",
        StmtKind::Nonlocal { .. } => "nonlocal",
        StmtKind::Expr { .. } => "expression",
        StmtKind::Pass { .. } => "pass",
        StmtKind::Break { .. } => "break",
        StmtKind::Continue { .. } => "continue",
    }
}
