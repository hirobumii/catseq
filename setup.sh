#!/bin/bash
set -e

echo "🚀 Setting up CatSeq development environment..."

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: setup.sh must be run from the project root directory"
    exit 1
fi

# Install uv if not already installed
if ! command -v uv &> /dev/null; then
    echo "📦 Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "🐍 Setting up Python virtual environment with uv..."

# Create virtual environment using uv
uv venv --python 3.12

echo "📋 Installing dependencies..."

# Activate virtual environment and install dependencies
source .venv/bin/activate

# Install the package in editable mode with dev dependencies
uv pip install -e .[dev]

echo "🔍 Running development tool checks..."

# Run linting
# echo "  - Running ruff linting..."
# ruff check .

# # Run type checking
# echo "  - Running mypy type checking..."
# mypy .

# # Run tests
# echo "  - Running pytest..."
# pytest

# # Format code
# echo "  - Formatting code with ruff..."
# ruff format .

echo "✅ Development environment setup complete!"
echo ""
echo "📝 To activate the environment in new sessions, run:"
echo "   source .venv/bin/activate"
echo ""
echo "🛠️  Common development commands:"
echo "   ruff check .     # Linting"
echo "   mypy .          # Type checking" 
echo "   pytest          # Run tests"
echo "   ruff format .   # Format code"
echo ""
echo "🎯 Environment is ready for CatSeq development!"