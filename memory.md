# `'assembler' object has no attribute '0'` 错误修复

## 错误信息

```
❌ OASM execution with assembler_seq failed: 'assembler' object has no attribute '0'
```

## 根因分析

错误发生在 `catseq/compilation/execution.py` 第89行：

```python
assembler_seq(0, set_tout)
```

查看 `oasm/rtmq2/__init__.py` 中 `assembler.__call__` 的实现：

```python
def __call__(self, *args, **kwargs):
    multi = getattr(self.asm,'multi',None)
    if multi is None:
        # 单板模式：args[0] 是函数
        ...
    else:
        # 多板模式：需要至少2个参数
        if len(args) < 2:
            return self
        if args[0] is None:
            # None 表示对所有板子执行
            with self:
                args[1](*args[2:],**kwargs)
        else:
            # 非 None 时，尝试 self[args[0]] → getattr(self, str(args[0]))
            with self[args[0]]:
                args[1](*args[2:],**kwargs)
```

当 `assembler` 以多板模式创建时（例如 `assembler(run_all, [('rwg0', C_RWG)])`），`self.asm.multi` 被设置为 `['rwg0']`。
此时 `__call__` 进入多板分支。

传入 `0` 作为第一个参数时，代码尝试 `self[0]` → `getattr(self, '0')`，但 `assembler` 对象只有 `'rwg0'` 属性，没有 `'0'` 属性，因此抛出 `AttributeError`。

## 修复

将 `0` 改为板子名称字符串，例如 `'rwg0'`：

```python
# 修改前
assembler_seq(0, set_tout)

# 修改后
assembler_seq('rwg0', set_tout)
```

`set_tout` 是全局设置（设置 `asm.tout = 100`），需要指定具体的板子名称来执行。

## 关键教训

- `assembler.__call__` 的第一个参数在多板模式下是板子名称（字符串），不是数字索引
- 使用 `None` 会导致指令不执行（`args[0] is None` 分支虽然不会报错，但 `set_tout` 设置的是模块级 `asm.tout`，而非 `assembler_seq` 实例内部的 `asm.tout`，因此不会正确生效）
- 单板模式下第一个参数是函数本身，多板模式下第一个参数是板子标识，第二个参数才是函数
