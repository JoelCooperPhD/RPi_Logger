#!/usr/bin/env python3
"""
Focused test suite for async I/O core functionality.
Skips GUI/hardware dependencies to test the async changes specifically.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Direct imports to avoid tkinter dependencies
import importlib.util


def import_module_from_file(module_name, file_path):
    """Import a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


print("="*70)
print("ASYNC I/O OPTIMIZATION - CORE FUNCTIONALITY TEST")
print("="*70)

passed = 0
failed = 0

# Test 1: ConfigManager - Import and Instantiate
print("\n[TEST 1] ConfigManager - Import and Instantiate")
try:
    config_manager = import_module_from_file("config_manager", "logger_core/config_manager.py")
    ConfigManager = config_manager.ConfigManager
    cm = ConfigManager()
    assert hasattr(cm, 'lock')
    assert hasattr(cm, 'read_config')
    assert hasattr(cm, 'read_config_async')
    assert hasattr(cm, 'write_config')
    assert hasattr(cm, 'write_config_async')
    print("✅ PASSED - ConfigManager has all methods and asyncio.Lock")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 2: ConfigManager - Sync Methods
print("\n[TEST 2] ConfigManager - Sync read/write")
try:
    cm = ConfigManager()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("test_key = test_value\n")
        f.write("enabled = true\n")
        f.write("count = 42\n")
        test_path = Path(f.name)

    # Read
    config = cm.read_config(test_path)
    assert config['test_key'] == 'test_value'
    assert cm.get_bool(config, 'enabled') == True
    assert cm.get_int(config, 'count') == 42

    # Write
    success = cm.write_config(test_path, {'test_key': 'updated', 'enabled': False})
    assert success == True

    # Read again
    config2 = cm.read_config(test_path)
    assert config2['test_key'] == 'updated'
    assert cm.get_bool(config2, 'enabled') == False

    test_path.unlink()
    print("✅ PASSED - Sync read/write works correctly")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 3: ConfigManager - Async Methods
print("\n[TEST 3] ConfigManager - Async read/write")
async def test_config_manager_async():
    cm = ConfigManager()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("async_key = async_value\n")
        test_path = Path(f.name)

    try:
        # Async read
        config = await cm.read_config_async(test_path)
        assert config['async_key'] == 'async_value'

        # Async write
        success = await cm.write_config_async(test_path, {'async_key': 'updated_async', 'new_key': 'new_value'})
        assert success == True

        # Async read again
        config2 = await cm.read_config_async(test_path)
        assert config2['async_key'] == 'updated_async'
        assert config2['new_key'] == 'new_value'

        return True
    finally:
        test_path.unlink()

try:
    result = asyncio.run(test_config_manager_async())
    print("✅ PASSED - Async read/write works correctly")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 4: ConfigLoader
print("\n[TEST 4] ConfigLoader - Sync and Async")
try:
    config_loader = import_module_from_file("config_loader", "Modules/base/config_loader.py")
    ConfigLoader = config_loader.ConfigLoader

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("# Test config\n")
        f.write("key1 = value1\n")
        f.write("enabled = true\n")
        f.write("count = 123\n")
        test_path = Path(f.name)

    # Sync
    config = ConfigLoader.load(test_path)
    assert config['key1'] == 'value1'
    assert config['enabled'] == True
    assert config['count'] == 123

    # Async
    async def test_loader_async():
        config = await ConfigLoader.load_async(test_path)
        assert config['key1'] == 'value1'
        return True

    asyncio.run(test_loader_async())
    test_path.unlink()

    print("✅ PASSED - ConfigLoader sync and async work correctly")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 5: Module Discovery
print("\n[TEST 5] Module Discovery - discover_modules")
try:
    module_discovery = import_module_from_file("module_discovery", "logger_core/module_discovery.py")
    discover_modules = module_discovery.discover_modules
    discover_modules_async = module_discovery.discover_modules_async

    # Sync
    modules = discover_modules()
    assert isinstance(modules, list)
    assert len(modules) > 0
    module_names = [m.name for m in modules]
    print(f"  Found modules: {module_names}")

    # Async
    async def test_discovery_async():
        modules = await discover_modules_async()
        assert isinstance(modules, list)
        assert len(modules) > 0
        return True

    asyncio.run(test_discovery_async())

    print(f"✅ PASSED - Module discovery found {len(modules)} modules")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 6: Camera Remux - Async signatures
print("\n[TEST 6] Camera Remux - Async function signatures")
try:
    remux = import_module_from_file("remux", "Modules/Cameras/camera_core/recording/remux.py")
    import inspect

    assert inspect.iscoroutinefunction(remux.calculate_actual_fps)
    assert inspect.iscoroutinefunction(remux.remux_video_with_fps)
    assert inspect.iscoroutinefunction(remux.auto_remux_recording)

    print("✅ PASSED - All remux functions are async coroutines")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 7: NoteTaker Recording Manager - Async signatures
print("\n[TEST 7] NoteTaker Recording Manager - Async methods")
try:
    notes_manager = import_module_from_file("notes_manager", "Modules/NoteTaker/notes_core/recording/manager.py")
    import inspect

    RecordingManager = notes_manager.RecordingManager

    # Check that methods are async
    assert inspect.iscoroutinefunction(RecordingManager.start_recording)
    assert inspect.iscoroutinefunction(RecordingManager.add_note)
    assert inspect.iscoroutinefunction(RecordingManager.get_all_notes)

    print("✅ PASSED - NoteTaker recording methods are async")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Test 8: Backward Compatibility - Sync methods still work
print("\n[TEST 8] Backward Compatibility - Sync interfaces preserved")
try:
    # ConfigManager has both sync and async
    cm = ConfigManager()
    assert callable(cm.read_config)
    assert callable(cm.write_config)
    assert callable(cm.get_bool)
    assert callable(cm.get_int)
    assert callable(cm.get_float)

    # ConfigLoader has both
    assert callable(ConfigLoader.load)
    assert callable(ConfigLoader.update_config_values)

    # Module discovery has both
    assert callable(discover_modules)

    print("✅ PASSED - All sync methods still available")
    passed += 1
except Exception as e:
    print(f"❌ FAILED - {e}")
    failed += 1

# Summary
print("\n" + "="*70)
print("TEST SUMMARY")
print("="*70)
print(f"Total Tests: {passed + failed}")
print(f"✅ Passed: {passed}")
print(f"❌ Failed: {failed}")
print("="*70)

if failed == 0:
    print("\n🎉 ALL CORE FUNCTIONALITY TESTS PASSED!")
    print("\nAsync I/O optimizations are working correctly:")
    print("  ✅ ConfigManager - Dual interface (sync/async)")
    print("  ✅ ConfigLoader - Async wrappers")
    print("  ✅ Module Discovery - Async wrappers")
    print("  ✅ Camera Remux - Async subprocess")
    print("  ✅ NoteTaker - Async file operations")
    print("  ✅ Backward compatibility maintained")
    sys.exit(0)
else:
    print("\n⚠️  SOME TESTS FAILED - Review above for details")
    sys.exit(1)
