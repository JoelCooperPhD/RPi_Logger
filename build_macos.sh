#!/bin/bash
# Build RPi Logger for macOS using Nuitka

set -e

# Activate virtual environment
source .venv/bin/activate

# Clean previous builds
rm -rf build/ dist/ RPi_Logger.app RPi_Logger.dist RPi_Logger.build

# Create icon if icon.png exists
if [ -f "rpi_logger/core/ui/icon.png" ] && ! [ -f "rpi_logger/core/ui/icon.icns" ]; then
    echo "Creating macOS icon..."
    mkdir -p icon.iconset
    sips -z 16 16   rpi_logger/core/ui/icon.png --out icon.iconset/icon_16x16.png
    sips -z 32 32   rpi_logger/core/ui/icon.png --out icon.iconset/icon_16x16@2x.png
    sips -z 32 32   rpi_logger/core/ui/icon.png --out icon.iconset/icon_32x32.png
    sips -z 64 64   rpi_logger/core/ui/icon.png --out icon.iconset/icon_32x32@2x.png
    sips -z 128 128 rpi_logger/core/ui/icon.png --out icon.iconset/icon_128x128.png
    sips -z 256 256 rpi_logger/core/ui/icon.png --out icon.iconset/icon_128x128@2x.png
    sips -z 256 256 rpi_logger/core/ui/icon.png --out icon.iconset/icon_256x256.png
    sips -z 512 512 rpi_logger/core/ui/icon.png --out icon.iconset/icon_256x256@2x.png
    sips -z 512 512 rpi_logger/core/ui/icon.png --out icon.iconset/icon_512x512.png
    sips -z 1024 1024 rpi_logger/core/ui/icon.png --out icon.iconset/icon_512x512@2x.png
    iconutil -c icns icon.iconset -o rpi_logger/core/ui/icon.icns
    rm -rf icon.iconset
fi

# Determine icon option
ICON_OPT="--macos-app-icon=none"
if [ -f "rpi_logger/core/ui/icon.icns" ]; then
    ICON_OPT="--macos-app-icon=rpi_logger/core/ui/icon.icns"
fi

echo "Building RPi Logger with Nuitka for macOS..."

python -m nuitka \
    --standalone \
    --assume-yes-for-downloads \
    --macos-create-app-bundle \
    --macos-app-name="Logger" \
    --macos-app-version="0.1.0" \
    $ICON_OPT \
    --lto=yes \
    --enable-plugin=tk-inter \
    --nofollow-import-to=pytest \
    --nofollow-import-to=unittest \
    --nofollow-import-to=doctest \
    --nofollow-import-to=test \
    --nofollow-import-to=tests \
    --nofollow-import-to=_pytest \
    --nofollow-import-to=numpy.testing \
    --nofollow-import-to=numpy.f2py \
    --nofollow-import-to=numpy.distutils \
    --nofollow-import-to=matplotlib.backends.backend_qt5agg \
    --nofollow-import-to=matplotlib.backends.backend_qt5 \
    --nofollow-import-to=matplotlib.backends.backend_qt \
    --nofollow-import-to=matplotlib.backends.backend_gtk3 \
    --nofollow-import-to=matplotlib.backends.backend_gtk \
    --nofollow-import-to=matplotlib.backends.backend_wx \
    --nofollow-import-to=matplotlib.backends.backend_webagg \
    --nofollow-import-to=matplotlib.backends.backend_pdf \
    --nofollow-import-to=matplotlib.backends.backend_ps \
    --nofollow-import-to=matplotlib.backends.backend_svg \
    --nofollow-import-to=matplotlib.backends.backend_pgf \
    --nofollow-import-to=PIL.ImageQt \
    --nofollow-import-to=tkintermapview \
    --nofollow-import-to=scipy \
    --nofollow-import-to=scipy.stats \
    --nofollow-import-to=scipy.optimize \
    --nofollow-import-to=scipy.interpolate \
    --nofollow-import-to=pandas \
    --nofollow-import-to=pandas.core \
    --nofollow-import-to=IPython \
    --nofollow-import-to=jupyter \
    --nofollow-import-to=notebook \
    --noinclude-custom-mode=zeroconf:bytecode \
    --include-data-dir=rpi_logger/core/ui=rpi_logger/core/ui \
    --include-data-file=config.txt=config.txt \
    --include-data-dir=rpi_logger/modules=rpi_logger/modules \
    --include-data-file=rpi_logger/modules/Audio/main_audio.py=rpi_logger/modules/Audio/main_audio.py \
    --include-data-file=rpi_logger/modules/Cameras/main_cameras.py=rpi_logger/modules/Cameras/main_cameras.py \
    --include-data-file=rpi_logger/modules/DRT/main_drt.py=rpi_logger/modules/DRT/main_drt.py \
    --include-data-file=rpi_logger/modules/EyeTracker/main_eye_tracker.py=rpi_logger/modules/EyeTracker/main_eye_tracker.py \
    --include-data-file=rpi_logger/modules/GPS/main_gps.py=rpi_logger/modules/GPS/main_gps.py \
    --include-data-file=rpi_logger/modules/Notes/main_notes.py=rpi_logger/modules/Notes/main_notes.py \
    --include-data-file=rpi_logger/modules/VOG/main_vog.py=rpi_logger/modules/VOG/main_vog.py \
    "--include-data-file=rpi_logger/modules/stub (codex)/main_stub_codex.py=rpi_logger/modules/stub (codex)/main_stub_codex.py" \
    --output-dir=dist \
    rpi_logger/__main__.py

echo ""
echo "Build complete!"
echo "Application bundle: dist/__main__.app (rename to Logger.app)"
mv dist/__main__.app dist/Logger.app 2>/dev/null || true
echo "Final location: dist/Logger.app"
