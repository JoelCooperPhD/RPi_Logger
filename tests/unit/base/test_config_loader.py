"""Unit tests for ConfigLoader in base module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestConfigLoaderParsing:
    """Test ConfigLoader value parsing."""

    def test_parse_value_bool_true(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        for val in ['true', 'True', 'TRUE', 'yes', 'Yes', 'on', 'ON', '1']:
            assert ConfigLoader._parse_value(val) is True

    def test_parse_value_bool_false(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        for val in ['false', 'False', 'FALSE', 'no', 'No', 'off', 'OFF', '0']:
            assert ConfigLoader._parse_value(val) is False

    def test_parse_value_int(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value('42') == 42
        assert ConfigLoader._parse_value('-10') == -10
        assert ConfigLoader._parse_value('0') is False  # Treated as bool

    def test_parse_value_float(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value('3.14') == pytest.approx(3.14)
        assert ConfigLoader._parse_value('-0.5') == pytest.approx(-0.5)

    def test_parse_value_string(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value('hello') == 'hello'
        assert ConfigLoader._parse_value('/dev/ttyUSB0') == '/dev/ttyUSB0'


class TestConfigLoaderTypedParsing:
    """Test ConfigLoader typed value parsing."""

    def test_parse_with_type_bool(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('true', bool) is True
        assert ConfigLoader._parse_value_with_type('false', bool) is False
        assert ConfigLoader._parse_value_with_type('yes', bool) is True
        assert ConfigLoader._parse_value_with_type('no', bool) is False

    def test_parse_with_type_int(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('42', int) == 42
        assert ConfigLoader._parse_value_with_type('0xFF', int) == 255
        assert ConfigLoader._parse_value_with_type('0b1010', int) == 10
        assert ConfigLoader._parse_value_with_type('0o17', int) == 15

    def test_parse_with_type_int_invalid(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('invalid', int) == 0

    def test_parse_with_type_float(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('3.14', float) == pytest.approx(3.14)
        assert ConfigLoader._parse_value_with_type('-2.5', float) == pytest.approx(-2.5)

    def test_parse_with_type_float_invalid(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('invalid', float) == 0.0

    def test_parse_with_type_string(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._parse_value_with_type('hello', str) == 'hello'


class TestConfigLoaderLoad:
    """Test ConfigLoader.load method."""

    def test_load_nonexistent_with_defaults(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "nonexistent.txt"
        defaults = {'key1': 'value1', 'key2': 42}

        result = ConfigLoader.load(config_path, defaults)

        assert result == defaults

    def test_load_nonexistent_without_defaults(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "nonexistent.txt"

        result = ConfigLoader.load(config_path)

        assert result == {}

    def test_load_basic_config(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("key1=value1\nkey2=42\nenabled=true\n")

        result = ConfigLoader.load(config_path)

        assert result['key1'] == 'value1'
        assert result['key2'] == 42
        assert result['enabled'] is True

    def test_load_with_defaults(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("key1=override\n")
        defaults = {'key1': 'default', 'key2': 100}

        result = ConfigLoader.load(config_path, defaults)

        assert result['key1'] == 'override'
        assert result['key2'] == 100

    def test_load_with_comments(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("# This is a comment\nkey=value # inline comment\n")

        result = ConfigLoader.load(config_path)

        assert result['key'] == 'value'

    def test_load_skips_invalid_lines(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("key1=value1\ninvalid line without equals\nkey2=value2\n")

        result = ConfigLoader.load(config_path)

        assert result['key1'] == 'value1'
        assert result['key2'] == 'value2'
        assert 'invalid' not in result

    def test_load_strict_mode(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("known=value\nunknown=value\n")
        defaults = {'known': 'default'}

        result = ConfigLoader.load(config_path, defaults, strict=True)

        assert result['known'] == 'value'
        assert 'unknown' not in result

    def test_load_preserves_type_from_defaults(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("count=5\nratio=2.5\nflag=yes\n")
        defaults = {'count': 0, 'ratio': 0.0, 'flag': False}

        result = ConfigLoader.load(config_path, defaults)

        assert isinstance(result['count'], int)
        assert isinstance(result['ratio'], float)
        assert isinstance(result['flag'], bool)


class TestConfigLoaderAsync:
    """Test ConfigLoader async methods."""

    @pytest.mark.asyncio
    async def test_load_async(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        config_path = tmp_path / "config.txt"
        config_path.write_text("key=value\n")

        result = await ConfigLoader.load_async(config_path)

        assert result['key'] == 'value'


class TestConfigLoaderModuleConfig:
    """Test ConfigLoader.load_module_config method."""

    def test_load_module_config_finds_config(self, tmp_path):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        # Create nested structure
        module_dir = tmp_path / "ModuleName"
        module_dir.mkdir()
        config_path = module_dir / "config.txt"
        config_path.write_text("enabled=true\n")

        core_dir = module_dir / "module_core"
        core_dir.mkdir()
        calling_file = core_dir / "some_file.py"
        calling_file.touch()

        result = ConfigLoader.load_module_config(str(calling_file))

        assert result['enabled'] is True


class TestConfigLoaderFormatValue:
    """Test ConfigLoader._format_config_value method."""

    def test_format_bool_true(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._format_config_value(True) == 'true'

    def test_format_bool_false(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._format_config_value(False) == 'false'

    def test_format_int(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._format_config_value(42) == '42'

    def test_format_float(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._format_config_value(3.14) == '3.14'

    def test_format_string(self):
        from rpi_logger.modules.base.config_loader import ConfigLoader

        assert ConfigLoader._format_config_value('hello') == 'hello'


class TestLoadConfigFile:
    """Test load_config_file convenience function."""

    def test_load_config_file_with_path(self, tmp_path):
        from rpi_logger.modules.base.config_loader import load_config_file

        config_path = tmp_path / "config.txt"
        config_path.write_text("key=value\n")

        result = load_config_file(config_path=config_path)

        assert result['key'] == 'value'

    def test_load_config_file_no_args(self):
        from rpi_logger.modules.base.config_loader import load_config_file

        defaults = {'key': 'default'}
        result = load_config_file(defaults=defaults)

        assert result == defaults
