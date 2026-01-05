"""
Utility functions for program dialect

包含非递归的遍历实现
"""

from typing import Iterator
from xdsl.ir import Operation, Region, Block


def walk_iterative(op: Operation) -> Iterator[Operation]:
    """
    非递归版本的 walk，使用显式栈避免 Python 递归限制

    支持任意深度的嵌套，不会栈溢出。

    示例：
        for nested_op in walk_iterative(root_op):
            print(nested_op)
    """
    # 使用显式栈：每个元素是 (operation, is_processed)
    # is_processed=False 表示还没处理 regions
    stack = [(op, False)]

    while stack:
        current_op, is_processed = stack.pop()

        if not is_processed:
            # 第一次遇到这个操作：yield 它
            yield current_op

            # 标记为已处理，稍后会再次入栈（如果有 regions）
            if current_op.regions:
                # 反向遍历 regions，这样出栈时是正序
                for region in reversed(current_op.regions):
                    # 遍历 region 中的所有 blocks
                    for block in reversed(region.blocks):
                        # 遍历 block 中的所有 operations
                        for block_op in reversed(list(block.ops)):
                            stack.append((block_op, False))


def walk_iterative_with_depth(op: Operation) -> Iterator[tuple[Operation, int]]:
    """
    非递归版本的 walk，同时返回深度信息

    返回: (operation, depth) 元组

    示例：
        for nested_op, depth in walk_iterative_with_depth(root_op):
            print(f"{'  ' * depth}{nested_op.name}")
    """
    # 栈元素：(operation, depth)
    stack = [(op, 0)]

    while stack:
        current_op, depth = stack.pop()
        yield current_op, depth

        # 处理子操作
        if current_op.regions:
            for region in reversed(current_op.regions):
                for block in reversed(region.blocks):
                    for block_op in reversed(list(block.ops)):
                        stack.append((block_op, depth + 1))


def count_operations(op: Operation) -> int:
    """
    统计操作总数（使用非递归遍历）

    示例：
        count = count_operations(root_op)
        print(f"Total operations: {count}")
    """
    return sum(1 for _ in walk_iterative(op))


def max_nesting_depth(op: Operation) -> int:
    """
    计算最大嵌套深度（使用非递归遍历）

    示例：
        depth = max_nesting_depth(root_op)
        print(f"Max depth: {depth}")
    """
    max_depth = 0
    for _, depth in walk_iterative_with_depth(op):
        max_depth = max(max_depth, depth)
    return max_depth
