//! CatSeq V2 Program Arena
//!
//! 存储所有 Program AST 节点和 Value 的中央仓库。
//! Python 只持有轻量级 Handle（NodeId/ValueId），所有数据在 Rust 中。

use pyo3::prelude::*;
use std::collections::HashMap;

use super::nodes::{AluOp, CmpOp, NodeData, NodeId};
use super::values::{LogicalOp, TypeHint, UnaryOp, ValueData, ValueId};

/// Program Arena - 存储所有 AST 节点和 Value
///
/// 这是 Handle-based 架构的核心：
/// - Python 对象只持有 `node_id` 或 `value_id`
/// - 所有数据存储在这个 Arena 中
/// - 支持高效的节点共享和内存管理
#[pyclass(unsendable)]
pub struct ProgramArena {
    /// Program 节点存储
    nodes: Vec<NodeData>,
    /// Value 存储
    values: Vec<ValueData>,
    /// 变量名到 ValueId 的映射（确保同名变量复用）
    var_names: HashMap<String, ValueId>,
}

#[pymethods]
impl ProgramArena {
    /// 创建空的 ProgramArena
    #[new]
    pub fn new() -> Self {
        ProgramArena {
            nodes: Vec::with_capacity(1024),
            values: Vec::with_capacity(1024),
            var_names: HashMap::new(),
        }
    }

    /// 创建带预分配容量的 ProgramArena
    #[staticmethod]
    pub fn with_capacity(node_capacity: usize, value_capacity: usize) -> Self {
        ProgramArena {
            nodes: Vec::with_capacity(node_capacity),
            values: Vec::with_capacity(value_capacity),
            var_names: HashMap::new(),
        }
    }

    /// 获取节点数量
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    /// 获取 Value 数量
    pub fn value_count(&self) -> usize {
        self.values.len()
    }

    /// 获取变量数量
    pub fn var_count(&self) -> usize {
        self.var_names.len()
    }

    /// 清空 Arena（用于重置）
    pub fn clear(&mut self) {
        self.nodes.clear();
        self.values.clear();
        self.var_names.clear();
    }

    // =========================================================================
    // Value 创建方法
    // =========================================================================

    /// 创建整数字面量
    ///
    /// Args:
    ///     value: 整数值
    ///
    /// Returns:
    ///     ValueId: 新创建的 Value 的 ID
    pub fn literal(&mut self, value: i64) -> ValueId {
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::int(value));
        id
    }

    /// 创建浮点数字面量
    ///
    /// Args:
    ///     value: 浮点数值
    ///
    /// Returns:
    ///     ValueId: 新创建的 Value 的 ID
    pub fn literal_float(&mut self, value: f64) -> ValueId {
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::float(value));
        id
    }

    /// 创建或获取变量
    ///
    /// 如果同名变量已存在，返回已有的 ValueId（保证唯一性）。
    ///
    /// Args:
    ///     name: 变量名
    ///     type_hint: 类型提示字符串 ("int32", "int64", "float32", "float64", "bool")
    ///
    /// Returns:
    ///     ValueId: 变量的 ID
    pub fn variable(&mut self, name: &str, type_hint: &str) -> ValueId {
        // 检查是否已存在同名变量
        if let Some(&id) = self.var_names.get(name) {
            return id;
        }

        // 解析类型提示
        let hint = TypeHint::from_str(type_hint).unwrap_or(TypeHint::Int32);

        // 创建新变量
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::Variable {
            name: name.to_string(),
            type_hint: hint,
        });
        self.var_names.insert(name.to_string(), id);
        id
    }

    /// 创建二元表达式
    ///
    /// Args:
    ///     lhs: 左操作数的 ValueId
    ///     op: 操作符字符串 ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>")
    ///     rhs: 右操作数的 ValueId
    ///
    /// Returns:
    ///     ValueId: 表达式的 ID
    pub fn binary_expr(&mut self, lhs: ValueId, op: &str, rhs: ValueId) -> ValueId {
        let alu_op = AluOp::from_str(op).unwrap_or(AluOp::Add);
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::BinaryExpr {
            lhs,
            op: alu_op,
            rhs,
        });
        id
    }

    /// 创建一元表达式
    ///
    /// Args:
    ///     op: 操作符字符串 ("-", "!", "~")
    ///     operand: 操作数的 ValueId
    ///
    /// Returns:
    ///     ValueId: 表达式的 ID
    pub fn unary_expr(&mut self, op: &str, operand: ValueId) -> ValueId {
        let unary_op = UnaryOp::from_str(op).unwrap_or(UnaryOp::Neg);
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::UnaryExpr {
            op: unary_op,
            operand,
        });
        id
    }

    /// 创建条件表达式
    ///
    /// Args:
    ///     lhs: 左操作数的 ValueId
    ///     op: 比较操作符字符串 ("==", "!=", "<", "<=", ">", ">=")
    ///     rhs: 右操作数的 ValueId
    ///
    /// Returns:
    ///     ValueId: 条件表达式的 ID
    pub fn condition(&mut self, lhs: ValueId, op: &str, rhs: ValueId) -> ValueId {
        let cmp_op = CmpOp::from_str(op).unwrap_or(CmpOp::Eq);
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::Condition {
            lhs,
            op: cmp_op,
            rhs,
        });
        id
    }

    /// 创建逻辑表达式
    ///
    /// Args:
    ///     lhs: 左操作数的 ValueId
    ///     op: 逻辑操作符字符串 ("and", "&&", "or", "||", "not", "!")
    ///     rhs: 右操作数的 ValueId（对于 NOT 操作为 None）
    ///
    /// Returns:
    ///     ValueId: 逻辑表达式的 ID
    #[pyo3(signature = (lhs, op, rhs=None))]
    pub fn logical_expr(&mut self, lhs: ValueId, op: &str, rhs: Option<ValueId>) -> ValueId {
        let logical_op = LogicalOp::from_str(op).unwrap_or(LogicalOp::And);
        let id = self.values.len() as ValueId;
        self.values.push(ValueData::LogicalExpr {
            lhs,
            op: logical_op,
            rhs,
        });
        id
    }

    // =========================================================================
    // Node 创建方法
    // =========================================================================

    /// 创建 Lift 节点
    ///
    /// 将 Morphism 提升到 Program 层。
    ///
    /// Args:
    ///     morphism_ref: Morphism 引用（Python object id 或 Morphism Arena id）
    ///     params: 参数绑定字典（变量名 -> ValueId）
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn lift(&mut self, morphism_ref: u64, params: HashMap<String, ValueId>) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Lift {
            morphism_ref,
            params,
        });
        id
    }

    /// 创建 Delay 节点
    ///
    /// Args:
    ///     duration: 延迟时长的 ValueId
    ///     max_hint: 最大时长提示（用于编译优化）
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    #[pyo3(signature = (duration, max_hint=None))]
    pub fn delay(&mut self, duration: ValueId, max_hint: Option<u64>) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Delay { duration, max_hint });
        id
    }

    /// 创建 Set 节点（变量赋值）
    ///
    /// Args:
    ///     target: 目标变量的 ValueId
    ///     value: 赋值表达式的 ValueId
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn set_var(&mut self, target: ValueId, value: ValueId) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Set { target, value });
        id
    }

    /// 创建 Chain 节点（顺序组合）
    ///
    /// Args:
    ///     left: 左节点的 ID
    ///     right: 右节点的 ID
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn chain(&mut self, left: NodeId, right: NodeId) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Chain { left, right });
        id
    }

    /// 创建 Loop 节点
    ///
    /// Args:
    ///     count: 循环次数的 ValueId
    ///     body: 循环体的 NodeId
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    #[pyo3(name = "loop_")]
    pub fn loop_node(&mut self, count: ValueId, body: NodeId) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Loop { count, body });
        id
    }

    /// 创建 Match 节点（模式匹配）
    ///
    /// Args:
    ///     subject: 匹配主体的 ValueId
    ///     cases: 分支字典（key -> NodeId）
    ///     default: 默认分支的 NodeId（可选）
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    #[pyo3(name = "match_", signature = (subject, cases, default=None))]
    pub fn match_node(
        &mut self,
        subject: ValueId,
        cases: HashMap<i64, NodeId>,
        default: Option<NodeId>,
    ) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Match {
            subject,
            cases,
            default,
        });
        id
    }

    /// 创建 Apply 节点（函数调用）
    ///
    /// Args:
    ///     func: 函数定义的 NodeId
    ///     args: 实参列表（ValueId）
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn apply(&mut self, func: NodeId, args: Vec<ValueId>) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Apply { func, args });
        id
    }

    /// 创建 FuncDef 节点（函数定义）
    ///
    /// Args:
    ///     name: 函数名
    ///     params: 形参列表（ValueId，必须是 Variable）
    ///     body: 函数体的 NodeId
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn func_def(&mut self, name: &str, params: Vec<ValueId>, body: NodeId) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::FuncDef {
            name: name.to_string(),
            params,
            body,
        });
        id
    }

    /// 创建 Measure 节点
    ///
    /// Args:
    ///     target: 存储结果的变量 ValueId
    ///     source: 测量源标识
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn measure(&mut self, target: ValueId, source: u32) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Measure { target, source });
        id
    }

    /// 创建 Identity 节点
    ///
    /// Returns:
    ///     NodeId: 新创建节点的 ID
    pub fn identity(&mut self) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(NodeData::Identity);
        id
    }

    // =========================================================================
    // 批量组合方法
    // =========================================================================

    /// 批量 Chain 组合（构建平衡树）
    ///
    /// 将线性 NodeId 列表构建为平衡的 Chain 树，
    /// 避免右偏树导致的递归深度问题。
    ///
    /// Args:
    ///     nodes: NodeId 列表
    ///
    /// Returns:
    ///     NodeId | None: 组合后的根节点 ID，空列表返回 None
    pub fn chain_sequence(&mut self, nodes: Vec<NodeId>) -> Option<NodeId> {
        if nodes.is_empty() {
            return None;
        }
        if nodes.len() == 1 {
            return Some(nodes[0]);
        }

        // 二分归约：每轮将相邻节点两两组合
        let mut current = nodes;
        while current.len() > 1 {
            let mut next = Vec::with_capacity((current.len() + 1) / 2);

            let mut i = 0;
            while i < current.len() {
                if i + 1 < current.len() {
                    let combined = self.chain(current[i], current[i + 1]);
                    next.push(combined);
                    i += 2;
                } else {
                    next.push(current[i]);
                    i += 1;
                }
            }
            current = next;
        }

        Some(current[0])
    }

    // =========================================================================
    // 查询方法
    // =========================================================================

    /// 检查 ValueId 是否为字面量
    pub fn is_literal(&self, value_id: ValueId) -> bool {
        self.values
            .get(value_id as usize)
            .map(|v| v.is_literal())
            .unwrap_or(false)
    }

    /// 检查 ValueId 是否为变量
    pub fn is_variable(&self, value_id: ValueId) -> bool {
        self.values
            .get(value_id as usize)
            .map(|v| v.is_variable())
            .unwrap_or(false)
    }

    /// 获取字面量的整数值
    pub fn get_literal_int(&self, value_id: ValueId) -> Option<i64> {
        self.values.get(value_id as usize).and_then(|v| v.as_int())
    }

    /// 获取字面量的浮点值
    pub fn get_literal_float(&self, value_id: ValueId) -> Option<f64> {
        self.values
            .get(value_id as usize)
            .and_then(|v| v.as_float())
    }

    /// 获取变量名
    pub fn get_variable_name(&self, value_id: ValueId) -> Option<String> {
        match self.values.get(value_id as usize) {
            Some(ValueData::Variable { name, .. }) => Some(name.clone()),
            _ => None,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "<ProgramArena nodes={} values={} vars={}>",
            self.nodes.len(),
            self.values.len(),
            self.var_names.len()
        )
    }
}

impl Default for ProgramArena {
    fn default() -> Self {
        Self::new()
    }
}

// Rust-only methods (not exposed to Python)
impl ProgramArena {
    /// 获取节点引用（Rust only）
    pub fn get_node(&self, id: NodeId) -> Option<&NodeData> {
        self.nodes.get(id as usize)
    }

    /// 获取 Value 引用（Rust only）
    pub fn get_value(&self, id: ValueId) -> Option<&ValueData> {
        self.values.get(id as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_arena() {
        let arena = ProgramArena::new();
        assert_eq!(arena.node_count(), 0);
        assert_eq!(arena.value_count(), 0);
        assert_eq!(arena.var_count(), 0);
    }

    #[test]
    fn test_literal_creation() {
        let mut arena = ProgramArena::new();

        let int_id = arena.literal(42);
        assert_eq!(int_id, 0);
        assert!(arena.is_literal(int_id));
        assert_eq!(arena.get_literal_int(int_id), Some(42));

        let float_id = arena.literal_float(3.14);
        assert_eq!(float_id, 1);
        assert!(arena.is_literal(float_id));
        assert!((arena.get_literal_float(float_id).unwrap() - 3.14).abs() < 1e-10);
    }

    #[test]
    fn test_variable_creation() {
        let mut arena = ProgramArena::new();

        let x_id = arena.variable("x", "int32");
        assert_eq!(x_id, 0);
        assert!(arena.is_variable(x_id));
        assert_eq!(arena.get_variable_name(x_id), Some("x".to_string()));

        // Same name should return same ID
        let x_id2 = arena.variable("x", "int64");
        assert_eq!(x_id, x_id2);

        // Different name should create new variable
        let y_id = arena.variable("y", "float32");
        assert_ne!(x_id, y_id);
    }

    #[test]
    fn test_binary_expr() {
        let mut arena = ProgramArena::new();

        let x = arena.variable("x", "int32");
        let ten = arena.literal(10);
        let expr = arena.binary_expr(x, "+", ten);

        assert_eq!(arena.value_count(), 3);
        assert!(!arena.is_literal(expr));
        assert!(!arena.is_variable(expr));
    }

    #[test]
    fn test_condition() {
        let mut arena = ProgramArena::new();

        let x = arena.variable("x", "int32");
        let zero = arena.literal(0);
        let _cond = arena.condition(x, ">", zero);

        assert_eq!(arena.value_count(), 3);
    }

    #[test]
    fn test_chain() {
        let mut arena = ProgramArena::new();

        let dur1 = arena.literal(100);
        let dur2 = arena.literal(200);
        let delay1 = arena.delay(dur1, None);
        let delay2 = arena.delay(dur2, None);
        let _chained = arena.chain(delay1, delay2);

        assert_eq!(arena.node_count(), 3);
    }

    #[test]
    fn test_loop() {
        let mut arena = ProgramArena::new();

        let count = arena.literal(10);
        let body = arena.identity();
        let _loop_node = arena.loop_node(count, body);

        assert_eq!(arena.node_count(), 2);
    }

    #[test]
    fn test_match() {
        let mut arena = ProgramArena::new();

        let x = arena.variable("x", "int32");
        let branch_a = arena.identity();
        let branch_b = arena.identity();

        let mut cases = HashMap::new();
        cases.insert(0, branch_a);
        cases.insert(1, branch_b);

        let _match_node = arena.match_node(x, cases, None);

        assert_eq!(arena.node_count(), 3);
    }

    #[test]
    fn test_chain_sequence() {
        let mut arena = ProgramArena::new();

        // Create 10 identity nodes
        let nodes: Vec<NodeId> = (0..10).map(|_| arena.identity()).collect();
        let initial_count = arena.node_count();

        // Chain them together
        let root = arena.chain_sequence(nodes);
        assert!(root.is_some());

        // Should have created additional chain nodes
        assert!(arena.node_count() > initial_count);
    }

    #[test]
    fn test_chain_sequence_empty() {
        let mut arena = ProgramArena::new();
        assert_eq!(arena.chain_sequence(vec![]), None);
    }

    #[test]
    fn test_chain_sequence_single() {
        let mut arena = ProgramArena::new();
        let node = arena.identity();
        assert_eq!(arena.chain_sequence(vec![node]), Some(node));
    }

    #[test]
    fn test_clear() {
        let mut arena = ProgramArena::new();

        arena.variable("x", "int32");
        arena.literal(42);
        arena.identity();

        arena.clear();

        assert_eq!(arena.node_count(), 0);
        assert_eq!(arena.value_count(), 0);
        assert_eq!(arena.var_count(), 0);
    }

    #[test]
    fn test_lift_with_params() {
        let mut arena = ProgramArena::new();

        let duration = arena.variable("t", "int32");
        let amplitude = arena.literal_float(0.5);

        let mut params = HashMap::new();
        params.insert("duration".to_string(), duration);
        params.insert("amplitude".to_string(), amplitude);

        let _lift_node = arena.lift(12345, params);

        assert_eq!(arena.node_count(), 1);
        assert_eq!(arena.value_count(), 2);
    }

    #[test]
    fn test_func_def_and_apply() {
        let mut arena = ProgramArena::new();

        // Define function: fn pulse(t) { delay(t) }
        let param_t = arena.variable("_arg_pulse_t", "int32");
        let body = arena.delay(param_t, None);
        let func = arena.func_def("pulse", vec![param_t], body);

        // Apply function: pulse(100)
        let arg = arena.literal(100);
        let _call = arena.apply(func, vec![arg]);

        assert_eq!(arena.node_count(), 4); // delay, func_def, apply
    }
}
