# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for RPi Logger.

Build commands:
  - Windows/Linux: pyinstaller rpi_logger.spec
  - macOS: pyinstaller rpi_logger.spec (creates .app bundle)

The output will be in the 'dist' folder.
"""

import sys
from pathlib import Path

block_cipher = None

# Determine platform-specific settings
is_windows = sys.platform == 'win32'
is_macos = sys.platform == 'darwin'
is_linux = sys.platform.startswith('linux')

# Application metadata
APP_NAME = 'RPi Logger'
APP_BUNDLE_ID = 'com.rpilogger.app'
APP_VERSION = '0.1.0'

# Paths
ROOT = Path(SPECPATH)
PACKAGE_DIR = ROOT / 'rpi_logger'

# Helper to collect all Python files from a module directory (recursively)
def collect_module_files(module_name):
    """Collect all .py files and config.txt from a module directory, including subdirectories."""
    module_dir = PACKAGE_DIR / 'modules' / module_name
    files = []
    if module_dir.exists():
        # Recursively collect all .py files
        for py_file in module_dir.rglob('*.py'):
            # Calculate the relative path from the module directory
            rel_path = py_file.relative_to(module_dir)
            # Destination is the same relative structure under rpi_logger/modules/module_name
            if rel_path.parent == Path('.'):
                dest = f'rpi_logger/modules/{module_name}'
            else:
                dest = f'rpi_logger/modules/{module_name}/{rel_path.parent}'
            files.append((str(py_file), dest))
        # Also collect config.txt if present
        config = module_dir / 'config.txt'
        if config.exists():
            files.append((str(config), f'rpi_logger/modules/{module_name}'))
    return files

# Collect all data files (config files, images, module Python files, etc.)
datas = [
    # Root config file
    (str(ROOT / 'config.txt'), '.'),
    # Logo for the UI
    (str(PACKAGE_DIR / 'core' / 'ui' / 'logo_100.png'), 'rpi_logger/core/ui'),
]

# Add all Python files from each module directory
# (modules use local imports like "from runtime import ..." so we need all .py files)
for module_name in ['Audio', 'Cameras', 'DRT', 'EyeTracker', 'GPS', 'Notes', 'stub (codex)']:
    datas.extend(collect_module_files(module_name))

# Include entire vmc package from stub (codex) - needed by multiple modules as top-level import
datas.append((str(PACKAGE_DIR / 'modules' / 'stub (codex)' / 'vmc'), 'vmc'))

# Helper to collect all submodule imports from a module directory
def collect_module_imports(module_name):
    """Collect all submodule import paths from a module directory."""
    module_dir = PACKAGE_DIR / 'modules' / module_name
    imports = [f'rpi_logger.modules.{module_name}']
    if module_dir.exists():
        for py_file in module_dir.rglob('*.py'):
            if py_file.name == '__init__.py':
                # Package init
                rel_path = py_file.parent.relative_to(module_dir)
                if rel_path == Path('.'):
                    continue  # Already added
                import_path = f'rpi_logger.modules.{module_name}.{str(rel_path).replace("/", ".")}'
            else:
                # Module file
                rel_path = py_file.relative_to(module_dir)
                module_path = str(rel_path.with_suffix('')).replace('/', '.')
                import_path = f'rpi_logger.modules.{module_name}.{module_path}'
            imports.append(import_path)
    return imports

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # Core dependencies
    'numpy',
    'cv2',
    'sounddevice',
    'soundfile',
    'pandas',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'psutil',
    'aiofiles',
    'serial_asyncio',
    'matplotlib',
    'matplotlib.backends.backend_tkagg',
    # Tkinter
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkintermapview',
    # async-tkinter-loop
    'async_tkinter_loop',
    # Pupil Labs
    'pupil_labs',
    'pupil_labs.realtime_api',
    # Core rpi_logger modules
    'rpi_logger',
    'rpi_logger.app',
    'rpi_logger.app.master',
    'rpi_logger.core',
    'rpi_logger.core.logger_system',
    'rpi_logger.core.module_discovery',
    'rpi_logger.core.module_manager',
    'rpi_logger.core.module_process',
    'rpi_logger.core.config_manager',
    'rpi_logger.core.session_manager',
    'rpi_logger.core.cli',
    'rpi_logger.core.ui',
    'rpi_logger.core.ui.main_window',
    'rpi_logger.modules',
    'rpi_logger.modules.base',
    'rpi_logger.tools',
    # vmc module from stub (codex) - used by multiple modules
    'vmc',
    'vmc.supervisor',
    'vmc.controller',
    'vmc.model',
    'vmc.view',
    'vmc.preferences',
    'vmc.runtime',
    'vmc.runtime_helpers',
    'vmc.constants',
    'vmc.migration',
]

# Dynamically add all submodule imports for each module
for module_name in ['Audio', 'Cameras', 'DRT', 'EyeTracker', 'GPS', 'Notes', 'stub (codex)']:
    hiddenimports.extend(collect_module_imports(module_name))

# Exclude unnecessary modules to reduce size
excludes = [
    'pytest',
    'test',
    'tests',
    'unittest',
    'doctest',
]

# Add stub (codex) directory to path for vmc module discovery
stub_path = ROOT / 'rpi_logger' / 'modules' / 'stub (codex)'
if stub_path.exists() and str(stub_path) not in sys.path:
    sys.path.insert(0, str(stub_path))

a = Analysis(
    [str(PACKAGE_DIR / '__main__.py')],
    pathex=[str(ROOT), str(stub_path)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Platform-specific executable settings
if is_macos:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='RPi Logger',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,  # No terminal window on macOS
        disable_windowed_traceback=False,
        argv_emulation=True,  # Support file drops on macOS
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='RPi Logger',
    )

    app = BUNDLE(
        coll,
        name='RPi Logger.app',
        icon=None,  # Add icon path here if you have one: 'assets/icon.icns'
        bundle_identifier=APP_BUNDLE_ID,
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,  # Support dark mode
        },
    )

elif is_windows:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='RPi Logger',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,  # No console window
        disable_windowed_traceback=False,
        icon=None,  # Add icon path here if you have one: 'assets/icon.ico'
        version_info=None,  # Can add version info file
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='RPi Logger',
    )

else:  # Linux / Raspberry Pi
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='rpi-logger',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='rpi-logger',
    )
