#!/bin/bash
################################################################################
# RPi Logger Startup Wrapper Script
#
# Reads config.txt to determine startup mode and launches the logger.
# Used by systemd service for auto-start on boot.
################################################################################

set -e

# Determine project directory (where this script lives)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Config file
CONFIG_FILE="$SCRIPT_DIR/config.txt"

# Default values
MODE="interactive"
LOG_LEVEL="info"
DATA_DIR="data"

# Read config file
if [ -f "$CONFIG_FILE" ]; then
    # Extract auto_start_mode
    if grep -q "^auto_start_mode" "$CONFIG_FILE"; then
        MODE=$(grep "^auto_start_mode" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d ' ' | tr -d '\r')
    fi

    # Extract log_level
    if grep -q "^log_level" "$CONFIG_FILE"; then
        LOG_LEVEL=$(grep "^log_level" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d ' ' | tr -d '\r')
    fi

    # Extract data_dir
    if grep -q "^data_dir" "$CONFIG_FILE"; then
        DATA_DIR=$(grep "^data_dir" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d ' ' | tr -d '\r')
    fi
fi

# Validate mode
case "$MODE" in
    gui|interactive|cli)
        ;;
    *)
        echo "Invalid auto_start_mode in config: '$MODE'. Using 'interactive'" >&2
        MODE="interactive"
        ;;
esac

# Find Python (prefer venv if exists)
PYTHON="python3"
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

# Log startup
echo "================================================"
echo "RPi Logger Auto-Start"
echo "================================================"
echo "Mode:      $MODE"
echo "Data dir:  $DATA_DIR"
echo "Log level: $LOG_LEVEL"
echo "Python:    $PYTHON"
echo "Display:   $DISPLAY"
echo "================================================"

# Launch logger
exec $PYTHON main_logger.py \
    --mode "$MODE" \
    --data-dir "$DATA_DIR" \
    --log-level "$LOG_LEVEL" \
    --console
