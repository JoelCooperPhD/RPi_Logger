# PyInstaller hook for the vmc module
# The vmc package is located in a non-standard path: rpi_logger/modules/stub (codex)/vmc
# This hook ensures it gets collected properly

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import sys
from pathlib import Path

# Add the stub directory to the path so vmc can be found
stub_path = Path(__file__).parent.parent / 'rpi_logger' / 'modules' / 'stub (codex)'
if stub_path.exists() and str(stub_path) not in sys.path:
    sys.path.insert(0, str(stub_path))

# Now collect all vmc submodules
hiddenimports = collect_submodules('vmc')
datas = collect_data_files('vmc')
