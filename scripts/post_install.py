"""
Post-installation utilities for catseq package.
This module handles deployment of OASM extensions with automatic environment detection.
It can be run from any location and will detect the current Python environment.
"""

import os
import shutil
import sys
import site
from pathlib import Path
from typing import Optional, Tuple


def detect_environment() -> Tuple[str, Path]:
    """
    Detect current Python environment and return site-packages path.

    Returns:
        Tuple[str, Path]: (environment_type, site_packages_path)
    """
    # Check if we're in a virtual environment
    in_venv = (
        hasattr(sys, 'real_prefix') or
        (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    )

    if in_venv:
        env_type = "virtualenv"
        # Virtual environment site-packages
        if sys.platform == "win32":
            site_packages = Path(sys.prefix) / "Lib" / "site-packages"
        else:
            site_packages = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    else:
        env_type = "system"
        # System site-packages
        site_packages = Path(site.getsitepackages()[0])

    return env_type, site_packages


def get_current_site_packages() -> Path:
    """Get the site-packages directory for the current environment."""
    env_type, site_packages = detect_environment()

    # Validate the path exists
    if not site_packages.exists():
        # Fallback: try to find site-packages from sys.path
        for path_str in sys.path:
            path = Path(path_str)
            if path.name == "site-packages" and path.exists():
                site_packages = path
                break
        else:
            raise RuntimeError(f"Could not locate site-packages directory. Detected path: {site_packages}")

    return site_packages


def print_environment_info():
    """Print current environment information for debugging."""
    print("=== Python Environment Information ===")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"sys.prefix: {sys.prefix}")
    print(f"sys.base_prefix: {getattr(sys, 'base_prefix', 'N/A')}")

    print("\n=== Site-packages Paths ===")
    try:
        print(f"User site-packages: {site.getusersitepackages()}")
    except:
        print("User site-packages: N/A")

    try:
        for i, path in enumerate(site.getsitepackages()):
            print(f"Global site-packages[{i}]: {path}")
    except:
        print("Global site-packages: N/A")

    print(f"\n=== Current Environment Detection ===")
    try:
        env_type, site_pkg = detect_environment()
        print(f"Environment type: {env_type}")
        print(f"Target site-packages: {site_pkg}")
        print(f"Site-packages exists: {site_pkg.exists()}")
    except Exception as e:
        print(f"Environment detection failed: {e}")
    print("=" * 50)


def find_oasm_dev_path() -> Optional[Path]:
    """Find the installation path of oasm.dev package in current environment."""
    try:
        import oasm.dev
        return Path(oasm.dev.__file__).parent
    except ImportError:
        print("Warning: oasm.dev not found in current environment. Please install it first:")
        print("  pip install oasm.dev")
        return None


def find_catseq_extensions() -> Optional[Path]:
    """
    Find the oasm_extensions directory.
    Try multiple locations to support different installation scenarios.
    """
    # Get current site-packages for installed package scenario
    try:
        current_site_packages = get_current_site_packages()

        # Scenario 1: Extensions embedded in installed catseq package
        catseq_package_path = current_site_packages / "catseq"
        embedded_extensions = catseq_package_path / "_internal" / "oasm_extensions"
        if embedded_extensions.exists():
            print(f"Found embedded extensions at: {embedded_extensions}")
            return embedded_extensions

    except Exception as e:
        print(f"Warning: Could not check for embedded extensions: {e}")

    # Scenario 2: Running from project directory (development mode)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    project_extensions = project_root / "oasm_extensions"
    if project_extensions.exists():
        print(f"Found project extensions at: {project_extensions}")
        return project_extensions

    # Scenario 3: Try common project locations
    common_locations = [
        Path.cwd() / "oasm_extensions",
        Path.cwd().parent / "oasm_extensions",
        Path.cwd() / "catseq" / "oasm_extensions",
    ]

    for location in common_locations:
        if location.exists():
            print(f"Found extensions at: {location}")
            return location

    print("Warning: Extensions directory not found. Searched locations:")
    print(f"  - Embedded: {embedded_extensions if 'embedded_extensions' in locals() else 'N/A'}")
    print(f"  - Project: {project_extensions}")
    for loc in common_locations:
        print(f"  - Common: {loc}")

    return None


def install_oasm_extensions() -> bool:
    """
    Install OASM extension files to appropriate locations.

    Returns:
        bool: True if installation succeeded, False otherwise
    """
    oasm_dev_path = find_oasm_dev_path()
    extensions_path = find_catseq_extensions()

    if not oasm_dev_path or not extensions_path:
        print("Could not find oasm.dev path or catseq extensions. Aborting.")
        return False

    print(f"Found oasm.dev at: {oasm_dev_path}")
    print(f"Found catseq extensions at: {extensions_path}")

    success_count = 0
    total_files = 0

    # Use environment detection to determine site-packages directory
    try:
        site_packages = get_current_site_packages()
        env_type, _ = detect_environment()
        print(f"Detected {env_type} environment, installing to: {site_packages}")
    except RuntimeError as e:
        print(f"Could not determine site-packages directory: {e}")
        return False

    # 1. Install regular files to oasm.dev (excluding special files)
    extension_files = [f for f in extensions_path.glob("*") 
                      if f.is_file() and f.name not in ["__init__.py", "veri.py"]]
    
    if extension_files:
        print(f"Installing OASM.dev extensions to {oasm_dev_path}...")
        total_files += len(extension_files)
        
        for file_path in extension_files:
            target_path = oasm_dev_path / file_path.name
            try:
                shutil.copy2(file_path, target_path)
                print(f"  ✓ Installed {file_path.name}")
                success_count += 1
            except Exception as e:
                print(f"  ✗ Failed to install {file_path.name}: {e}")
    
    # 2. Install hdl directory to site-packages root
    hdl_dir = extensions_path / "hdl"
    if hdl_dir.exists() and hdl_dir.is_dir():
        target_hdl = site_packages / "hdl"
        total_files += 1
        try:
            if target_hdl.exists():
                print(f"Removing existing hdl directory at {target_hdl}...")
                shutil.rmtree(target_hdl)
            
            print(f"Copying hdl directory to {target_hdl}...")
            shutil.copytree(hdl_dir, target_hdl)
            print(f"  ✓ Installed hdl directory to {target_hdl}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to install hdl directory: {e}")
            
    # 3. Install ftd3xx directory to site-packages root
    ftd3xx_dir = extensions_path / "ftd3xx"
    if ftd3xx_dir.exists() and ftd3xx_dir.is_dir():
        target_ftd3xx = site_packages / "ftd3xx"
        total_files += 1
        try:
            if target_ftd3xx.exists():
                print(f"Removing existing ftd3xx directory at {target_ftd3xx}...")
                shutil.rmtree(target_ftd3xx)
            
            print(f"Copying ftd3xx directory to {target_ftd3xx}...")
            shutil.copytree(ftd3xx_dir, target_ftd3xx)
            print(f"  ✓ Installed ftd3xx directory to {target_ftd3xx}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to install ftd3xx directory: {e}")
    
    # 4. Install veri.py to site-packages root with lib path correction
    veri_file = extensions_path / "veri.py"
    if veri_file.exists():
        target_veri = site_packages / "veri.py"
        total_files += 1
        try:
            with open(veri_file, 'r') as f:
                veri_content = f.read()
            
            corrected_lib_path = str(site_packages / "hdl" / "rtmq2" / sys.platform)
            veri_content = veri_content.replace(
                'lib=r"C:\\Users\\Jiang\\Documents\\rtmq\\py\\archon\\hdl\\rtmq2\\lib"',
                f'lib=r"{corrected_lib_path}"'
            )
            
            with open(target_veri, 'w') as f:
                f.write(veri_content)
            
            print(f"  ✓ Installed veri.py to {target_veri} (lib path corrected)")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to install veri.py: {e}")
    
    if total_files == 0:
        print("No extension files found to install.")
        return True
    
    if success_count == total_files:
        print(f"Successfully installed {success_count} extension(s).")
        return True
    else:
        print(f"Installed {success_count}/{total_files} extensions. Some installations failed.")
        return False


def main():
    print("Running CatSeq OASM extension setup...")

    # Add optional debug info flag
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        print_environment_info()
        print()

    success = install_oasm_extensions()
    if success:
        print("CatSeq OASM extension setup completed successfully!")
    else:
        print("CatSeq OASM extension setup completed with warnings or errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()
