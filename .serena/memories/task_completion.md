# 任务完成时的步骤

当你完成一个开发任务后，应该按照以下顺序执行这些步骤，确保代码质量和一致性。

## 1. 代码格式化

使用 `ruff` 格式化代码：
```bash
ruff format catseq/
```

## 2. 代码风格检查

检查并修复代码风格问题：
```bash
# 检查问题
ruff check catseq/

# 自动修复可修复的问题
ruff check catseq/ --fix
```

## 3. 类型检查

运行 `mypy` 确保类型安全：
```bash
mypy catseq/
```

**注意**: 确保没有类型错误。如果有新的类型忽略需求，应在代码中明确标注原因。

## 4. 运行测试

运行完整的测试套件：
```bash
# 详细模式
.venv/bin/pytest tests/ -v

# 或者在 Windows 上
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

**要求**: 所有 49 个测试必须通过。

### 如果添加了新功能
- 添加对应的单元测试
- 确保测试覆盖了边界情况和错误情况
- 测试文件放在 `tests/unit/` 或 `tests/integration/`

### 如果修复了 bug
- 添加回归测试确保 bug 不会再次出现
- 在测试中注释说明这是针对哪个 bug 的测试

## 5. 更新文档（如果适用）

### 如果修改了公共 API
- 更新相关的 docstring
- 更新 `README.md` 中的示例（如果涉及）
- 更新 `docs/user/` 中的用户文档

### 如果修改了架构
- 更新 `docs/dev/compiler_notes.md`
- 如果有重大变更，更新 `CLAUDE.md`

### 如果修改了依赖
- 更新 `pyproject.toml`
- 运行 `uv pip install -e .[dev]` 确保依赖安装正确

## 6. Git 提交

### 提交消息规范
使用语义化提交消息：

```bash
# 新功能
git commit -m "feat: add support for RSP hardware module"

# Bug 修复
git commit -m "fix: correct timing offset in RWG load-play pipeline"

# 重构
git commit -m "refactor: simplify Morphism composition logic"

# 文档
git commit -m "docs: update compiler architecture documentation"

# 测试
git commit -m "test: add integration tests for multi-board sync"

# 性能优化
git commit -m "perf: optimize PhysicalLane merge algorithm"

# 样式/格式
git commit -m "style: apply ruff formatting to compiler module"

# 依赖
git commit -m "chore: update oasm.dev to version 2.0.0"
```

### 提交前检查清单
- [ ] 代码已格式化 (`ruff format`)
- [ ] 代码风格检查通过 (`ruff check`)
- [ ] 类型检查通过 (`mypy`)
- [ ] 所有测试通过 (`pytest`)
- [ ] 文档已更新（如果需要）
- [ ] 提交消息清晰描述了更改

## 7. 推送到远程（如果适用）

```bash
# 推送到主分支
git push origin main

# 或推送到功能分支
git push origin feature/your-feature-name
```

## 完整的一键命令

可以使用以下命令链来执行所有检查：

```bash
# Linux/macOS
ruff format catseq/ && \
ruff check catseq/ --fix && \
mypy catseq/ && \
.venv/bin/pytest tests/ -v && \
echo "✅ All checks passed!"

# Windows PowerShell
ruff format catseq/; `
ruff check catseq/ --fix; `
mypy catseq/; `
.\.venv\Scripts\python.exe -m pytest tests/ -v; `
if ($?) { Write-Host "✅ All checks passed!" -ForegroundColor Green }
```

## 特殊情况

### 如果测试失败
1. 仔细阅读失败消息
2. 使用 `pytest tests/path/to/test.py::test_name -v -s` 运行单个测试并查看输出
3. 修复问题
4. 重新运行完整测试套件

### 如果类型检查失败
1. 检查 mypy 报告的错误
2. 添加或修正类型注解
3. 如果是已知的第三方库问题，可以在 `pyproject.toml` 中配置忽略
4. 重新运行 `mypy catseq/`

### 如果格式化检查失败
1. 运行 `ruff format catseq/` 自动格式化
2. 对于 `ruff check` 报告的问题，使用 `--fix` 自动修复
3. 手动修复无法自动修复的问题

## 版本发布（维护者）

如果需要发布新版本：

1. 更新 `pyproject.toml` 中的版本号
2. 更新 `CHANGELOG.md`（如果存在）
3. 确保所有测试通过
4. 创建 git tag：
   ```bash
   git tag -a v0.2.1 -m "Release version 0.2.1"
   git push origin v0.2.1
   ```
5. 创建 GitHub Release（如果适用）

## 总结

**最小化工作流**：
```bash
ruff format catseq/
ruff check catseq/ --fix
mypy catseq/
pytest tests/ -v
git commit -m "type: description"
git push
```

遵循这些步骤确保代码库的高质量和一致性。
