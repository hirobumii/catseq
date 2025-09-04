"""
Post-installation utilities for catseq package.
This module handles deployment of OASM extensions.
It is designed to be run from the project root directory before catseq is installed.
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def find_oasm_dev_path() -> Optional[Path]:
    """Find the installation path of oasm.dev package."""
    try:
        import oasm.dev
        return Path(oasm.dev.__file__).parent
    except ImportError:
        print("Warning: oasm.dev not found. Please install it first:")
        print("  pip install oasm.dev")
        return None


def find_catseq_extensions() -> Optional[Path]:
    """Find the oasm_extensions directory in the project."""
    # This script assumes it is run from the project root
    project_root = Path(__file__).parent.parent
    extensions_path = project_root / "oasm_extensions"
    
    if extensions_path.exists():
        return extensions_path
    else:
        print(f"Warning: Extensions directory not found at {extensions_path}")
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
    
    # Determine site-packages directory
    # This is a bit of a heuristic, going up from oasm/dev/__init__.py
    site_packages = oasm_dev_path.parent.parent

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
            
    # 3. Install veri.py to site-packages root with lib path correction
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
    success = install_oasm_extensions()
    if success:
        print("CatSeq OASM extension setup completed successfully!")
    else:
        print("CatSeq OASM extension setup completed with warnings or errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()
