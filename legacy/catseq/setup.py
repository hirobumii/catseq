"""
Setup utilities for catseq package.
This module handles post-installation tasks including deploying OASM extensions.
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def find_oasm_dev_path() -> Optional[Path]:
    """Find the installation path of oasm.dev package."""
    try:
        import oasm.dev
        return Path(oasm.dev.__file__).parent
    except ImportError:
        print("Warning: oasm.dev not found. Please install oasm.dev first:")
        print("  pip install oasm.dev")
        return None


def find_catseq_extensions() -> Optional[Path]:
    """Find the oasm_extensions directory in catseq package."""
    try:
        import catseq
        catseq_path = Path(catseq.__file__).parent
        extensions_path = catseq_path / "oasm_extensions"
        
        if extensions_path.exists():
            return extensions_path
        else:
            print(f"Warning: Extensions directory not found at {extensions_path}")
            return None
    except ImportError:
        print("Warning: catseq package not found.")
        return None


def install_oasm_extensions() -> bool:
    """
    Install OASM extension files to oasm.dev package.
    
    Returns:
        bool: True if installation succeeded, False otherwise
    """
    # Find paths
    oasm_dev_path = find_oasm_dev_path()
    extensions_path = find_catseq_extensions()
    
    if not oasm_dev_path or not extensions_path:
        return False
    
    # List of files to install (excluding __init__.py)
    extension_files = [f for f in extensions_path.glob("*") 
                      if f.is_file() and f.name != "__init__.py"]
    
    if not extension_files:
        print("No extension files found to install.")
        return True
    
    print(f"Installing OASM extensions to {oasm_dev_path}...")
    
    success_count = 0
    for file_path in extension_files:
        target_path = oasm_dev_path / file_path.name
        try:
            shutil.copy2(file_path, target_path)
            print(f"  ✓ Installed {file_path.name}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to install {file_path.name}: {e}")
    
    if success_count == len(extension_files):
        print(f"Successfully installed {success_count} extension file(s).")
        return True
    else:
        print(f"Installed {success_count}/{len(extension_files)} files. Some installations failed.")
        return False


def post_install():
    """
    Post-installation script entry point.
    This function is called after catseq is installed to deploy OASM extensions.
    """
    print("Running catseq post-installation setup...")
    
    success = install_oasm_extensions()
    
    if success:
        print("catseq setup completed successfully!")
        
        # Verify installation
        try:
            import oasm.dev.rwg
            print("Verification: oasm.dev.rwg is now available.")
        except ImportError:
            print("Warning: Could not import oasm.dev.rwg after installation.")
    else:
        print("catseq setup completed with warnings. Some extensions may not be available.")
        sys.exit(1)


def verify_installation():
    """Verify that OASM extensions are properly installed."""
    try:
        import oasm.dev
        oasm_dev_path = Path(oasm.dev.__file__).parent
        
        # Check for rwg.py specifically
        rwg_path = oasm_dev_path / "rwg.py"
        if rwg_path.exists():
            print(f"✓ rwg.py found at {rwg_path}")
            try:
                import oasm.dev.rwg
                print("✓ oasm.dev.rwg imports successfully")
                return True
            except Exception as e:
                print(f"✗ Failed to import oasm.dev.rwg: {e}")
                return False
        else:
            print(f"✗ rwg.py not found at {rwg_path}")
            return False
    except ImportError:
        print("✗ oasm.dev not available")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify_installation()
    else:
        post_install()