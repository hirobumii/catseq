"""
AST preprocessing for RTMQ subroutine compilation.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass


LOCAL_ANNOTATION_NAME = "local"


@dataclass(frozen=True)
class PreparedFunction:
    """Prepared source-level subroutine shape."""

    name: str
    arg_names: tuple[str, ...]
    local_names: tuple[str, ...]
    local_initializers: tuple[ast.Assign, ...]
    transformed_module: ast.Module


class _LocalAnnotationValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.invalid: list[str] = []

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _is_local_annassign(node):
            self.invalid.append("nested")
        self.generic_visit(node)


def _is_local_annassign(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and getattr(node.annotation, "id", None) == LOCAL_ANNOTATION_NAME
    )


def prepare_function_ast(
    module: ast.Module,
    *,
    abi: str,
) -> PreparedFunction:
    """
    Validate and rewrite a function module for the RTMQ subroutine compiler.

    The decorated function must be the first top-level definition in the parsed module.
    """

    if not module.body or not isinstance(module.body[0], ast.FunctionDef):
        raise ValueError("core_domain expects a top-level function definition.")

    function_node = copy.deepcopy(module.body[0])
    name = function_node.name
    function_node.decorator_list = []

    if function_node.args.defaults or function_node.args.kw_defaults:
        raise ValueError(f"core_domain does not support default-valued parameters in '{name}'.")
    if function_node.args.vararg or function_node.args.kwarg or function_node.args.kwonlyargs:
        raise ValueError(f"core_domain does not support varargs/kwargs in '{name}'.")
    if any(arg.annotation is not None for arg in function_node.args.args):
        raise ValueError(
            f"Header register annotations are not supported in '{name}'. "
            "Declare register-backed locals in the body with `x: local` instead."
        )

    arg_names = tuple(arg.arg for arg in function_node.args.args)
    local_names: list[str] = []
    local_initializers: list[ast.Assign] = []
    transformed_body: list[ast.stmt] = []
    declarations_open = True

    for stmt in function_node.body:
        if _is_local_annassign(stmt):
            if not declarations_open:
                raise ValueError(
                    f"Local declarations in '{name}' must appear before executable statements."
                )
            target = stmt.target.id
            if target in arg_names or target in local_names:
                raise ValueError(f"Duplicate local declaration '{target}' in '{name}'.")
            local_names.append(target)
            if stmt.value is not None:
                assign = ast.Assign(
                    targets=[ast.Name(id=target, ctx=ast.Store())],
                    value=stmt.value,
                    lineno=stmt.lineno,
                    col_offset=stmt.col_offset,
                )
                local_initializers.append(assign)
            continue

        declarations_open = False
        transformed_body.append(stmt)

    validator = _LocalAnnotationValidator()
    for stmt in transformed_body:
        validator.visit(stmt)
    if validator.invalid:
        raise ValueError(
            f"Nested local declarations are not supported in '{name}'. "
            "Declare locals only at the top of the function body."
        )

    for stmt in transformed_body:
        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Tuple):
            raise ValueError(f"core_domain supports only a single scalar return value in '{name}'.")

    function_node.args.args = []
    function_node.args.defaults = []
    function_node.args.kw_defaults = []
    wrapper_args: list[ast.expr] = [
        ast.Constant(value=name),
        ast.Constant(value=len(arg_names)),
        ast.Constant(value=len(local_names)),
    ]

    function_node.body = [
        ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=ast.Name(id="_catseq_subroutine_func", ctx=ast.Load()),
                        args=wrapper_args,
                        keywords=[],
                    )
                )
            ],
            body=[*local_initializers, *transformed_body],
        )
    ]

    transformed_module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(transformed_module)
    return PreparedFunction(
        name=name,
        arg_names=arg_names,
        local_names=tuple(local_names),
        local_initializers=tuple(local_initializers),
        transformed_module=transformed_module,
    )
