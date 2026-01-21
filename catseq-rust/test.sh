#!/bin/bash
# CatSeq Rust Backend 测试脚本
#
# 用法:
#   ./test.sh          # 完整测试（Rust + Python）
#   ./test.sh rust     # 仅 Rust 测试
#   ./test.sh python   # 仅 Python 测试（需先构建）
#   ./test.sh build    # 仅构建，不测试
#   ./test.sh quick    # 快速开发模式（debug 构建 + 测试）

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 加载 Rust 环境
source ~/.cargo/env 2>/dev/null || true

# 加载 Python 虚拟环境
source ~/catseq/.venv/bin/activate 2>/dev/null || true

echo -e "${BLUE}=== CatSeq Rust Backend 测试 ===${NC}"
echo ""

# 检查依赖
check_deps() {
    if ! command -v cargo &> /dev/null; then
        echo -e "${RED}错误: Rust 未安装${NC}"
        echo "请运行: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
        exit 1
    fi

    if ! python -c "import maturin" 2>/dev/null; then
        echo -e "${YELLOW}安装 maturin...${NC}"
        python -m pip install maturin
    fi
}

# Rust 测试
rust_test() {
    echo -e "${BLUE}[Rust] 运行单元测试...${NC}"
    cargo test --lib
    echo -e "${GREEN}[Rust] 测试通过 ✓${NC}"
}

# 构建 Python 扩展
build_python() {
    local mode=${1:-release}
    if [ "$mode" = "debug" ]; then
        echo -e "${BLUE}[Build] 构建 Python 扩展 (debug)...${NC}"
        maturin develop
    else
        echo -e "${BLUE}[Build] 构建 Python 扩展 (release)...${NC}"
        maturin develop --release
    fi
    echo -e "${GREEN}[Build] 构建完成 ✓${NC}"
}

# Python 测试
python_test() {
    echo -e "${BLUE}[Python] 运行集成测试...${NC}"

    # 确保 pytest 已安装
    if ! python -c "import pytest" 2>/dev/null; then
        echo -e "${YELLOW}安装 pytest...${NC}"
        python -m pip install pytest
    fi

    python -m pytest tests/ -v --tb=short
    echo -e "${GREEN}[Python] 测试通过 ✓${NC}"
}

# 快速验证（用于开发）
quick_check() {
    echo -e "${BLUE}[Quick] 快速验证...${NC}"
    python -c "
import catseq_rs
ctx = catseq_rs.CompilerContext()
n1 = ctx.atomic(0, 100, b'test')
n2 = ctx.atomic(1, 50, b'test2')
seq = n1 @ n2
par = ctx.atomic(0, 100, b'a') | ctx.atomic(1, 100, b'b')
print(f'Context: {ctx}')
print(f'Sequential duration: {seq.duration}')
print(f'Parallel duration: {par.duration}')
events = seq.compile()
print(f'Compiled events: {len(events)}')
print('Quick check passed!')
"
    echo -e "${GREEN}[Quick] 验证通过 ✓${NC}"
}

# 主逻辑
case "${1:-full}" in
    rust)
        check_deps
        rust_test
        ;;
    python)
        python_test
        ;;
    build)
        check_deps
        build_python release
        ;;
    quick)
        check_deps
        rust_test
        build_python debug
        quick_check
        ;;
    full|"")
        check_deps
        rust_test
        echo ""
        build_python release
        echo ""
        python_test
        echo ""
        echo -e "${GREEN}=== 全部测试通过 ✓ ===${NC}"
        ;;
    *)
        echo "用法: $0 [rust|python|build|quick|full]"
        echo ""
        echo "  rust    - 仅运行 Rust 单元测试"
        echo "  python  - 仅运行 Python 集成测试"
        echo "  build   - 仅构建 Python 扩展"
        echo "  quick   - 快速开发模式（debug + 简单验证）"
        echo "  full    - 完整测试（默认）"
        exit 1
        ;;
esac
