//! CatSeq V2 Value Types
//!
//! 符号值系统，支持字面量、变量、表达式。
//! 所有值都存储在 Arena 中，Python 只持有轻量级 Handle（ValueId）。

use super::nodes::{AluOp, CmpOp};

pub type ValueId = u32;

/// 类型提示
///
/// 用于变量声明和编译优化
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TypeHint {
    Int32,
    Int64,
    Float32,
    Float64,
    Bool,
}

impl TypeHint {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "int32" | "i32" => Some(TypeHint::Int32),
            "int64" | "i64" => Some(TypeHint::Int64),
            "float32" | "f32" => Some(TypeHint::Float32),
            "float64" | "f64" => Some(TypeHint::Float64),
            "bool" => Some(TypeHint::Bool),
            _ => None,
        }
    }
}

/// 一元操作符
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnaryOp {
    /// 算术取反 (-x)
    Neg,
    /// 逻辑非 (!x)
    Not,
    /// 位取反 (~x)
    BitNot,
}

impl UnaryOp {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "-" => Some(UnaryOp::Neg),
            "!" => Some(UnaryOp::Not),
            "~" => Some(UnaryOp::BitNot),
            _ => None,
        }
    }
}

/// 逻辑操作符
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogicalOp {
    And,
    Or,
    Not,
}

impl LogicalOp {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "and" | "&&" => Some(LogicalOp::And),
            "or" | "||" => Some(LogicalOp::Or),
            "not" | "!" => Some(LogicalOp::Not),
            _ => None,
        }
    }
}

/// Value 数据
///
/// 表示可以在运行时求值的表达式。
/// 所有 Value 都存储在 Arena 中，支持表达式树的高效共享。
#[derive(Debug, Clone)]
pub enum ValueData {
    /// 字面量
    ///
    /// 统一使用 i64 存储（float 通过 to_bits 转换）
    Literal {
        value: i64,
        /// 标记是否为浮点数（用于正确解释 bits）
        is_float: bool,
    },

    /// 变量
    ///
    /// 对应硬件寄存器或编译时符号
    Variable {
        name: String,
        type_hint: TypeHint,
    },

    /// 二元表达式
    ///
    /// 例如：x + y, a * b
    BinaryExpr {
        lhs: ValueId,
        op: AluOp,
        rhs: ValueId,
    },

    /// 一元表达式
    ///
    /// 例如：-x, ~y, !z
    UnaryExpr {
        op: UnaryOp,
        operand: ValueId,
    },

    /// 条件表达式
    ///
    /// 比较操作，返回 bool
    /// 例如：x > 0, a == b
    Condition {
        lhs: ValueId,
        op: CmpOp,
        rhs: ValueId,
    },

    /// 逻辑表达式
    ///
    /// 布尔运算
    /// 例如：a && b, !c
    LogicalExpr {
        lhs: ValueId,
        op: LogicalOp,
        /// None 表示一元操作（NOT）
        rhs: Option<ValueId>,
    },
}

impl ValueData {
    /// 创建整数字面量
    pub fn int(value: i64) -> Self {
        ValueData::Literal {
            value,
            is_float: false,
        }
    }

    /// 创建浮点数字面量
    pub fn float(value: f64) -> Self {
        ValueData::Literal {
            value: value.to_bits() as i64,
            is_float: true,
        }
    }

    /// 获取字面量的整数值
    pub fn as_int(&self) -> Option<i64> {
        match self {
            ValueData::Literal {
                value, is_float, ..
            } if !is_float => Some(*value),
            _ => None,
        }
    }

    /// 获取字面量的浮点值
    pub fn as_float(&self) -> Option<f64> {
        match self {
            ValueData::Literal {
                value, is_float, ..
            } if *is_float => Some(f64::from_bits(*value as u64)),
            _ => None,
        }
    }

    /// 检查是否为字面量
    pub fn is_literal(&self) -> bool {
        matches!(self, ValueData::Literal { .. })
    }

    /// 检查是否为变量
    pub fn is_variable(&self) -> bool {
        matches!(self, ValueData::Variable { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_type_hint_from_str() {
        assert_eq!(TypeHint::from_str("int32"), Some(TypeHint::Int32));
        assert_eq!(TypeHint::from_str("i32"), Some(TypeHint::Int32));
        assert_eq!(TypeHint::from_str("int64"), Some(TypeHint::Int64));
        assert_eq!(TypeHint::from_str("float32"), Some(TypeHint::Float32));
        assert_eq!(TypeHint::from_str("float64"), Some(TypeHint::Float64));
        assert_eq!(TypeHint::from_str("bool"), Some(TypeHint::Bool));
        assert_eq!(TypeHint::from_str("unknown"), None);
    }

    #[test]
    fn test_int_literal() {
        let lit = ValueData::int(42);
        assert_eq!(lit.as_int(), Some(42));
        assert_eq!(lit.as_float(), None);
        assert!(lit.is_literal());
    }

    #[test]
    fn test_float_literal() {
        let lit = ValueData::float(3.14);
        assert_eq!(lit.as_int(), None);
        assert!((lit.as_float().unwrap() - 3.14).abs() < 1e-10);
        assert!(lit.is_literal());
    }

    #[test]
    fn test_variable() {
        let var = ValueData::Variable {
            name: "x".to_string(),
            type_hint: TypeHint::Int32,
        };
        assert!(var.is_variable());
        assert!(!var.is_literal());
    }

    #[test]
    fn test_unary_op_from_str() {
        assert_eq!(UnaryOp::from_str("-"), Some(UnaryOp::Neg));
        assert_eq!(UnaryOp::from_str("!"), Some(UnaryOp::Not));
        assert_eq!(UnaryOp::from_str("~"), Some(UnaryOp::BitNot));
        assert_eq!(UnaryOp::from_str("??"), None);
    }

    #[test]
    fn test_logical_op_from_str() {
        assert_eq!(LogicalOp::from_str("and"), Some(LogicalOp::And));
        assert_eq!(LogicalOp::from_str("&&"), Some(LogicalOp::And));
        assert_eq!(LogicalOp::from_str("or"), Some(LogicalOp::Or));
        assert_eq!(LogicalOp::from_str("||"), Some(LogicalOp::Or));
        assert_eq!(LogicalOp::from_str("not"), Some(LogicalOp::Not));
        assert_eq!(LogicalOp::from_str("??"), None);
    }
}
