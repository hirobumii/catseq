"""CatSeq V2 Program - 轻量级 Handle

Program 是 Arena 中节点的轻量级 Handle，只持有 node_id。
支持 Monadic 组合操作符 (>>)。

使用示例：
    >>> from catseq.v2.program import Program
    >>> from catseq.v2.dsl import delay, lift
    >>>
    >>> # 顺序组合
    >>> p1 = delay(100)
    >>> p2 = delay(200)
    >>> seq = p1 >> p2  # Chain: 先执行 p1，再执行 p2
    >>>
    >>> # 重复
    >>> repeated = p1.replicate(10)
"""

from __future__ import annotations

from catseq.v2.context import get_arena


class Program:
    """Program: Arena 中节点的轻量级 Handle

    不存储任何逻辑，只持有 node_id。
    所有实际数据存储在 Rust ProgramArena 中。
    """

    __slots__ = ("_id",)

    def __init__(self, node_id: int):
        self._id = node_id

    @property
    def id(self) -> int:
        """获取 Arena 中的 NodeId"""
        return self._id

    def __rshift__(self, other: Program) -> Program:
        """Monadic bind (>>): 顺序组合

        先执行 self，再执行 other。
        代数语义：(>>) :: M a -> M b -> M b
        """
        arena = get_arena()
        new_id = arena.chain(self._id, other._id)
        return Program(new_id)

    def replicate(self, n: int) -> Program:
        """重复 n 次

        Args:
            n: 重复次数

        Returns:
            Program: 循环节点
        """
        from catseq.v2.dsl import repeat
        return repeat(n, self)

    def __repr__(self) -> str:
        return f"Program(id={self._id})"

    def __sizeof__(self) -> int:
        """返回对象的内存大小（字节）

        Program 只持有一个 int，非常轻量。
        """
        # __slots__ 对象的基础大小 + int 大小
        import sys
        return object.__sizeof__(self) + sys.getsizeof(self._id) - sys.getsizeof(0)
