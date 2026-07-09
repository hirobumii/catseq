#!/bin/bash
set -e

echo "🚀 Setting up CatSeq development environment (Developer-First Mode)..."

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: setup.sh must be run from the project root directory"
    exit 1
fi

# Install uv if not already installed
if ! command -v uv &> /dev/null; then
    echo "📦 Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # This line might need adjustment depending on the shell config file (.bashrc, .zshrc, etc.)
    # Source the environment file to make uv available in the current session
    source "$HOME/.cargo/env"
fi

echo "🐍 Setting up Python virtual environment with uv..."

# Create virtual environment using uv
# The --seed flag ensures pip, setuptools, and wheel are available, which is good practice.
uv venv --python 3.12 --seed

# Activate virtual environment
source .venv/bin/activate

echo "📋 Installing CatSeq and all dev dependencies..."
uv pip install -e .[dev]

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
