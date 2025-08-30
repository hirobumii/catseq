# 解决 OASM 库命名冲突

## 问题描述

在 CatSeq 包中存在名为 `oasm` 的子目录会与 Python 的 `oasm` 库产生命名冲突，当用户尝试同时使用两个包时可能导致导入错误。

## 解决方案

将 `catseq/oasm/` 目录重命名为 `catseq/compilation/`，更准确地反映其功能（编译 Morphism 到 OASM 调用）。

## 具体更改

### 1. 目录重命名
```bash
mv catseq/oasm/ catseq/compilation/
```

### 2. 更新导入语句
- `catseq/__init__.py`: 更新主包导入
- 所有引用 `.oasm` 的地方改为 `.compilation`

### 3. 文档更新
- `PACKAGE_STRUCTURE.md`: 更新包结构图
- `REFACTORING_SUMMARY.md`: 更新重构总结
- 相关技术文档更新目录引用

## 新的包结构

```
catseq/
├── compilation/          # ← 原来的 oasm/
│   ├── __init__.py
│   ├── types.py          # OASM 类型定义
│   ├── functions.py      # OASM DSL 函数
│   └── compiler.py       # Morphism → OASM 编译器
└── ... 其他模块
```

## API 兼容性

✅ **完全向后兼容**: 用户 API 保持不变
```python
import catseq

# 这些调用完全不受影响
calls = catseq.compile_to_oasm_calls(sequence)
catseq.execute_oasm_calls(calls, seq_object)
```

## 验证结果

- ✅ 所有测试通过
- ✅ MyPy 类型检查通过  
- ✅ 多通道分析功能正常
- ✅ 文档已更新

## 命名逻辑

`compilation` 这个名字更准确地描述了模块的功能：
- **职责**: 将高级 Morphism 对象编译为硬件控制调用
- **范围**: 不限于 OASM，未来可以扩展到其他编译目标
- **清晰性**: 避免与外部库名称冲突

## 对开发者的影响

**内部开发者**:
- 需要更新对内部模块的直接导入（如果有）
- 目录结构变更需要更新 IDE 配置

**用户**:
- 无任何影响，所有公共 API 保持不变
- 可以安全地同时使用 CatSeq 和 oasm 库

## 未来扩展

这个重命名为未来扩展铺平了道路：
- 支持多种编译目标（不仅限于 OASM）
- 添加新的硬件控制后端
- 实现不同的代码生成策略