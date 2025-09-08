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

echo "📋 Step 1/4: Installing oasm.dev to enable extension patching..."
uv pip install oasm.dev h5py scipy numpy

# --- NEW STEP ADDED HERE ---
echo "📋 Step 2/4: Installing sipyco from GitHub and locking version..."
# We install directly from a specific git commit hash to "lock" the version.
# This ensures that everyone gets the exact same dependency, making builds reproducible.
uv pip install git+https://github.com/m-labs/sipyco@96fcefb
# --- END OF NEW STEP ---

echo "📋 Step 3/4: Running script to patch oasm.dev with extensions..."
python scripts/post_install.py

echo "📋 Step 4/4: Installing catseq and all dev dependencies..."
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

