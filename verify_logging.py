
import logging
import sys
from rpi_logger.core.logging_utils import get_module_logger, ensure_structured_logger

def verify_logging():
    print("Verifying logging configuration...")
    
    # Test get_module_logger
    logger = get_module_logger("TestModule")
    print(f"Logger name: {logger.name}")
    print(f"Logger component: {logger.component}")
    
    if logger.name != "rpi_logger.TestModule":
        print("FAIL: Logger name incorrect")
        return False
        
    if logger.component != "TestModule":
        print("FAIL: Logger component incorrect")
        return False

    # Test ensure_structured_logger
    raw_logger = logging.Logger("rpi_logger.Raw")
    structured = ensure_structured_logger(raw_logger)
    print(f"Structured logger name: {structured.name}")
    
    if structured.name != "rpi_logger.Raw":
        print("FAIL: Structured logger name incorrect")
        return False

    print("PASS: Logging verification successful")
    return True

if __name__ == "__main__":
    if not verify_logging():
        sys.exit(1)
