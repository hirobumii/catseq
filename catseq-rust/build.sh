#!/bin/bash
# CatSeq Rust Backend 构建脚本

set -e  # 遇到错误立即退出

echo "=== CatSeq Rust Backend 构建脚本 ==="

# 检查 Rust 是否安装
if ! command -v cargo &> /dev/null; then
    echo "错误: Rust 未安装"
    echo "请运行: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

# 检查 maturin 是否安装
if ! command -v maturin &> /dev/null; then
    echo "安装 maturin..."
    pip install maturin
fi

# 运行 Rust 单元测试
echo ""
echo "=== 步骤 1/3: 运行 Rust 单元测试 ==="
cargo test --lib --release

# 构建 Python 扩展
echo ""
echo "=== 步骤 2/3: 构建 Python 扩展 ==="
maturin develop --release

# 运行 Python 集成测试
echo ""
echo "=== 步骤 3/3: 运行 Python 集成测试 ==="
cd ..
pytest tests/test_rust_backend.py -v

echo ""
echo "✅ 构建完成！"
echo ""
echo "使用方法:"
echo "  from catseq.v2.rust_backend import RustMorphism"
echo "  ctx = RustMorphism.create_context()"
echo "  ..."
