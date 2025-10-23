#!/usr/bin/env python3
"""
Test suite for async I/O optimization changes.
Tests both sync and async interfaces for backward compatibility.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Test results tracking
test_results = []


def test(name):
    """Decorator to track test results."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                test_results.append((name, True, None))
                print(f"✅ {name}")
                return result
            except Exception as e:
                test_results.append((name, False, str(e)))
                print(f"❌ {name}: {e}")
                return None
        return wrapper
    return decorator


@test("Import logger_core.config_manager")
def test_import_config_manager():
    # Import directly to avoid tkinter dependency from logger_core.__init__
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("config_manager", "logger_core/config_manager.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ConfigManager, module.get_config_manager


@test("Import logger_core.module_discovery")
def test_import_module_discovery():
    from logger_core.module_discovery import (
        discover_modules,
        discover_modules_async,
        validate_module_structure,
        validate_module_structure_async,
    )
    return discover_modules


@test("Import Modules.base.config_loader")
def test_import_config_loader():
    from Modules.base.config_loader import ConfigLoader
    return ConfigLoader


@test("Import Modules.Cameras.camera_core.recording.remux")
def test_import_camera_remux():
    from Modules.Cameras.camera_core.recording.remux import (
        calculate_actual_fps,
        remux_video_with_fps,
        auto_remux_recording,
    )
    return calculate_actual_fps


@test("ConfigManager - Instantiate")
def test_config_manager_init():
    from logger_core.config_manager import ConfigManager
    cm = ConfigManager()
    assert hasattr(cm, 'lock')
    assert hasattr(cm, 'read_config')
    assert hasattr(cm, 'read_config_async')
    assert hasattr(cm, 'write_config')
    assert hasattr(cm, 'write_config_async')
    return cm


@test("ConfigManager - Sync read_config (no file)")
def test_config_manager_sync_read():
    from logger_core.config_manager import ConfigManager
    cm = ConfigManager()
    config = cm.read_config(Path("/nonexistent/config.txt"))
    assert isinstance(config, dict)
    assert len(config) == 0
    return config


@test("ConfigManager - Sync write/read with temp file")
def test_config_manager_sync_write_read():
    from logger_core.config_manager import ConfigManager
    cm = ConfigManager()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("test_key = test_value\n")
        f.write("enabled = true\n")
        test_path = Path(f.name)

    try:
        # Read
        config = cm.read_config(test_path)
        assert config['test_key'] == 'test_value'
        assert cm.get_bool(config, 'enabled') == True

        # Write
        success = cm.write_config(test_path, {'test_key': 'updated_value', 'enabled': False})
        assert success == True

        # Read again
        config2 = cm.read_config(test_path)
        assert config2['test_key'] == 'updated_value'
        assert cm.get_bool(config2, 'enabled') == False

        return config2
    finally:
        test_path.unlink()


@test("ConfigManager - Async methods exist and are coroutines")
def test_config_manager_async_methods():
    from logger_core.config_manager import ConfigManager
    import inspect

    cm = ConfigManager()
    assert inspect.iscoroutinefunction(cm.read_config_async)
    assert inspect.iscoroutinefunction(cm.write_config_async)
    return True


@test("ConfigLoader - Sync load")
def test_config_loader_sync():
    from Modules.base.config_loader import ConfigLoader

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("# Test config\n")
        f.write("key1 = value1\n")
        f.write("enabled = true\n")
        test_path = Path(f.name)

    try:
        config = ConfigLoader.load(test_path)
        assert 'key1' in config
        assert config['key1'] == 'value1'
        assert config['enabled'] == True
        return config
    finally:
        test_path.unlink()


@test("ConfigLoader - Async wrapper exists")
def test_config_loader_async():
    from Modules.base.config_loader import ConfigLoader
    import inspect

    assert hasattr(ConfigLoader, 'load_async')
    assert inspect.iscoroutinefunction(ConfigLoader.load_async)
    assert hasattr(ConfigLoader, 'update_config_values_async')
    assert inspect.iscoroutinefunction(ConfigLoader.update_config_values_async)
    return True


@test("Module Discovery - discover_modules works")
def test_discover_modules():
    from logger_core.module_discovery import discover_modules

    # This will search for actual modules
    modules = discover_modules()
    assert isinstance(modules, list)
    # Should find at least some modules (Cameras, NoteTaker, etc.)
    print(f"  Found {len(modules)} modules: {[m.name for m in modules]}")
    return modules


@test("Module Discovery - Async wrapper exists")
def test_discover_modules_async_exists():
    from logger_core.module_discovery import discover_modules_async
    import inspect

    assert inspect.iscoroutinefunction(discover_modules_async)
    return True


@test("Camera Remux - Functions are async coroutines")
def test_camera_remux_async():
    from Modules.Cameras.camera_core.recording.remux import (
        calculate_actual_fps,
        remux_video_with_fps,
        auto_remux_recording,
    )
    import inspect

    assert inspect.iscoroutinefunction(calculate_actual_fps)
    assert inspect.iscoroutinefunction(remux_video_with_fps)
    assert inspect.iscoroutinefunction(auto_remux_recording)
    return True


# Async tests
async def async_test_config_manager_read():
    """Test ConfigManager async read."""
    from logger_core.config_manager import ConfigManager

    cm = ConfigManager()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("async_test = success\n")
        test_path = Path(f.name)

    try:
        config = await cm.read_config_async(test_path)
        assert config['async_test'] == 'success'
        print("✅ ConfigManager - Async read_config_async")
        test_results.append(("ConfigManager - Async read_config_async", True, None))
        return config
    except Exception as e:
        print(f"❌ ConfigManager - Async read_config_async: {e}")
        test_results.append(("ConfigManager - Async read_config_async", False, str(e)))
        raise
    finally:
        test_path.unlink()


async def async_test_config_manager_write():
    """Test ConfigManager async write."""
    from logger_core.config_manager import ConfigManager

    cm = ConfigManager()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("original = value\n")
        test_path = Path(f.name)

    try:
        success = await cm.write_config_async(test_path, {'original': 'updated', 'new_key': 'new_value'})
        assert success == True

        config = await cm.read_config_async(test_path)
        assert config['original'] == 'updated'
        assert config['new_key'] == 'new_value'

        print("✅ ConfigManager - Async write_config_async")
        test_results.append(("ConfigManager - Async write_config_async", True, None))
        return config
    except Exception as e:
        print(f"❌ ConfigManager - Async write_config_async: {e}")
        test_results.append(("ConfigManager - Async write_config_async", False, str(e)))
        raise
    finally:
        test_path.unlink()


async def async_test_config_loader():
    """Test ConfigLoader async wrapper."""
    from Modules.base.config_loader import ConfigLoader

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("async_key = async_value\n")
        test_path = Path(f.name)

    try:
        config = await ConfigLoader.load_async(test_path)
        assert 'async_key' in config
        assert config['async_key'] == 'async_value'

        print("✅ ConfigLoader - Async load_async")
        test_results.append(("ConfigLoader - Async load_async", True, None))
        return config
    except Exception as e:
        print(f"❌ ConfigLoader - Async load_async: {e}")
        test_results.append(("ConfigLoader - Async load_async", False, str(e)))
        raise
    finally:
        test_path.unlink()


async def async_test_module_discovery():
    """Test module discovery async wrapper."""
    from logger_core.module_discovery import discover_modules_async

    try:
        modules = await discover_modules_async()
        assert isinstance(modules, list)

        print(f"✅ Module Discovery - Async discover_modules_async ({len(modules)} modules)")
        test_results.append(("Module Discovery - Async discover_modules_async", True, None))
        return modules
    except Exception as e:
        print(f"❌ Module Discovery - Async discover_modules_async: {e}")
        test_results.append(("Module Discovery - Async discover_modules_async", False, str(e)))
        raise


async def run_async_tests():
    """Run all async tests."""
    print("\n" + "="*60)
    print("ASYNC TESTS")
    print("="*60)

    await async_test_config_manager_read()
    await async_test_config_manager_write()
    await async_test_config_loader()
    await async_test_module_discovery()


def main():
    """Run all tests."""
    print("="*60)
    print("ASYNC I/O OPTIMIZATION - TEST SUITE")
    print("="*60)
    print("\nSYNC TESTS")
    print("="*60)

    # Run sync tests
    test_import_config_manager()
    test_import_module_discovery()
    test_import_config_loader()
    test_import_camera_remux()
    test_config_manager_init()
    test_config_manager_sync_read()
    test_config_manager_sync_write_read()
    test_config_manager_async_methods()
    test_config_loader_sync()
    test_config_loader_async()
    test_discover_modules()
    test_discover_modules_async_exists()
    test_camera_remux_async()

    # Run async tests
    asyncio.run(run_async_tests())

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(1 for _, success, _ in test_results if success)
    failed = sum(1 for _, success, _ in test_results if not success)
    total = len(test_results)

    print(f"\nTotal Tests: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed > 0:
        print("\nFailed Tests:")
        for name, success, error in test_results:
            if not success:
                print(f"  ❌ {name}: {error}")

    print("\n" + "="*60)

    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("⚠️  SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
