"""
AST to xDSL IR Conversion Layer

This module converts the Program AST (program_ast.py) to xDSL IR (program_dialect.py),
enabling non-recursive traversal and pattern-based transformations while maintaining
the existing Program API.
"""

from typing import Dict, List
from xdsl.ir import Block, Region, SSAValue, Operation
from xdsl.dialects.builtin import IntegerAttr, IntegerType, StringAttr, ModuleOp

from .program_ast import (
    ProgramNode,
    MorphismStmt,
    SequenceStmt,
    ForLoopStmt,
    IfStmt,
)
from .variables import RuntimeVar, CompileTimeParam
from .expressions import Condition, BinOp, UnaryOp, VarRef, ConstExpr
from ..dialects.program_dialect import (
    ExecuteOp,
    SequenceOp,
    ForOp,
    IfOp,
    CompareOp,
    LogicalAndOp,
    LogicalOrOp,
    LogicalNotOp,
    MorphismRefType,
    ConditionType,
)


class ASTToIRConverter:
    """Converts Program AST to xDSL IR operations
    
    This converter maintains a mapping between Morphism objects and their unique IDs,
    and properly handles SSA values for conditions.
    """
    
    def __init__(self):
        """Initialize the converter with an empty morphism registry"""
        self._morphism_registry: Dict[int, object] = {}  # morphism_id -> Morphism object
        self._next_morphism_id: int = 0
        self._condition_ops: List[Operation] = []  # Track condition operations to insert
    
    def register_morphism(self, morphism) -> int:
        """Register a Morphism and return its unique ID
        
        Args:
            morphism: The Morphism object to register
            
        Returns:
            The unique ID assigned to this morphism
        """
        morphism_id = self._next_morphism_id
        self._morphism_registry[morphism_id] = morphism
        self._next_morphism_id += 1
        return morphism_id
    
    def get_morphism(self, morphism_id: int):
        """Retrieve a Morphism by its ID
        
        Args:
            morphism_id: The unique ID of the morphism
            
        Returns:
            The Morphism object
            
        Raises:
            KeyError: If the morphism_id is not found
        """
        return self._morphism_registry[morphism_id]
    
    def convert_condition(self, condition: Condition) -> SSAValue:
        """Convert a Condition AST node to xDSL IR operation and return SSA value
        
        Args:
            condition: The Condition AST node
            
        Returns:
            An SSA value of type !program.condition
        """
        expr = condition._expr
        
        if isinstance(expr, BinOp):
            # Check if it's a comparison or logical operation
            if expr.op in {">", "<", ">=", "<=", "==", "!="}:
                # Comparison operation: var > value
                if not isinstance(expr.left, VarRef):
                    raise ValueError("Left side of comparison must be a variable reference")
                if not isinstance(expr.right, ConstExpr):
                    raise ValueError("Right side of comparison must be a constant")
                
                var_ref = StringAttr(expr.left.var.name)
                comparator = StringAttr(expr.op)
                
                # Convert value to IntegerAttr
                if isinstance(expr.right.value, int):
                    value = IntegerAttr(expr.right.value, IntegerType(32))
                else:
                    # For float, cast to int (may need refinement)
                    value = IntegerAttr(int(expr.right.value), IntegerType(32))
                
                op = CompareOp.build(
                    attributes={
                        "var_ref": var_ref,
                        "comparator": comparator,
                        "value": value
                    },
                    result_types=[ConditionType()]
                )
                self._condition_ops.append(op)
                return op.result
            
            elif expr.op == "&&":
                # Logical AND
                lhs_val = self.convert_condition(Condition(expr.left))
                rhs_val = self.convert_condition(Condition(expr.right))
                
                op = LogicalAndOp.build(
                    operands=[lhs_val, rhs_val],
                    result_types=[ConditionType()]
                )
                self._condition_ops.append(op)
                return op.result
            
            elif expr.op == "||":
                # Logical OR
                lhs_val = self.convert_condition(Condition(expr.left))
                rhs_val = self.convert_condition(Condition(expr.right))
                
                op = LogicalOrOp.build(
                    operands=[lhs_val, rhs_val],
                    result_types=[ConditionType()]
                )
                self._condition_ops.append(op)
                return op.result
            
            else:
                raise ValueError(f"Unsupported binary operator in condition: {expr.op}")
        
        elif isinstance(expr, UnaryOp):
            if expr.op == "!":
                # Logical NOT
                operand_val = self.convert_condition(Condition(expr.operand))
                
                op = LogicalNotOp.build(
                    operands=[operand_val],
                    result_types=[ConditionType()]
                )
                self._condition_ops.append(op)
                return op.result
            else:
                raise ValueError(f"Unsupported unary operator in condition: {expr.op}")
        
        else:
            raise ValueError(f"Unsupported condition expression type: {type(expr)}")
    
    def convert_node_recursive(self, node: ProgramNode, collect_conditions: bool = False) -> Operation:
        """Convert a ProgramNode to xDSL IR operation (RECURSIVE VERSION - avoid for deep nesting)
        
        Args:
            node: The AST node to convert
            collect_conditions: If True, collect condition ops instead of clearing them
            
        Returns:
            The corresponding xDSL IR operation
        """
        if isinstance(node, MorphismStmt):
            # Register the morphism and create ExecuteOp
            morphism_id = self.register_morphism(node.morphism)
            morphism_ref = MorphismRefType.from_int(morphism_id)
            
            return ExecuteOp.build(attributes={"morphism_ref": morphism_ref})
        
        elif isinstance(node, SequenceStmt):
            # Convert all statements in the sequence
            ops = []
            for stmt in node.statements:
                # Save and clear condition ops for each statement
                saved_cond_ops = self._condition_ops[:]
                self._condition_ops.clear()
                
                stmt_op = self.convert_node_recursive(stmt, collect_conditions=True)
                
                # Add condition ops before the statement
                ops.extend(self._condition_ops)
                ops.append(stmt_op)
                
                # Restore condition ops if we're collecting
                if collect_conditions:
                    self._condition_ops = saved_cond_ops + self._condition_ops
                else:
                    self._condition_ops.clear()
            
            # Create a block containing all operations
            seq_block = Block(ops)
            seq_region = Region([seq_block])
            
            return SequenceOp.build(regions=[seq_region])
        
        elif isinstance(node, ForLoopStmt):
            # Convert loop count
            if isinstance(node.count, int):
                count_attr = IntegerAttr.from_int_and_width(node.count, 64)
            elif isinstance(node.count, CompileTimeParam):
                # For compile-time parameters, we'll use a placeholder value
                # This will need to be resolved at compile time
                count_attr = IntegerAttr.from_int_and_width(0, 64)
                # TODO: Add metadata to track compile-time parameters
            else:
                raise ValueError(f"Unsupported loop count type: {type(node.count)}")
            
            # Clear condition ops for loop body
            self._condition_ops.clear()
            
            # Convert loop body (RECURSIVE CALL - can stack overflow)
            body_op = self.convert_node_recursive(node.body, collect_conditions=False)
            loop_block = Block([body_op])
            loop_region = Region([loop_block])
            
            return ForOp.build(
                attributes={"count": count_attr},
                regions=[loop_region]
            )
        
        elif isinstance(node, IfStmt):
            # Convert condition and get SSA value
            cond_val = self.convert_condition(node.condition)
            
            # Save condition ops that were generated
            cond_ops = self._condition_ops[:]
            
            # Clear for branches
            self._condition_ops.clear()
            
            # Convert then branch
            then_op = self.convert_node_recursive(node.then_branch, collect_conditions=False)
            then_block = Block([then_op])
            then_region = Region([then_block])
            
            # Convert else branch (if exists)
            if node.else_branch:
                else_op = self.convert_node_recursive(node.else_branch, collect_conditions=False)
                else_block = Block([else_op])
                else_region = Region([else_block])
            else:
                # Empty else branch
                else_block = Block([])
                else_region = Region([else_block])
            
            # Create IfOp with the condition value
            if_op = IfOp.build(
                operands=[cond_val],
                regions=[then_region, else_region]
            )
            
            # If we're collecting conditions, we need to wrap in a sequence
            # that includes the condition ops
            if collect_conditions:
                self._condition_ops = cond_ops
            else:
                # Wrap condition ops and if_op in a sequence
                if cond_ops:
                    all_ops = cond_ops + [if_op]
                    block = Block(all_ops)
                    region = Region([block])
                    return SequenceOp.build(regions=[region])
            
            return if_op
        
        else:
            raise ValueError(f"Unsupported AST node type: {type(node)}")
    
    def convert_node(self, node: ProgramNode) -> Operation:
        """Convert a ProgramNode to xDSL IR operation (NON-RECURSIVE)
        
        Uses explicit stack to avoid Python recursion limit for deep nesting.
        
        Args:
            node: The AST node to convert
            
        Returns:
            The corresponding xDSL IR operation
        """
        # For simple nodes without deep nesting, use recursive version for simplicity
        # Check if node has potential for deep nesting (ForLoopStmt)
        if not self._has_deep_nesting(node):
            return self.convert_node_recursive(node, collect_conditions=False)
        
        # For potentially deep nesting, use iterative conversion
        return self._convert_node_iterative(node)
    
    def _has_deep_nesting(self, node: ProgramNode, depth_limit: int = 50) -> bool:
        """Check if node might have deep nesting (simple heuristic)"""
        depth = 0
        current = node
        
        while depth < depth_limit:
            if isinstance(current, ForLoopStmt):
                current = current.body
                depth += 1
            else:
                return False
        
        return True  # Exceeded depth limit, likely has deep nesting
    
    def _convert_node_iterative(self, root: ProgramNode) -> Operation:
        """Non-recursive conversion using explicit stack
        
        This handles deep nesting without stack overflow.
        """
        # Stack: (node, converted_op or None, phase)
        # phase: 'pre' (before conversion), 'post' (after conversion)
        stack = [(root, None, 'pre')]
        converted = {}  # node_id -> converted Operation
        
        while stack:
            node, op, phase = stack.pop()
            node_id = id(node)
            
            if phase == 'post':
                # Store the converted operation
                converted[node_id] = op
                continue
            
            # Pre-conversion phase
            if isinstance(node, MorphismStmt):
                # Leaf node - convert directly
                morphism_id = self.register_morphism(node.morphism)
                morphism_ref = MorphismRefType.from_int(morphism_id)
                op = ExecuteOp.build(attributes={"morphism_ref": morphism_ref})
                converted[node_id] = op
            
            elif isinstance(node, ForLoopStmt):
                # Check if body is already converted
                body_id = id(node.body)
                if body_id in converted:
                    # Body is converted, create ForOp
                    if isinstance(node.count, int):
                        count_attr = IntegerAttr.from_int_and_width(node.count, 64)
                    else:
                        count_attr = IntegerAttr.from_int_and_width(0, 64)
                    
                    body_op = converted[body_id]
                    loop_block = Block([body_op])
                    loop_region = Region([loop_block])
                    
                    op = ForOp.build(
                        attributes={"count": count_attr},
                        regions=[loop_region]
                    )
                    converted[node_id] = op
                else:
                    # Push node back for post-processing
                    stack.append((node, None, 'post-for'))
                    # Push body for conversion
                    stack.append((node.body, None, 'pre'))
            
            elif phase == 'post-for':
                # ForLoop post-processing
                body_id = id(node.body)
                if isinstance(node.count, int):
                    count_attr = IntegerAttr.from_int_and_width(node.count, 64)
                else:
                    count_attr = IntegerAttr.from_int_and_width(0, 64)
                
                body_op = converted[body_id]
                loop_block = Block([body_op])
                loop_region = Region([loop_block])
                
                op = ForOp.build(
                    attributes={"count": count_attr},
                    regions=[loop_region]
                )
                converted[node_id] = op
            
            else:
                # Other node types - use recursive version
                # (SequenceStmt and IfStmt are typically not deeply nested)
                op = self.convert_node_recursive(node, collect_conditions=False)
                converted[node_id] = op
        
        return converted[id(root)]
    
    def convert_to_module(self, node: ProgramNode) -> ModuleOp:
        """Convert a ProgramNode to a complete xDSL Module
        
        Args:
            node: The root AST node
            
        Returns:
            A ModuleOp containing the converted IR
        """
        # Convert the root node
        root_op = self.convert_node(node)
        
        # Wrap in a module
        module_block = Block([root_op])
        module_region = Region([module_block])
        
        return ModuleOp.build(regions=[module_region])


def convert_ast_to_ir(ast: ProgramNode) -> tuple[ModuleOp, ASTToIRConverter]:
    """Convert a Program AST to xDSL IR
    
    Args:
        ast: The Program AST root node
        
    Returns:
        A tuple of (ModuleOp, ASTToIRConverter)
        The converter is returned to allow access to the morphism registry
    """
    converter = ASTToIRConverter()
    module = converter.convert_to_module(ast)
    return module, converter
