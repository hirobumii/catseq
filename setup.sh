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
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "🐍 Setting up Python virtual environment with uv..."

# Create virtual environment using uv
# The --seed flag ensures pip, setuptools, and wheel are available, which is good practice.
uv venv --python 3.12 --seed

# Activate virtual environment
source .venv/bin/activate

echo "📋 Step 1/3: Installing oasm.dev to enable extension patching..."
uv pip install oasm.dev

echo "📋 Step 2/3: Running script to patch oasm.dev with extensions..."
python scripts/post_install.py

echo "📋 Step 3/3: Installing catseq and all dev dependencies..."
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