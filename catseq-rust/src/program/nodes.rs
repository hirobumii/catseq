//! CatSeq V2 Program AST Node Types
//!
//! Program 层的控制流节点，支持硬件循环、分支等 FPGA 原语。
//! 这些节点与 Morphism Arena（数据流）是正交的。

use std::collections::HashMap;

pub type NodeId = u32;
pub type ValueId = u32;

/// 比较操作符
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CmpOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl CmpOp {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "==" => Some(CmpOp::Eq),
            "!=" => Some(CmpOp::Ne),
            "<" => Some(CmpOp::Lt),
            "<=" => Some(CmpOp::Le),
            ">" => Some(CmpOp::Gt),
            ">=" => Some(CmpOp::Ge),
            _ => None,
        }
    }
}

/// 算术操作符
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AluOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    BitAnd,
    BitOr,
    BitXor,
    Shl,
    Shr,
}

impl AluOp {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "+" => Some(AluOp::Add),
            "-" => Some(AluOp::Sub),
            "*" => Some(AluOp::Mul),
            "/" => Some(AluOp::Div),
            "%" => Some(AluOp::Mod),
            "&" => Some(AluOp::BitAnd),
            "|" => Some(AluOp::BitOr),
            "^" => Some(AluOp::BitXor),
            "<<" => Some(AluOp::Shl),
            ">>" => Some(AluOp::Shr),
            _ => None,
        }
    }
}

/// Program 节点数据
///
/// 使用 Functional Naming (Haskell/Category Theory 风格):
/// - Lift: 将 Morphism 提升到 Program Monad
/// - Chain: 顺序组合 (>>)
/// - Match: 模式匹配
/// - Apply: 函数应用
#[derive(Debug, Clone)]
pub enum NodeData {
    /// Lift: 将 Morphism 提升到 Program
    ///
    /// 物理语义：执行一个预定义的硬件操作序列
    /// 代数语义：return :: a -> M a
    Lift {
        /// Morphism 引用（可以是 Python object id 或 Morphism Arena id）
        morphism_ref: u64,
        /// 参数绑定：变量名 -> ValueId
        params: HashMap<String, ValueId>,
    },

    /// Delay: 时间延迟
    ///
    /// 物理语义：等待指定时间
    /// 支持变量时长（运行时确定）
    Delay {
        /// 延迟时长（ValueId，可以是 Literal 或 Variable）
        duration: ValueId,
        /// 最大时长提示（用于编译优化）
        max_hint: Option<u64>,
    },

    /// Set: 变量赋值
    ///
    /// 物理语义：更新寄存器/变量值
    Set {
        /// 目标变量（必须是 Variable）
        target: ValueId,
        /// 赋值表达式
        value: ValueId,
    },

    /// Chain: 顺序组合 (>>)
    ///
    /// 物理语义：先执行 left，再执行 right
    /// 代数语义：(>>) :: M a -> M b -> M b
    Chain {
        left: NodeId,
        right: NodeId,
    },

    /// Loop: 循环
    ///
    /// 物理语义：硬件循环（FPGA loop 原语）
    /// 支持固定次数、变量次数
    Loop {
        /// 循环次数（ValueId）
        count: ValueId,
        /// 循环体
        body: NodeId,
    },

    /// Match: 模式匹配
    ///
    /// 物理语义：硬件分支（FPGA switch）
    /// 代数语义：case 表达式
    Match {
        /// 匹配主体
        subject: ValueId,
        /// 分支：key -> branch NodeId
        /// key 使用 i64 表示（bool: 0/1, int: 直接值）
        cases: HashMap<i64, NodeId>,
        /// 默认分支
        default: Option<NodeId>,
    },

    /// Apply: 函数调用
    ///
    /// 物理语义：子程序调用
    /// 代数语义：函数应用
    Apply {
        /// 函数定义（指向 FuncDef 节点）
        func: NodeId,
        /// 实参列表
        args: Vec<ValueId>,
    },

    /// FuncDef: 函数定义
    ///
    /// 物理语义：可复用的子程序
    FuncDef {
        /// 函数名
        name: String,
        /// 形参列表（ValueId，必须是 Variable）
        params: Vec<ValueId>,
        /// 函数体
        body: NodeId,
    },

    /// Measure: 测量
    ///
    /// 物理语义：从硬件读取测量结果
    Measure {
        /// 存储结果的变量
        target: ValueId,
        /// 测量源（channel id 或其他标识）
        source: u32,
    },

    /// Identity: 空操作
    ///
    /// 物理语义：什么都不做（零时长）
    /// 代数语义：id :: a -> a
    Identity,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cmp_op_from_str() {
        assert_eq!(CmpOp::from_str("=="), Some(CmpOp::Eq));
        assert_eq!(CmpOp::from_str("!="), Some(CmpOp::Ne));
        assert_eq!(CmpOp::from_str("<"), Some(CmpOp::Lt));
        assert_eq!(CmpOp::from_str("<="), Some(CmpOp::Le));
        assert_eq!(CmpOp::from_str(">"), Some(CmpOp::Gt));
        assert_eq!(CmpOp::from_str(">="), Some(CmpOp::Ge));
        assert_eq!(CmpOp::from_str("??"), None);
    }

    #[test]
    fn test_alu_op_from_str() {
        assert_eq!(AluOp::from_str("+"), Some(AluOp::Add));
        assert_eq!(AluOp::from_str("-"), Some(AluOp::Sub));
        assert_eq!(AluOp::from_str("*"), Some(AluOp::Mul));
        assert_eq!(AluOp::from_str("/"), Some(AluOp::Div));
        assert_eq!(AluOp::from_str("%"), Some(AluOp::Mod));
        assert_eq!(AluOp::from_str("&"), Some(AluOp::BitAnd));
        assert_eq!(AluOp::from_str("|"), Some(AluOp::BitOr));
        assert_eq!(AluOp::from_str("^"), Some(AluOp::BitXor));
        assert_eq!(AluOp::from_str("<<"), Some(AluOp::Shl));
        assert_eq!(AluOp::from_str(">>"), Some(AluOp::Shr));
        assert_eq!(AluOp::from_str("??"), None);
    }
}
