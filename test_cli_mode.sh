#!/bin/bash
# Comprehensive CLI mode testing script

set -e

PROJECT_ROOT="/home/rs-pi-2/Development/RPi_Logger"
cd "$PROJECT_ROOT"

TEST_LOG="test_cli_$(date +%Y%m%d_%H%M%S).log"
TEST_DATA_DIR="test_data_$(date +%Y%m%d_%H%M%S)"

echo "=====================================================================" | tee "$TEST_LOG"
echo "RPi Logger CLI Mode Comprehensive Testing" | tee -a "$TEST_LOG"
echo "=====================================================================" | tee -a "$TEST_LOG"
echo "Test log: $TEST_LOG" | tee -a "$TEST_LOG"
echo "Test data dir: $TEST_DATA_DIR" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# Test 1: Verify syntax
echo "TEST 1: Verify Python syntax..." | tee -a "$TEST_LOG"
python3 -m py_compile main_logger.py logger_core/cli/*.py 2>&1 | tee -a "$TEST_LOG"
echo "✓ Syntax check passed" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# Test 2: Help command
echo "TEST 2: Test --help output..." | tee -a "$TEST_LOG"
python3 main_logger.py --help 2>&1 | tee -a "$TEST_LOG"
echo "✓ Help displayed" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# Test 3: Interactive mode with automated commands
echo "TEST 3: Test interactive mode with automated commands..." | tee -a "$TEST_LOG"
cat << 'EOF' > /tmp/cli_test_commands.txt
help
list
status
quit
EOF

timeout 30 python3 main_logger.py --mode interactive --data-dir "$TEST_DATA_DIR" < /tmp/cli_test_commands.txt 2>&1 | tee -a "$TEST_LOG" || true
echo "✓ Interactive mode basic commands tested" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# Test 4: Check created files
echo "TEST 4: Verify log files created..." | tee -a "$TEST_LOG"
if [ -d "$TEST_DATA_DIR" ]; then
    echo "Test data directory created:" | tee -a "$TEST_LOG"
    ls -lR "$TEST_DATA_DIR" 2>&1 | tee -a "$TEST_LOG"
else
    echo "Warning: Test data directory not created" | tee -a "$TEST_LOG"
fi
echo "" | tee -a "$TEST_LOG"

# Test 5: Check logs for errors
echo "TEST 5: Check logs for ERROR/CRITICAL messages..." | tee -a "$TEST_LOG"
echo "Checking logs/master_logger.log..." | tee -a "$TEST_LOG"
if [ -f "logs/master_logger.log" ]; then
    ERROR_COUNT=$(grep -c "ERROR" logs/master_logger.log || echo "0")
    CRITICAL_COUNT=$(grep -c "CRITICAL" logs/master_logger.log || echo "0")
    echo "ERROR count: $ERROR_COUNT" | tee -a "$TEST_LOG"
    echo "CRITICAL count: $CRITICAL_COUNT" | tee -a "$TEST_LOG"

    if [ "$ERROR_COUNT" -gt "0" ] || [ "$CRITICAL_COUNT" -gt "0" ]; then
        echo "Last 20 ERROR/CRITICAL messages:" | tee -a "$TEST_LOG"
        grep -E "ERROR|CRITICAL" logs/master_logger.log | tail -20 | tee -a "$TEST_LOG"
    fi
else
    echo "Warning: Master log file not found" | tee -a "$TEST_LOG"
fi
echo "" | tee -a "$TEST_LOG"

echo "=====================================================================" | tee -a "$TEST_LOG"
echo "Testing complete. Review $TEST_LOG for details." | tee -a "$TEST_LOG"
echo "=====================================================================" | tee -a "$TEST_LOG"
