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
    Install OASM extension files to appropriate locations.
    
    Returns:
        bool: True if installation succeeded, False otherwise
    """
    # Find paths
    oasm_dev_path = find_oasm_dev_path()
    extensions_path = find_catseq_extensions()
    
    if not oasm_dev_path or not extensions_path:
        return False
    
    success_count = 0
    total_files = 0
    site_packages = oasm_dev_path.parent.parent  # site-packages directory (oasm/dev -> oasm -> site-packages)
    
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
        try:
            target_hdl = site_packages / "hdl"
            
            # Remove existing hdl directory if it exists
            if target_hdl.exists():
                shutil.rmtree(target_hdl)
            
            shutil.copytree(hdl_dir, target_hdl)
            print(f"  ✓ Installed hdl directory to {target_hdl}")
            success_count += 1
            total_files += 1
        except Exception as e:
            print(f"  ✗ Failed to install hdl directory: {e}")
            total_files += 1
    
    # 3. Install veri.py to site-packages root with lib path correction
    veri_file = extensions_path / "veri.py"
    if veri_file.exists():
        try:
            target_veri = site_packages / "veri.py"
            
            # Read veri.py and update lib path
            with open(veri_file, 'r') as f:
                veri_content = f.read()
            
            # Replace the hardcoded lib path with dynamic path
            corrected_lib_path = str(site_packages / "hdl" / "rtmq2" / sys.platform)
            veri_content = veri_content.replace(
                'lib=r"C:\\Users\\Jiang\\Documents\\rtmq\\py\\archon\\hdl\\rtmq2\\lib"',
                f'lib=r"{corrected_lib_path}"'
            )
            
            # Write corrected veri.py
            with open(target_veri, 'w') as f:
                f.write(veri_content)
            
            print(f"  ✓ Installed veri.py to {target_veri} (lib path corrected)")
            success_count += 1
            total_files += 1
        except Exception as e:
            print(f"  ✗ Failed to install veri.py: {e}")
            total_files += 1
    
    if total_files == 0:
        print("No extension files found to install.")
        return True
    
    if success_count == total_files:
        print(f"Successfully installed {success_count} extension(s).")
        return True
    else:
        print(f"Installed {success_count}/{total_files} extensions. Some installations failed.")
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
        success = verify_installation()
        sys.exit(0 if success else 1)
    else:
        post_install()