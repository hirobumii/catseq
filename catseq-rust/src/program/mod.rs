//! CatSeq V2 Program Module
//!
//! 控制流层的 Rust 实现，包括：
//! - `nodes`: Program AST 节点类型
//! - `values`: 符号值系统
//! - `arena`: ProgramArena 存储

pub mod arena;
pub mod nodes;
pub mod values;

pub use arena::ProgramArena;
pub use nodes::{AluOp, CmpOp, NodeData, NodeId};
pub use values::{LogicalOp, TypeHint, UnaryOp, ValueData, ValueId};
