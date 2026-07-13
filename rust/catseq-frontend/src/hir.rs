//! Source-level HIR for the restricted CatSeq Python language.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use tree_sitter::{Node, Parser};

use crate::SequenceEntry;

const MAX_EXPRESSION_DEPTH: usize = 512;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct ExpressionId(u32);

impl ExpressionId {
    pub const fn from_index(index: u32) -> Self {
        Self(index)
    }

    pub const fn index(self) -> u32 {
        self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionKind {
    AutoSerial,
    StrictSerial,
    Parallel,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BinaryOperator {
    Add,
    Subtract,
    Multiply,
    Divide,
    FloorDivide,
    Modulo,
    Power,
    ShiftLeft,
    BitAnd,
    BitXor,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnaryOperator {
    Positive,
    Negative,
    Invert,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Literal {
    Integer(i64),
    Float(f64),
    Boolean(bool),
    None,
    String(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KeywordArgument {
    name: String,
    value: ExpressionId,
}

impl KeywordArgument {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub const fn value(&self) -> ExpressionId {
        self.value
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum HirKind {
    Symbol(String),
    Literal(Literal),
    Attribute {
        object: ExpressionId,
        name: String,
    },
    Subscript {
        value: ExpressionId,
        index: ExpressionId,
    },
    Call {
        function: ExpressionId,
        arguments: Vec<ExpressionId>,
        keywords: Vec<KeywordArgument>,
    },
    Compose {
        kind: CompositionKind,
        left: ExpressionId,
        right: ExpressionId,
    },
    Binary {
        operator: BinaryOperator,
        left: ExpressionId,
        right: ExpressionId,
    },
    Unary {
        operator: UnaryOperator,
        argument: ExpressionId,
    },
    Dictionary(Vec<(ExpressionId, ExpressionId)>),
    List(Vec<ExpressionId>),
    Tuple(Vec<ExpressionId>),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SourceSpan {
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub start_column: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct HirExpression {
    kind: HirKind,
    span: SourceSpan,
}

impl HirExpression {
    pub fn kind(&self) -> &HirKind {
        &self.kind
    }

    pub const fn span(&self) -> SourceSpan {
        self.span
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SequenceHir {
    parameters: Vec<String>,
    expressions: Vec<HirExpression>,
    root: ExpressionId,
}

impl SequenceHir {
    pub fn parameters(&self) -> &[String] {
        &self.parameters
    }

    pub fn expressions(&self) -> &[HirExpression] {
        &self.expressions
    }

    pub fn expression(&self, expression: ExpressionId) -> &HirExpression {
        &self.expressions[expression.0 as usize]
    }

    pub const fn root(&self) -> ExpressionId {
        self.root
    }

    pub fn call_count(&self) -> usize {
        self.expressions
            .iter()
            .filter(|expression| matches!(expression.kind, HirKind::Call { .. }))
            .count()
    }

    pub fn composition_count(&self, selected: CompositionKind) -> usize {
        self.expressions
            .iter()
            .filter(|expression| {
                matches!(
                    expression.kind,
                    HirKind::Compose { kind, .. } if kind == selected
                )
            })
            .count()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LoweringError {
    EntryNotFound {
        file_name: String,
        entry: String,
    },
    InvalidEntrySource {
        file_name: String,
        entry: String,
    },
    MissingReturn {
        file_name: String,
        entry: String,
    },
    Unsupported {
        file_name: String,
        kind: String,
        line: usize,
        column: usize,
    },
    InvalidLiteral {
        file_name: String,
        value: String,
        line: usize,
        column: usize,
    },
    ExpressionTooDeep {
        file_name: String,
        line: usize,
        column: usize,
    },
}

impl Display for LoweringError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EntryNotFound { file_name, entry } => {
                write!(
                    formatter,
                    "sequence entry {entry:?} not found in {file_name}"
                )
            }
            Self::InvalidEntrySource { file_name, entry } => {
                write!(
                    formatter,
                    "invalid source for sequence entry {entry:?} in {file_name}"
                )
            }
            Self::MissingReturn { file_name, entry } => {
                write!(
                    formatter,
                    "sequence entry {entry:?} in {file_name} has no return"
                )
            }
            Self::Unsupported {
                file_name,
                kind,
                line,
                column,
            } => write!(
                formatter,
                "unsupported restricted-Python node {kind} at {file_name}:{line}:{column}"
            ),
            Self::InvalidLiteral {
                file_name,
                value,
                line,
                column,
            } => write!(
                formatter,
                "invalid numeric literal {value:?} at {file_name}:{line}:{column}"
            ),
            Self::ExpressionTooDeep {
                file_name,
                line,
                column,
            } => write!(
                formatter,
                "expression nesting exceeds {MAX_EXPRESSION_DEPTH} at {file_name}:{line}:{column}"
            ),
        }
    }
}

impl Error for LoweringError {}

pub(crate) fn lower_entry(
    file_name: &str,
    entry: &SequenceEntry,
) -> Result<SequenceHir, LoweringError> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .map_err(|_| invalid_source(file_name, entry))?;
    let tree = parser
        .parse(entry.source(), None)
        .ok_or_else(|| invalid_source(file_name, entry))?;
    let mut cursor = tree.root_node().walk();
    let function = tree
        .root_node()
        .named_children(&mut cursor)
        .find(|node| node.kind() == "function_definition")
        .ok_or_else(|| invalid_source(file_name, entry))?;
    let parameters = function
        .child_by_field_name("parameters")
        .map(|node| parameter_names(node, entry.source()))
        .unwrap_or_default();
    let body = function
        .child_by_field_name("body")
        .ok_or_else(|| invalid_source(file_name, entry))?;
    let mut lowerer = Lowerer {
        file_name,
        entry,
        source: entry.source(),
        expressions: Vec::new(),
        locals: HashMap::new(),
    };
    let root = lowerer
        .lower_body(body)?
        .ok_or_else(|| LoweringError::MissingReturn {
            file_name: file_name.to_owned(),
            entry: entry.qualified_name().to_owned(),
        })?;
    Ok(SequenceHir {
        parameters,
        expressions: lowerer.expressions,
        root,
    })
}

fn invalid_source(file_name: &str, entry: &SequenceEntry) -> LoweringError {
    LoweringError::InvalidEntrySource {
        file_name: file_name.to_owned(),
        entry: entry.qualified_name().to_owned(),
    }
}

fn parameter_names(parameters: Node<'_>, source: &str) -> Vec<String> {
    let mut cursor = parameters.walk();
    parameters
        .named_children(&mut cursor)
        .filter_map(|parameter| match parameter.kind() {
            "identifier" => text(parameter, source).map(str::to_owned),
            "typed_parameter" => first_named_child(parameter)
                .filter(|name| name.kind() == "identifier")
                .and_then(|name| text(name, source))
                .map(str::to_owned),
            "default_parameter" | "typed_default_parameter" => parameter
                .child_by_field_name("name")
                .and_then(|name| text(name, source))
                .map(str::to_owned),
            _ => None,
        })
        .collect()
}

struct Lowerer<'source> {
    file_name: &'source str,
    entry: &'source SequenceEntry,
    source: &'source str,
    expressions: Vec<HirExpression>,
    locals: HashMap<String, ExpressionId>,
}

impl Lowerer<'_> {
    fn lower_body(&mut self, body: Node<'_>) -> Result<Option<ExpressionId>, LoweringError> {
        let mut cursor = body.walk();
        for statement in body.named_children(&mut cursor) {
            match statement.kind() {
                "expression_statement" => {
                    let Some(inner) = first_named_child(statement) else {
                        continue;
                    };
                    if inner.kind() != "assignment" {
                        return Err(self.unsupported(inner));
                    }
                    self.lower_assignment(inner)?;
                }
                "return_statement" => {
                    let value =
                        first_named_child(statement).ok_or_else(|| self.unsupported(statement))?;
                    return self.lower_expression(value, 0).map(Some);
                }
                "comment" => {}
                _ => return Err(self.unsupported(statement)),
            }
        }
        Ok(None)
    }

    fn lower_assignment(&mut self, assignment: Node<'_>) -> Result<(), LoweringError> {
        let left = assignment
            .child_by_field_name("left")
            .ok_or_else(|| self.unsupported(assignment))?;
        if left.kind() != "identifier" {
            return Err(self.unsupported(left));
        }
        let name = text(left, self.source)
            .ok_or_else(|| self.unsupported(left))?
            .to_owned();
        let right = assignment
            .child_by_field_name("right")
            .ok_or_else(|| self.unsupported(assignment))?;
        let value = self.lower_expression(right, 0)?;
        self.locals.insert(name, value);
        Ok(())
    }

    fn lower_expression(
        &mut self,
        node: Node<'_>,
        depth: usize,
    ) -> Result<ExpressionId, LoweringError> {
        if depth > MAX_EXPRESSION_DEPTH {
            let (line, column) = self.location(node);
            return Err(LoweringError::ExpressionTooDeep {
                file_name: self.file_name.to_owned(),
                line,
                column,
            });
        }
        let next_depth = depth + 1;
        let kind = match node.kind() {
            "identifier" => {
                let name = text(node, self.source).ok_or_else(|| self.unsupported(node))?;
                if let Some(expression) = self.locals.get(name) {
                    return Ok(*expression);
                }
                HirKind::Symbol(name.to_owned())
            }
            "integer" => HirKind::Literal(Literal::Integer(
                self.parse_literal::<i64>(node, |value| value.replace('_', ""))?,
            )),
            "float" => HirKind::Literal(Literal::Float(
                self.parse_literal::<f64>(node, |value| value.replace('_', ""))?,
            )),
            "true" => HirKind::Literal(Literal::Boolean(true)),
            "false" => HirKind::Literal(Literal::Boolean(false)),
            "none" => HirKind::Literal(Literal::None),
            "string" | "concatenated_string" => HirKind::Literal(Literal::String(
                text(node, self.source)
                    .ok_or_else(|| self.unsupported(node))?
                    .to_owned(),
            )),
            "parenthesized_expression" => {
                let child = first_named_child(node).ok_or_else(|| self.unsupported(node))?;
                return self.lower_expression(child, next_depth);
            }
            "attribute" => {
                let object = node
                    .child_by_field_name("object")
                    .ok_or_else(|| self.unsupported(node))?;
                let attribute = node
                    .child_by_field_name("attribute")
                    .ok_or_else(|| self.unsupported(node))?;
                HirKind::Attribute {
                    object: self.lower_expression(object, next_depth)?,
                    name: text(attribute, self.source)
                        .ok_or_else(|| self.unsupported(attribute))?
                        .to_owned(),
                }
            }
            "subscript" => {
                let value = node
                    .child_by_field_name("value")
                    .ok_or_else(|| self.unsupported(node))?;
                let index = node
                    .child_by_field_name("subscript")
                    .ok_or_else(|| self.unsupported(node))?;
                HirKind::Subscript {
                    value: self.lower_expression(value, next_depth)?,
                    index: self.lower_expression(index, next_depth)?,
                }
            }
            "call" => self.lower_call(node, next_depth)?,
            "binary_operator" => self.lower_binary(node, next_depth)?,
            "unary_operator" => self.lower_unary(node, next_depth)?,
            "dictionary" => HirKind::Dictionary(self.lower_dictionary(node, next_depth)?),
            "list" => HirKind::List(self.lower_sequence_items(node, next_depth)?),
            "tuple" => HirKind::Tuple(self.lower_sequence_items(node, next_depth)?),
            _ => return Err(self.unsupported(node)),
        };
        Ok(self.append(kind, node))
    }

    fn lower_call(&mut self, node: Node<'_>, depth: usize) -> Result<HirKind, LoweringError> {
        let function = node
            .child_by_field_name("function")
            .ok_or_else(|| self.unsupported(node))?;
        let function = self.lower_expression(function, depth)?;
        let mut arguments = Vec::new();
        let mut keywords = Vec::new();
        if let Some(argument_list) = node.child_by_field_name("arguments") {
            if argument_list.kind() != "argument_list" {
                return Err(self.unsupported(argument_list));
            }
            let mut cursor = argument_list.walk();
            for argument in argument_list.named_children(&mut cursor) {
                if argument.kind() == "keyword_argument" {
                    let name = argument
                        .child_by_field_name("name")
                        .and_then(|name| text(name, self.source))
                        .ok_or_else(|| self.unsupported(argument))?
                        .to_owned();
                    let value = argument
                        .child_by_field_name("value")
                        .ok_or_else(|| self.unsupported(argument))?;
                    keywords.push(KeywordArgument {
                        name,
                        value: self.lower_expression(value, depth)?,
                    });
                } else {
                    arguments.push(self.lower_expression(argument, depth)?);
                }
            }
        }
        Ok(HirKind::Call {
            function,
            arguments,
            keywords,
        })
    }

    fn lower_binary(&mut self, node: Node<'_>, depth: usize) -> Result<HirKind, LoweringError> {
        let left = node
            .child_by_field_name("left")
            .ok_or_else(|| self.unsupported(node))?;
        let right = node
            .child_by_field_name("right")
            .ok_or_else(|| self.unsupported(node))?;
        let operator = node
            .child_by_field_name("operator")
            .and_then(|operator| text(operator, self.source))
            .ok_or_else(|| self.unsupported(node))?;
        let left = self.lower_expression(left, depth)?;
        let right = self.lower_expression(right, depth)?;
        let composition = match operator {
            ">>" => Some(CompositionKind::AutoSerial),
            "@" => Some(CompositionKind::StrictSerial),
            "|" => Some(CompositionKind::Parallel),
            _ => None,
        };
        if let Some(kind) = composition {
            return Ok(HirKind::Compose { kind, left, right });
        }
        let operator = match operator {
            "+" => BinaryOperator::Add,
            "-" => BinaryOperator::Subtract,
            "*" => BinaryOperator::Multiply,
            "/" => BinaryOperator::Divide,
            "//" => BinaryOperator::FloorDivide,
            "%" => BinaryOperator::Modulo,
            "**" => BinaryOperator::Power,
            "<<" => BinaryOperator::ShiftLeft,
            "&" => BinaryOperator::BitAnd,
            "^" => BinaryOperator::BitXor,
            _ => return Err(self.unsupported(node)),
        };
        Ok(HirKind::Binary {
            operator,
            left,
            right,
        })
    }

    fn lower_unary(&mut self, node: Node<'_>, depth: usize) -> Result<HirKind, LoweringError> {
        let argument = node
            .child_by_field_name("argument")
            .ok_or_else(|| self.unsupported(node))?;
        let operator = node
            .child_by_field_name("operator")
            .and_then(|operator| text(operator, self.source))
            .ok_or_else(|| self.unsupported(node))?;
        let operator = match operator {
            "+" => UnaryOperator::Positive,
            "-" => UnaryOperator::Negative,
            "~" => UnaryOperator::Invert,
            _ => return Err(self.unsupported(node)),
        };
        Ok(HirKind::Unary {
            operator,
            argument: self.lower_expression(argument, depth)?,
        })
    }

    fn lower_dictionary(
        &mut self,
        node: Node<'_>,
        depth: usize,
    ) -> Result<Vec<(ExpressionId, ExpressionId)>, LoweringError> {
        let mut entries = Vec::new();
        let mut cursor = node.walk();
        for pair in node.named_children(&mut cursor) {
            if pair.kind() != "pair" {
                return Err(self.unsupported(pair));
            }
            let key = pair
                .child_by_field_name("key")
                .ok_or_else(|| self.unsupported(pair))?;
            let value = pair
                .child_by_field_name("value")
                .ok_or_else(|| self.unsupported(pair))?;
            entries.push((
                self.lower_expression(key, depth)?,
                self.lower_expression(value, depth)?,
            ));
        }
        Ok(entries)
    }

    fn lower_sequence_items(
        &mut self,
        node: Node<'_>,
        depth: usize,
    ) -> Result<Vec<ExpressionId>, LoweringError> {
        let mut items = Vec::new();
        let mut cursor = node.walk();
        for item in node.named_children(&mut cursor) {
            items.push(self.lower_expression(item, depth)?);
        }
        Ok(items)
    }

    fn parse_literal<T: std::str::FromStr>(
        &self,
        node: Node<'_>,
        normalize: impl FnOnce(&str) -> String,
    ) -> Result<T, LoweringError> {
        let value = text(node, self.source).ok_or_else(|| self.unsupported(node))?;
        normalize(value)
            .parse()
            .map_err(|_| self.invalid_literal(node, value))
    }

    fn append(&mut self, kind: HirKind, node: Node<'_>) -> ExpressionId {
        let expression = ExpressionId(self.expressions.len() as u32);
        let point = node.start_position();
        self.expressions.push(HirExpression {
            kind,
            span: SourceSpan {
                start_byte: self.entry.byte_range().start + node.start_byte(),
                end_byte: self.entry.byte_range().start + node.end_byte(),
                start_line: self.entry.source_start_line + point.row,
                start_column: point.column + 1,
            },
        });
        expression
    }

    fn unsupported(&self, node: Node<'_>) -> LoweringError {
        let (line, column) = self.location(node);
        LoweringError::Unsupported {
            file_name: self.file_name.to_owned(),
            kind: node.kind().to_owned(),
            line,
            column,
        }
    }

    fn invalid_literal(&self, node: Node<'_>, value: &str) -> LoweringError {
        let (line, column) = self.location(node);
        LoweringError::InvalidLiteral {
            file_name: self.file_name.to_owned(),
            value: value.to_owned(),
            line,
            column,
        }
    }

    fn location(&self, node: Node<'_>) -> (usize, usize) {
        let point = node.start_position();
        (self.entry.source_start_line + point.row, point.column + 1)
    }
}

fn first_named_child(node: Node<'_>) -> Option<Node<'_>> {
    let mut cursor = node.walk();
    node.named_children(&mut cursor).next()
}

fn text<'source>(node: Node<'_>, source: &'source str) -> Option<&'source str> {
    node.utf8_text(source.as_bytes()).ok()
}
