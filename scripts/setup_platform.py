#!/usr/bin/env python3
"""
Platform detection helper script for CatSeq installation.
Automatically detects the platform and runs the appropriate setup script.
"""

import os
import sys
import subprocess
from pathlib import Path


def detect_platform():
    """Detect the current platform."""
    if sys.platform.startswith('win'):
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    elif sys.platform.startswith('linux'):
        return 'linux'
    else:
        return 'unknown'


def check_script_exists(script_path: Path) -> bool:
    """Check if a script file exists and is readable."""
    return script_path.exists() and script_path.is_file()


def run_setup_script():
    """Run the appropriate setup script for the detected platform."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    platform = detect_platform()

    print(f"Detected platform: {platform}")
    print(f"Script directory: {script_dir}")
    print(f"Project root: {project_root}")

    if platform == 'windows':
        script_path = script_dir / 'setup.ps1'
        if check_script_exists(script_path):
            print(f"Running Windows PowerShell setup script: {script_path}")
            try:
                # Use PowerShell to execute the script
                result = subprocess.run([
                    'powershell.exe', '-ExecutionPolicy', 'Bypass',
                    '-File', str(script_path)
                ], check=True)
                return result.returncode == 0
            except subprocess.CalledProcessError as e:
                print(f"Error running PowerShell script: {e}")
                return False
            except FileNotFoundError:
                print("PowerShell not found. Please install PowerShell or run the setup manually.")
                return False
        else:
            print(f"Windows setup script not found at {script_path}")
            return False

    elif platform in ['linux', 'macos']:
        # First check scripts/setup.sh, then root setup.sh
        script_paths = [script_dir / 'setup.sh', project_root / 'setup.sh']

        for script_path in script_paths:
            if check_script_exists(script_path):
                print(f"Running Unix shell setup script: {script_path}")
                try:
                    # Make script executable
                    os.chmod(script_path, 0o755)
                    # Run the script
                    result = subprocess.run(['/bin/bash', str(script_path)], check=True)
                    return result.returncode == 0
                except subprocess.CalledProcessError as e:
                    print(f"Error running shell script: {e}")
                    return False
                except FileNotFoundError:
                    print("Bash shell not found. Please run the setup manually.")
                    return False

        print(f"Unix setup script not found at any of: {script_paths}")
        return False

    else:
        print(f"Unsupported platform: {platform}")
        print("Please run the setup manually using the appropriate script:")
        print("  Windows: .\\scripts\\setup.ps1")
        print("  Linux/macOS: ./scripts/setup.sh")
        return False


def print_manual_instructions():
    """Print manual installation instructions."""
    print("\n" + "="*60)
    print("MANUAL INSTALLATION INSTRUCTIONS")
    print("="*60)
    print("\nIf the automatic setup failed, you can install manually:")
    print("\nWindows PowerShell:")
    print("  .\\scripts\\setup.ps1")
    print("\nLinux/macOS:")
    print("  chmod +x scripts/setup.sh")
    print("  ./scripts/setup.sh")
    print("\nManual step-by-step:")
    print("  1. Install uv: https://docs.astral.sh/uv/getting-started/installation/")
    print("  2. uv venv --python 3.12")
    print("  3. Activate virtual environment")
    print("  4. uv pip install oasm.dev h5py scipy numpy")
    print("  5. uv pip install sipyco")
    print("  6. python scripts/post_install.py")
    print("  7. uv pip install -e .[dev]")


def main():
    """Main entry point."""
    print("🚀 CatSeq Platform Detection and Setup")
    print("=====================================")

    # Check if we're in the right directory
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / 'pyproject.toml'

    if not pyproject_path.exists():
        print("❌ Error: This script must be run from the CatSeq project root directory")
        print(f"   Expected to find: {pyproject_path}")
        print("   Current directory:", Path.cwd())
        sys.exit(1)

    # Change to project root directory
    os.chdir(project_root)
    print(f"✅ Working directory: {project_root}")

    success = run_setup_script()

    if success:
        print("\n✅ Setup completed successfully!")
        print("\nNext steps:")
        print("1. Activate your virtual environment:")
        platform = detect_platform()
        if platform == 'windows':
            print("   .venv\\Scripts\\Activate.ps1")
        else:
            print("   source .venv/bin/activate")
        print("2. Start using CatSeq in your quantum experiments!")
    else:
        print("\n❌ Automated setup failed.")
        print_manual_instructions()
        sys.exit(1)


if __name__ == '__main__':
    main()