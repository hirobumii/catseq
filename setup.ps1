# PowerShell setup script for CatSeq development environment
# Usage: .\setup.ps1
param(
    [switch]$Help
)

if ($Help) {
    Write-Host "CatSeq Development Environment Setup Script (Windows)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usage: .\setup.ps1" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "This script will:"
    Write-Host "  1. Install uv package manager (if not present)"
    Write-Host "  2. Create Python virtual environment"
    Write-Host "  3. Install required dependencies"
    Write-Host "  4. Set up CatSeq for development"
    exit 0
}

# Enable strict error handling
$ErrorActionPreference = "Stop"

Write-Host "🚀 Setting up CatSeq development environment (Developer-First Mode)..." -ForegroundColor Green

# Check if we're in the right directory
if (!(Test-Path "pyproject.toml")) {
    Write-Host "❌ Error: setup.ps1 must be run from the project root directory" -ForegroundColor Red
    exit 1
}

# Check if uv is installed
try {
    $uvVersion = uv --version 2>$null
    Write-Host "✅ Found uv: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "📦 Installing uv package manager..." -ForegroundColor Yellow
    # Install uv using the official Windows installer
    try {
        # Use PowerShell to download and execute the installer
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

        # Refresh PATH environment variable for current session
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

        # Verify installation
        $uvVersion = uv --version 2>$null
        Write-Host "✅ uv installed successfully: $uvVersion" -ForegroundColor Green
    } catch {
        Write-Host "❌ Failed to install uv. Please install manually from https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Red
        exit 1
    }
}

Write-Host "🐍 Setting up Python virtual environment with uv..." -ForegroundColor Yellow

# Create virtual environment using uv
# The --seed flag ensures pip, setuptools, and wheel are available
try {
    uv venv --python 3.12 --seed
    Write-Host "✅ Virtual environment created" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to create virtual environment. Make sure Python 3.12+ is installed." -ForegroundColor Red
    exit 1
}

# Activate virtual environment (PowerShell version)
$activateScript = ".\.venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    Write-Host "🔄 Activating virtual environment..." -ForegroundColor Yellow
    & $activateScript
} else {
    Write-Host "❌ Failed to find activation script at $activateScript" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Step 1/4: Installing oasm.dev to enable extension patching..." -ForegroundColor Yellow
try {
    uv pip install oasm.dev h5py scipy numpy
    Write-Host "✅ oasm.dev and dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install oasm.dev dependencies" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Step 2/4: Installing sipyco from GitHub and locking version..." -ForegroundColor Yellow
# Install from specific git commit hash for reproducible builds
try {
    uv pip install git+https://github.com/m-labs/sipyco@96fcefb
    Write-Host "✅ sipyco installed from locked version" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install sipyco from GitHub" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Step 3/4: Running script to patch oasm.dev with extensions..." -ForegroundColor Yellow
try {
    python scripts/post_install.py
    Write-Host "✅ oasm.dev extensions patched successfully" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to run post-install script" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Step 4/4: Installing catseq and all dev dependencies..." -ForegroundColor Yellow
try {
    uv pip install -e .[dev]
    Write-Host "✅ CatSeq and development dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install CatSeq" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "✅ Development environment setup complete!" -ForegroundColor Green
Write-Host ""

Write-Host "📝 To activate the environment in new PowerShell sessions, run:" -ForegroundColor Cyan
Write-Host "   .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""

Write-Host "🛠️  Common development commands:" -ForegroundColor Cyan
Write-Host "   ruff check .     # Linting" -ForegroundColor White
Write-Host "   mypy .          # Type checking" -ForegroundColor White
Write-Host "   pytest          # Run tests" -ForegroundColor White
Write-Host "   ruff format .   # Format code" -ForegroundColor White
Write-Host ""

Write-Host "🎯 Environment is ready for CatSeq development!" -ForegroundColor Green
Write-Host ""

# Optional: Test installation
Write-Host "🧪 Testing installation..." -ForegroundColor Yellow
try {
    python -c "import catseq; print('CatSeq import successful!')"
    Write-Host "✅ CatSeq installation verified" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Warning: CatSeq import test failed, but installation may still be functional" -ForegroundColor Yellow
}