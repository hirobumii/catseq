# CatSeq 常用命令

## 环境设置

### 创建虚拟环境（使用 uv）
```bash
# Linux/macOS
uv venv --python 3.12
source .venv/bin/activate

# Windows PowerShell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
```

### 安装依赖
```bash
# 安装开发依赖
uv pip install -e .[dev]

# 仅安装运行时依赖
uv pip install -e .
```

### 使用自动化脚本（推荐）
```bash
# Linux/macOS
chmod +x scripts/setup.sh
./scripts/setup.sh

# Windows PowerShell
.\scripts\setup.ps1
```

## 开发工作流

### 运行测试
```bash
# 运行所有测试（详细模式）
.venv/bin/pytest tests/ -v

# Windows
.\.venv\Scripts\python.exe -m pytest tests/ -v

# 运行特定测试文件
pytest tests/unit/test_morphism.py -v

# 运行特定测试函数
pytest tests/unit/test_compiler.py::test_compile_simple_ttl -v

# 显示打印输出
pytest tests/ -v -s
```

### 代码格式化
```bash
# 检查代码风格（不修改文件）
ruff check catseq/

# 自动修复可修复的问题
ruff check catseq/ --fix

# 格式化代码
ruff format catseq/
```

### 类型检查
```bash
# 运行 mypy 类型检查
mypy catseq/

# 检查特定文件
mypy catseq/compilation/compiler.py
```

### 完整检查流程
```bash
# 格式化 + 类型检查 + 测试
ruff format catseq/ && mypy catseq/ && pytest tests/ -v
```

## Git 工作流

### 查看状态和历史
```bash
# 查看当前状态
git status

# 查看最近提交
git log --oneline -5

# 查看分支
git branch -a
```

### 提交更改
```bash
# 添加所有更改
git add .

# 提交（详细消息）
git commit -m "feat: add new feature description"

# 推送到远程
git push origin main
```

## Python 交互式开发

### 启动 IPython/Jupyter
```bash
# 启动 Jupyter Notebook
jupyter notebook

# 启动 IPython
ipython
```

### 快速测试代码
```python
# 在 Python REPL 中
from catseq import ttl_init, ttl_on, ttl_off, identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation import compile_to_oasm_calls

# 定义硬件
board = Board("RWG_0")
ch = Channel(board, 0, ChannelType.TTL)

# 构建序列
seq = ttl_init(ch) >> ttl_on(ch) >> identity(ch, 10e-6) >> ttl_off(ch)

# 查看可视化
print(seq.lanes_view())
print(seq.timeline_view())

# 编译
calls = compile_to_oasm_calls(seq, verbose=True)
print(calls)
```

## 调试技巧

### 启用详细编译输出
```python
# 查看编译器的详细过程
oasm_calls = compile_to_oasm_calls(morphism, verbose=True)
```

### 查看 Morphism 可视化
```python
# Lane 视图（紧凑）
print(morphism.lanes_view())

# 时间线视图（详细）
print(morphism.timeline_view(style="proportional"))

# 全局时间线（调试级别）
print(morphism.timeline_view(style="global"))
```

### 使用测试作为示例
```bash
# 查看现有测试用例
ls tests/unit/
cat tests/unit/test_morphism.py
```

## 文件系统操作

### 查找文件
```bash
# 查找 Python 文件
find catseq -name "*.py"

# 搜索代码中的关键字
grep -r "compile_to_oasm_calls" catseq/

# 查找包含特定类的文件
grep -r "class Morphism" catseq/
```

### 目录导航
```bash
# 列出目录内容
ls -la catseq/

# 显示目录树（需要安装 tree）
tree catseq/ -L 2

# 切换目录
cd catseq/compilation/
```

## 性能分析

### 使用 cProfile
```bash
python -m cProfile -o profile.stats your_script.py
```

### 使用 pytest-benchmark（如果安装）
```bash
pytest tests/benchmark/ --benchmark-only
```

## 文档生成

### 查看文档
```bash
# 查看 README
cat README.md

# 查看用户文档
cat docs/user/01_quickstart.md
cat docs/user/02_core_concepts.md

# 查看开发者文档
cat docs/dev/compiler_notes.md
```

## 常用 Linux 命令

```bash
# 显示当前工作目录
pwd

# 创建目录
mkdir new_directory

# 删除文件
rm file.py

# 移动/重命名文件
mv old_name.py new_name.py

# 复制文件
cp source.py destination.py

# 查看文件内容
cat file.py
less file.py  # 分页查看
head -n 20 file.py  # 前 20 行
tail -n 20 file.py  # 后 20 行

# 搜索文本
grep "pattern" file.py
grep -r "pattern" catseq/  # 递归搜索

# 查看进程
ps aux | grep python

# 磁盘使用
df -h
du -sh catseq/
```

## 包管理

### 使用 uv
```bash
# 添加新依赖
uv pip install package-name

# 更新依赖
uv pip install --upgrade package-name

# 查看已安装包
uv pip list

# 冻结依赖（生成 requirements.txt）
uv pip freeze > requirements.txt
```

## 清理操作

```bash
# 清理 Python 缓存
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# 清理测试缓存
rm -rf .pytest_cache/
rm -rf .mypy_cache/
rm -rf .ruff_cache/

# 清理构建产物
rm -rf build/
rm -rf dist/
rm -rf *.egg-info/
```

## 快速参考

### 开发循环
```bash
# 1. 修改代码
# 2. 格式化
ruff format catseq/

# 3. 类型检查
mypy catseq/

# 4. 运行测试
pytest tests/ -v

# 5. 提交
git add .
git commit -m "your message"
git push
```

### 故障排查
```bash
# Python 版本
python --version

# 虚拟环境状态
which python  # Linux/macOS
where python  # Windows

# 包版本
pip show oasm.dev
pip show numpy

# 测试单个文件（详细输出）
pytest tests/unit/test_compiler.py -v -s
```
