"""Unit tests for the Notes module.

This module tests the Notes runtime functionality including:
- NotesArchive: CSV persistence, note creation, timestamp handling
- NotesConfig: Configuration loading and CLI override handling
- NotesPreferences: Preference storage/retrieval
- NoteRecord: Data container for individual notes

These tests are designed to be fast (no hardware dependencies) and achieve
high code coverage for this simpler software-only module.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Mock vmc module before importing Notes components
# ---------------------------------------------------------------------------

# Create mock vmc module if it doesn't exist (for isolated testing)
if "vmc" not in sys.modules:
    mock_vmc = MagicMock()
    mock_vmc.ModuleRuntime = MagicMock
    mock_vmc.RuntimeContext = MagicMock
    mock_vmc.StubCodexSupervisor = MagicMock
    mock_vmc.RuntimeRetryPolicy = MagicMock
    mock_vmc.runtime_helpers = MagicMock()
    mock_vmc.runtime_helpers.BackgroundTaskManager = MagicMock
    mock_vmc.runtime_helpers.ShutdownGuard = MagicMock
    sys.modules["vmc"] = mock_vmc
    sys.modules["vmc.runtime_helpers"] = mock_vmc.runtime_helpers


# ---------------------------------------------------------------------------
# Imports from the Notes module
# ---------------------------------------------------------------------------

from rpi_logger.modules.Notes.notes_runtime import NoteRecord, NotesArchive
from rpi_logger.modules.Notes.config import NotesConfig, NotesPreferences


# ---------------------------------------------------------------------------
# Async Helper
# ---------------------------------------------------------------------------

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_logger() -> MagicMock:
    """Create a mock logger for testing."""
    logger = MagicMock()
    logger.getChild.return_value = logger
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.exception = MagicMock()
    return logger


@pytest.fixture
def notes_archive(temp_work_dir: Path, mock_logger: MagicMock) -> NotesArchive:
    """Create a NotesArchive instance for testing."""
    return NotesArchive(temp_work_dir, mock_logger)


@pytest.fixture
def mock_preferences() -> MagicMock:
    """Create a mock ScopedPreferences for testing."""
    prefs = MagicMock()
    prefs.get.return_value = None
    prefs.write_sync = MagicMock()
    return prefs


# ===========================================================================
# NoteRecord Tests
# ===========================================================================


class TestNoteRecord:
    """Tests for the NoteRecord dataclass."""

    def test_note_record_creation(self):
        """Test that NoteRecord can be created with all fields."""
        record = NoteRecord(
            index=1,
            trial_number=1,
            text="Test note content",
            timestamp=1704067200.0,  # 2024-01-01 00:00:00
            record_time_mono=12345.678901234,
            timestamp_iso="2024-01-01T00:00:00",
            elapsed="00:05:30",
            modules="GPS;DRT",
            file_line="1,Notes,notes,,1704067200.000000,12345.678901234,,Test note content",
        )

        assert record.index == 1
        assert record.trial_number == 1
        assert record.text == "Test note content"
        assert record.timestamp == pytest.approx(1704067200.0)
        assert record.record_time_mono == pytest.approx(12345.678901234)
        assert record.timestamp_iso == "2024-01-01T00:00:00"
        assert record.elapsed == "00:05:30"
        assert record.modules == "GPS;DRT"

    def test_note_record_empty_modules(self):
        """Test NoteRecord with empty modules string."""
        record = NoteRecord(
            index=1,
            trial_number=1,
            text="Solo note",
            timestamp=0.0,
            record_time_mono=0.0,
            timestamp_iso="",
            elapsed="00:00:00",
            modules="",
            file_line="",
        )

        assert record.modules == ""

    def test_note_record_unicode_text(self):
        """Test NoteRecord with Unicode content."""
        record = NoteRecord(
            index=1,
            trial_number=1,
            text="Unicode test: \u00e9\u00e0\u00fc \u4e2d\u6587 \U0001f600",
            timestamp=0.0,
            record_time_mono=0.0,
            timestamp_iso="",
            elapsed="00:00:00",
            modules="",
            file_line="",
        )

        assert "\u00e9" in record.text  # e with accent
        assert "\u4e2d\u6587" in record.text  # Chinese characters
        assert "\U0001f600" in record.text  # Emoji


# ===========================================================================
# NotesArchive Tests
# ===========================================================================


class TestNotesArchiveInitialization:
    """Tests for NotesArchive initialization."""

    def test_archive_creation(self, temp_work_dir: Path, mock_logger: MagicMock):
        """Test NotesArchive can be instantiated."""
        archive = NotesArchive(temp_work_dir, mock_logger)

        assert archive.base_dir == temp_work_dir
        assert archive.logger == mock_logger
        assert archive.encoding == "utf-8"
        assert archive.recording is False
        assert archive.note_count == 0
        assert archive.file_path is None

    def test_archive_custom_encoding(self, temp_work_dir: Path, mock_logger: MagicMock):
        """Test NotesArchive with custom encoding."""
        archive = NotesArchive(temp_work_dir, mock_logger, encoding="latin-1")

        assert archive.encoding == "latin-1"

    def test_archive_header_format(self):
        """Test that the CSV header matches expected format."""
        expected_header = [
            "trial",
            "module",
            "device_id",
            "label",
            "record_time_unix",
            "record_time_mono",
            "device_time_unix",
            "content",
        ]

        assert NotesArchive.HEADER == expected_header


class TestNotesArchiveStart:
    """Tests for NotesArchive.start() method."""

    def test_start_creates_new_file(self, notes_archive: NotesArchive):
        """Test that start() creates a new CSV file with header."""
        file_path = run_async(notes_archive.start(trial_number=1))

        assert file_path.exists()
        assert notes_archive.recording is True
        assert notes_archive.note_count == 0

        # The internal file handle has the header but may not be flushed.
        # Add a note to ensure there's content and stop to flush.
        run_async(notes_archive.add_note("Test note for header check", modules=[], trial_number=1))
        run_async(notes_archive.stop())

        # Verify header was written
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == NotesArchive.HEADER

    def test_start_normalizes_trial_number(self, notes_archive: NotesArchive):
        """Test that start() normalizes invalid trial numbers."""
        # Test with negative trial number
        run_async(notes_archive.start(trial_number=-5))
        assert notes_archive._current_trial_number == 1

        run_async(notes_archive.stop())
        notes_archive.file_path = None
        notes_archive.recording = False

        # Test with zero trial number
        run_async(notes_archive.start(trial_number=0))
        assert notes_archive._current_trial_number == 1

    def test_start_idempotent_when_recording(self, notes_archive: NotesArchive):
        """Test that start() returns existing path when already recording."""
        first_path = run_async(notes_archive.start(trial_number=1))
        second_path = run_async(notes_archive.start(trial_number=2))  # Different trial

        assert first_path == second_path  # Should return same path
        assert notes_archive.recording is True

    def test_start_appends_to_existing_file(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test that start() appends to existing file."""
        # Create first archive and add notes
        archive1 = NotesArchive(temp_work_dir, mock_logger)
        file_path = run_async(archive1.start(trial_number=1))
        run_async(archive1.add_note("First note", [], trial_number=1))
        run_async(archive1.stop())

        # Create second archive pointing to same directory
        archive2 = NotesArchive(temp_work_dir, mock_logger)
        run_async(archive2.start(trial_number=1))

        assert archive2.note_count == 1  # Should count existing notes
        assert archive2.recording is True


class TestNotesArchiveStop:
    """Tests for NotesArchive.stop() method."""

    def test_stop_closes_archive(self, notes_archive: NotesArchive):
        """Test that stop() properly closes the archive."""
        run_async(notes_archive.start(trial_number=1))
        assert notes_archive.recording is True

        run_async(notes_archive.stop())
        assert notes_archive.recording is False

    def test_stop_idempotent_when_not_recording(self, notes_archive: NotesArchive):
        """Test that stop() does nothing when not recording."""
        # Should not raise
        run_async(notes_archive.stop())
        assert notes_archive.recording is False


class TestNotesArchiveAddNote:
    """Tests for NotesArchive.add_note() method."""

    def test_add_note_basic(self, notes_archive: NotesArchive):
        """Test adding a basic note."""
        run_async(notes_archive.start(trial_number=1))

        record = run_async(notes_archive.add_note(
            "Test note content",
            modules=["GPS", "DRT"],
            trial_number=1,
        ))

        assert record.text == "Test note content"
        assert record.trial_number == 1
        assert record.modules == "DRT;GPS"  # Sorted
        assert record.index == 1
        assert notes_archive.note_count == 1

    def test_add_note_strips_whitespace(self, notes_archive: NotesArchive):
        """Test that note text is stripped of leading/trailing whitespace."""
        run_async(notes_archive.start(trial_number=1))

        record = run_async(notes_archive.add_note(
            "  Padded note  \n",
            modules=[],
            trial_number=1,
        ))

        assert record.text == "Padded note"

    def test_add_note_empty_raises_error(self, notes_archive: NotesArchive):
        """Test that adding empty note raises ValueError."""
        run_async(notes_archive.start(trial_number=1))

        with pytest.raises(ValueError, match="Cannot add empty note"):
            run_async(notes_archive.add_note("", modules=[], trial_number=1))

        with pytest.raises(ValueError, match="Cannot add empty note"):
            run_async(notes_archive.add_note("   \n  ", modules=[], trial_number=1))

    def test_add_note_not_recording_raises_error(self, notes_archive: NotesArchive):
        """Test that adding note when not recording raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Notes archive is not active"):
            run_async(notes_archive.add_note("Test", modules=[], trial_number=1))

    def test_add_note_increments_count(self, notes_archive: NotesArchive):
        """Test that note count increments correctly."""
        run_async(notes_archive.start(trial_number=1))

        assert notes_archive.note_count == 0

        run_async(notes_archive.add_note("Note 1", modules=[], trial_number=1))
        assert notes_archive.note_count == 1

        run_async(notes_archive.add_note("Note 2", modules=[], trial_number=1))
        assert notes_archive.note_count == 2

        run_async(notes_archive.add_note("Note 3", modules=[], trial_number=1))
        assert notes_archive.note_count == 3

    def test_add_note_with_custom_timestamp(self, notes_archive: NotesArchive):
        """Test adding note with custom posted_at timestamp."""
        run_async(notes_archive.start(trial_number=1))

        custom_time = 1704067200.0  # 2024-01-01 00:00:00 UTC
        record = run_async(notes_archive.add_note(
            "Backdated note",
            modules=[],
            posted_at=custom_time,
            trial_number=1,
        ))

        assert record.timestamp == pytest.approx(custom_time)

    def test_add_note_empty_modules(self, notes_archive: NotesArchive):
        """Test adding note with no modules."""
        run_async(notes_archive.start(trial_number=1))

        record = run_async(notes_archive.add_note(
            "Note without modules",
            modules=[],
            trial_number=1,
        ))

        assert record.modules == ""


class TestNotesArchiveUnicodeHandling:
    """Tests for Unicode content handling in NotesArchive."""

    def test_add_note_with_unicode(self, notes_archive: NotesArchive):
        """Test adding note with Unicode characters."""
        run_async(notes_archive.start(trial_number=1))

        unicode_text = "Caf\u00e9 with \u4e2d\u6587 and \U0001f600 emoji"
        record = run_async(notes_archive.add_note(
            unicode_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == unicode_text

    def test_add_note_with_accented_characters(self, notes_archive: NotesArchive):
        """Test adding note with accented characters."""
        run_async(notes_archive.start(trial_number=1))

        accented_text = "\u00e9\u00e0\u00f9\u00ee\u00f4 \u00e4\u00f6\u00fc \u00f1"
        record = run_async(notes_archive.add_note(
            accented_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == accented_text

    def test_add_note_with_chinese_characters(self, notes_archive: NotesArchive):
        """Test adding note with Chinese characters."""
        run_async(notes_archive.start(trial_number=1))

        chinese_text = "\u4e2d\u6587\u6d4b\u8bd5\u6587\u672c"
        record = run_async(notes_archive.add_note(
            chinese_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == chinese_text

    def test_add_note_with_emojis(self, notes_archive: NotesArchive):
        """Test adding note with emoji characters."""
        run_async(notes_archive.start(trial_number=1))

        emoji_text = "\U0001f600 \U0001f4a1 \U0001f3af \U0001f680"
        record = run_async(notes_archive.add_note(
            emoji_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == emoji_text


class TestNotesArchiveSpecialCharacters:
    """Tests for special character handling in NotesArchive."""

    def test_add_note_with_commas(self, notes_archive: NotesArchive):
        """Test that commas in note text are properly escaped in CSV."""
        run_async(notes_archive.start(trial_number=1))

        comma_text = "First, second, and third items"
        record = run_async(notes_archive.add_note(
            comma_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == comma_text

        # Verify CSV output is properly formatted
        records = run_async(notes_archive.load_recent(10))
        assert len(records) == 1
        assert records[0].text == comma_text

    def test_add_note_with_quotes(self, notes_archive: NotesArchive):
        """Test that quotes in note text are properly escaped."""
        run_async(notes_archive.start(trial_number=1))

        quote_text = 'User said "hello" and \'goodbye\''
        record = run_async(notes_archive.add_note(
            quote_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == quote_text

        # Verify roundtrip through CSV
        records = run_async(notes_archive.load_recent(10))
        assert len(records) == 1
        assert records[0].text == quote_text

    def test_add_note_with_newlines(self, notes_archive: NotesArchive):
        """Test that newlines in note text are handled."""
        run_async(notes_archive.start(trial_number=1))

        newline_text = "Line one\nLine two\nLine three"
        record = run_async(notes_archive.add_note(
            newline_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == newline_text

        # Verify roundtrip
        records = run_async(notes_archive.load_recent(10))
        assert len(records) == 1
        assert records[0].text == newline_text

    def test_add_note_with_tabs(self, notes_archive: NotesArchive):
        """Test that tabs in note text are preserved."""
        run_async(notes_archive.start(trial_number=1))

        tab_text = "Column1\tColumn2\tColumn3"
        record = run_async(notes_archive.add_note(
            tab_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == tab_text

    def test_add_note_with_backslashes(self, notes_archive: NotesArchive):
        """Test that backslashes in note text are preserved."""
        run_async(notes_archive.start(trial_number=1))

        backslash_text = "Path: C:\\Users\\Test\\file.txt"
        record = run_async(notes_archive.add_note(
            backslash_text,
            modules=[],
            trial_number=1,
        ))

        assert record.text == backslash_text


class TestNotesArchiveCSVFormat:
    """Tests for CSV output format validation."""

    def test_csv_file_format(self, notes_archive: NotesArchive):
        """Test that CSV file has correct format."""
        file_path = run_async(notes_archive.start(trial_number=1))

        # Add a note
        run_async(notes_archive.add_note(
            "Test note",
            modules=["GPS"],
            trial_number=1,
        ))
        run_async(notes_archive.stop())

        # Read and verify CSV structure
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should have header + 1 data row
        assert len(rows) == 2

        # Verify header
        assert rows[0] == NotesArchive.HEADER

        # Verify data row structure
        data_row = rows[1]
        assert len(data_row) == 8
        assert data_row[0] == "1"  # trial
        assert data_row[1] == "Notes"  # module
        assert data_row[2] == "notes"  # device_id
        assert data_row[3] == ""  # label (empty)
        # data_row[4] is record_time_unix
        # data_row[5] is record_time_mono
        assert data_row[6] == ""  # device_time_unix (empty)
        assert data_row[7] == "Test note"  # content

    def test_csv_timestamp_precision(self, notes_archive: NotesArchive):
        """Test that timestamps have correct precision."""
        file_path = run_async(notes_archive.start(trial_number=1))

        run_async(notes_archive.add_note("Test", modules=[], trial_number=1))
        run_async(notes_archive.stop())

        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            data_row = next(reader)

        record_time_unix = data_row[4]
        record_time_mono = data_row[5]

        # record_time_unix should have 6 decimal places
        assert "." in record_time_unix
        decimal_part = record_time_unix.split(".")[1]
        assert len(decimal_part) == 6

        # record_time_mono should have 9 decimal places
        assert "." in record_time_mono
        decimal_part = record_time_mono.split(".")[1]
        assert len(decimal_part) == 9

    def test_csv_multiple_notes(self, notes_archive: NotesArchive):
        """Test CSV with multiple notes."""
        file_path = run_async(notes_archive.start(trial_number=1))

        for i in range(5):
            run_async(notes_archive.add_note(f"Note {i+1}", modules=[], trial_number=1))
        run_async(notes_archive.stop())

        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 6  # Header + 5 notes

        for i, row in enumerate(rows[1:], 1):
            assert row[7] == f"Note {i}"


class TestNotesArchiveLoadRecent:
    """Tests for NotesArchive.load_recent() method."""

    def test_load_recent_empty(self, notes_archive: NotesArchive):
        """Test load_recent on empty archive."""
        run_async(notes_archive.start(trial_number=1))
        records = run_async(notes_archive.load_recent(10))
        assert records == []

    def test_load_recent_with_notes(self, notes_archive: NotesArchive):
        """Test loading recent notes."""
        run_async(notes_archive.start(trial_number=1))

        for i in range(5):
            run_async(notes_archive.add_note(f"Note {i+1}", modules=[], trial_number=1))

        records = run_async(notes_archive.load_recent(10))
        assert len(records) == 5

    def test_load_recent_limit(self, notes_archive: NotesArchive):
        """Test that load_recent respects limit parameter."""
        run_async(notes_archive.start(trial_number=1))

        for i in range(10):
            run_async(notes_archive.add_note(f"Note {i+1}", modules=[], trial_number=1))

        records = run_async(notes_archive.load_recent(3))
        assert len(records) == 3

        # Should return the most recent 3
        assert records[-1].text == "Note 10"

    def test_load_recent_no_file(self, temp_work_dir: Path, mock_logger: MagicMock):
        """Test load_recent when no file exists."""
        archive = NotesArchive(temp_work_dir, mock_logger)
        records = run_async(archive.load_recent(10))
        assert records == []


class TestNotesArchiveElapsedTime:
    """Tests for elapsed time formatting."""

    def test_format_elapsed_basic(self):
        """Test basic elapsed time formatting."""
        assert NotesArchive.format_elapsed(0) == "00:00:00"
        assert NotesArchive.format_elapsed(30) == "00:00:30"
        assert NotesArchive.format_elapsed(90) == "00:01:30"
        assert NotesArchive.format_elapsed(3661) == "01:01:01"

    def test_format_elapsed_large_values(self):
        """Test elapsed time formatting with large values."""
        # 10 hours, 30 minutes, 45 seconds
        assert NotesArchive.format_elapsed(37845) == "10:30:45"

        # 24+ hours
        assert NotesArchive.format_elapsed(90061) == "25:01:01"

    def test_format_elapsed_negative(self):
        """Test that negative values are clamped to zero."""
        assert NotesArchive.format_elapsed(-10) == "00:00:00"
        assert NotesArchive.format_elapsed(-100.5) == "00:00:00"

    def test_format_elapsed_fractional_seconds(self):
        """Test that fractional seconds are truncated."""
        assert NotesArchive.format_elapsed(30.9) == "00:00:30"
        assert NotesArchive.format_elapsed(30.1) == "00:00:30"

    def test_current_elapsed_not_recording(self, notes_archive: NotesArchive):
        """Test current_elapsed when not recording."""
        assert notes_archive.current_elapsed() == "00:00:00"


class TestNotesArchiveConcurrency:
    """Tests for concurrent note additions."""

    def test_concurrent_add_notes(self, notes_archive: NotesArchive):
        """Test adding multiple notes concurrently."""
        run_async(notes_archive.start(trial_number=1))

        async def add_notes_concurrently():
            tasks = [
                notes_archive.add_note(f"Concurrent note {i}", modules=[], trial_number=1)
                for i in range(10)
            ]
            return await asyncio.gather(*tasks)

        results = run_async(add_notes_concurrently())

        assert len(results) == 10
        assert notes_archive.note_count == 10

        # Verify all notes are in file
        records = run_async(notes_archive.load_recent(20))
        assert len(records) == 10

    def test_sequential_start_stop_cycles(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test multiple start/stop cycles."""
        archive = NotesArchive(temp_work_dir, mock_logger)

        for cycle in range(3):
            run_async(archive.start(trial_number=1))
            run_async(archive.add_note(f"Note from cycle {cycle}", modules=[], trial_number=1))
            run_async(archive.stop())

        # Reopen and verify all notes
        archive2 = NotesArchive(temp_work_dir, mock_logger)
        run_async(archive2.start(trial_number=1))
        records = run_async(archive2.load_recent(10))

        assert len(records) == 3


# ===========================================================================
# NotesConfig Tests
# ===========================================================================


class TestNotesConfigDefaults:
    """Tests for NotesConfig default values."""

    def test_config_default_values(self):
        """Test that NotesConfig has expected default values."""
        config = NotesConfig()

        assert config.display_name == "Notes"
        assert config.enabled is True
        assert config.internal is True
        assert config.visible is True
        assert config.history_limit == 200
        assert config.auto_start is False
        assert config.session_prefix == "notes"
        assert config.log_level == "info"

    def test_config_output_dir_default(self):
        """Test default output directory."""
        config = NotesConfig()
        assert config.output_dir == Path("notes")


class TestNotesConfigFromPreferences:
    """Tests for NotesConfig.from_preferences()."""

    def test_config_from_preferences_with_values(self, mock_preferences: MagicMock):
        """Test loading config from preferences."""
        mock_preferences.get.side_effect = lambda key, default=None: {
            "display_name": "Custom Notes",
            "enabled": True,
            "notes.history_limit": 100,
            "notes.auto_start": True,
        }.get(key, default)

        config = NotesConfig.from_preferences(mock_preferences)

        assert config.display_name == "Custom Notes"
        assert config.history_limit == 100
        assert config.auto_start is True

    def test_config_from_preferences_empty(self, mock_preferences: MagicMock):
        """Test loading config when preferences are empty."""
        mock_preferences.get.return_value = None

        config = NotesConfig.from_preferences(mock_preferences)

        # Should use defaults
        assert config.history_limit == 200
        assert config.auto_start is False


class TestNotesConfigArgsOverride:
    """Tests for CLI argument override handling."""

    def test_apply_args_override(self):
        """Test that CLI args override config values."""
        config = NotesConfig()

        args = MagicMock()
        args.history_limit = 50
        args.auto_start = True
        args.output_dir = None  # Not overridden
        args.session_prefix = None
        args.log_level = None
        args.console_output = None

        new_config = config._apply_args_override(args)

        assert new_config.history_limit == 50
        assert new_config.auto_start is True
        # Non-overridden values should remain
        assert new_config.output_dir == Path("notes")

    def test_to_dict(self):
        """Test config serialization to dictionary."""
        config = NotesConfig()
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert config_dict["display_name"] == "Notes"
        assert config_dict["history_limit"] == 200


# ===========================================================================
# NotesPreferences Tests
# ===========================================================================


class TestNotesPreferencesHistoryLimit:
    """Tests for NotesPreferences.history_limit()."""

    def test_history_limit_with_value(self, mock_preferences: MagicMock):
        """Test getting history limit when set."""
        mock_preferences.get.return_value = 150

        prefs = NotesPreferences(mock_preferences)
        assert prefs.history_limit(200) == 150

    def test_history_limit_fallback(self, mock_preferences: MagicMock):
        """Test history limit fallback when not set."""
        mock_preferences.get.return_value = None

        prefs = NotesPreferences(mock_preferences)
        assert prefs.history_limit(200) == 200

    def test_history_limit_invalid_value(self, mock_preferences: MagicMock):
        """Test history limit with invalid value returns fallback."""
        mock_preferences.get.return_value = "not_a_number"

        prefs = NotesPreferences(mock_preferences)
        assert prefs.history_limit(200) == 200

    def test_history_limit_no_prefs(self):
        """Test history limit when prefs is None."""
        prefs = NotesPreferences(None)
        assert prefs.history_limit(200) == 200


class TestNotesPreferencesAutoStart:
    """Tests for NotesPreferences.auto_start()."""

    def test_auto_start_true_values(self, mock_preferences: MagicMock):
        """Test auto_start with various true values."""
        prefs = NotesPreferences(mock_preferences)

        for true_val in ["true", "True", "TRUE", "1", "yes", "on"]:
            mock_preferences.get.return_value = true_val
            assert prefs.auto_start(False) is True

    def test_auto_start_false_values(self, mock_preferences: MagicMock):
        """Test auto_start with various false values."""
        prefs = NotesPreferences(mock_preferences)

        for false_val in ["false", "False", "0", "no", "off", ""]:
            mock_preferences.get.return_value = false_val
            assert prefs.auto_start(True) is False

    def test_auto_start_fallback(self, mock_preferences: MagicMock):
        """Test auto_start fallback when not set."""
        mock_preferences.get.return_value = None

        prefs = NotesPreferences(mock_preferences)
        assert prefs.auto_start(True) is True
        assert prefs.auto_start(False) is False

    def test_auto_start_no_prefs(self):
        """Test auto_start when prefs is None."""
        prefs = NotesPreferences(None)
        assert prefs.auto_start(True) is True
        assert prefs.auto_start(False) is False


class TestNotesPreferencesSetters:
    """Tests for NotesPreferences setter methods."""

    def test_set_history_limit(self, mock_preferences: MagicMock):
        """Test setting history limit."""
        prefs = NotesPreferences(mock_preferences)
        prefs.set_history_limit(100)

        mock_preferences.write_sync.assert_called_once_with({"history_limit": 100})

    def test_set_auto_start(self, mock_preferences: MagicMock):
        """Test setting auto start."""
        prefs = NotesPreferences(mock_preferences)
        prefs.set_auto_start(True)

        mock_preferences.write_sync.assert_called_once_with({"auto_start": True})

    def test_set_last_note_path(self, mock_preferences: MagicMock):
        """Test setting last note path."""
        prefs = NotesPreferences(mock_preferences)
        prefs.set_last_note_path("/path/to/notes.csv")

        mock_preferences.write_sync.assert_called_once_with(
            {"last_archive_path": "/path/to/notes.csv"}
        )

    def test_setters_with_no_prefs(self):
        """Test that setters do nothing when prefs is None."""
        prefs = NotesPreferences(None)

        # Should not raise
        prefs.set_history_limit(100)
        prefs.set_auto_start(True)
        prefs.set_last_note_path("/path")


# ===========================================================================
# Edge Cases and Error Handling Tests
# ===========================================================================


class TestNotesArchiveEdgeCases:
    """Tests for edge cases in NotesArchive."""

    def test_add_very_long_note(self, notes_archive: NotesArchive):
        """Test adding a very long note (10KB+)."""
        run_async(notes_archive.start(trial_number=1))

        long_text = "A" * 10000
        record = run_async(notes_archive.add_note(
            long_text,
            modules=[],
            trial_number=1,
        ))

        assert len(record.text) == 10000

        # Verify roundtrip
        records = run_async(notes_archive.load_recent(10))
        assert records[0].text == long_text

    def test_add_note_with_null_bytes(self, notes_archive: NotesArchive):
        """Test handling of null bytes in note text."""
        run_async(notes_archive.start(trial_number=1))

        # Note: CSV cannot handle null bytes well, but the input is stripped
        text_with_null = "Before\x00After"
        record = run_async(notes_archive.add_note(
            text_with_null,
            modules=[],
            trial_number=1,
        ))

        # The text should be preserved as-is (though null handling may vary)
        assert "Before" in record.text
        assert "After" in record.text

    def test_add_note_whitespace_only(self, notes_archive: NotesArchive):
        """Test that whitespace-only notes are rejected."""
        run_async(notes_archive.start(trial_number=1))

        with pytest.raises(ValueError):
            run_async(notes_archive.add_note("   ", modules=[], trial_number=1))

        with pytest.raises(ValueError):
            run_async(notes_archive.add_note("\t\n  ", modules=[], trial_number=1))

    def test_many_modules_sorted(self, notes_archive: NotesArchive):
        """Test that many modules are sorted correctly."""
        run_async(notes_archive.start(trial_number=1))

        modules = ["Zebra", "Alpha", "Middle", "Beta"]
        record = run_async(notes_archive.add_note(
            "Test",
            modules=modules,
            trial_number=1,
        ))

        assert record.modules == "Alpha;Beta;Middle;Zebra"

    def test_file_path_resolution(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test that file path includes session token and trial number."""
        archive = NotesArchive(temp_work_dir, mock_logger)
        file_path = run_async(archive.start(trial_number=5))

        # File path should contain trial number
        assert "trial005" in file_path.name
        assert file_path.suffix == ".csv"
        assert "notes" in file_path.name.lower()


class TestNotesArchiveErrorHandling:
    """Tests for error handling in NotesArchive."""

    def test_invalid_trial_number_type(self, notes_archive: NotesArchive):
        """Test handling of invalid trial number type."""
        # Pass non-integer trial number
        run_async(notes_archive.start(trial_number="invalid"))  # type: ignore
        assert notes_archive._current_trial_number == 1  # Should default to 1

    def test_append_row_without_file_path(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test _append_row raises error without file path."""
        archive = NotesArchive(temp_work_dir, mock_logger)

        with pytest.raises(RuntimeError, match="Archive file path not set"):
            archive._append_row("Test", 0.0, 0.0, 1)

    def test_resolve_header_indices(self):
        """Test header index resolution."""
        header = ["trial", "module", "device_id", "label", "record_time_unix", "record_time_mono", "device_time_unix", "content"]
        indices = NotesArchive._resolve_header_indices(header)

        assert indices["trial"] == 0
        assert indices["record_time_unix"] == 4
        assert indices["record_time_mono"] == 5
        assert indices["content"] == 7

    def test_resolve_header_indices_legacy(self):
        """Test header resolution with legacy 'timestamp' column."""
        header = ["trial", "module", "device_id", "label", "timestamp", "record_time_mono", "device_time_unix", "content"]
        indices = NotesArchive._resolve_header_indices(header)

        # Should find 'timestamp' as record_time_unix
        assert indices["record_time_unix"] == 4


class TestNotesArchiveCSVLineFormatting:
    """Tests for CSV line formatting helper."""

    def test_format_csv_line_basic(self):
        """Test basic CSV line formatting."""
        row = [1, "Notes", "notes", "", "1234.567890", "12345.678901234", "", "Test"]
        line = NotesArchive._format_csv_line(row)

        assert line == '1,Notes,notes,,1234.567890,12345.678901234,,Test'

    def test_format_csv_line_with_quotes(self):
        """Test CSV line formatting with text requiring quotes."""
        row = [1, "Notes", "notes", "", "1234.567890", "12345.678901234", "", 'Text with "quotes"']
        line = NotesArchive._format_csv_line(row)

        # CSV writer should escape quotes
        assert '"' in line

    def test_format_csv_line_with_commas(self):
        """Test CSV line formatting with commas in content."""
        row = [1, "Notes", "notes", "", "1234.567890", "12345.678901234", "", "One, two, three"]
        line = NotesArchive._format_csv_line(row)

        # Content with commas should be quoted
        assert '"One, two, three"' in line


# ===========================================================================
# Integration-style Unit Tests (Still Mocked)
# ===========================================================================


class TestNotesArchiveFullWorkflow:
    """Integration-style tests for complete workflows."""

    def test_complete_session_workflow(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test a complete note-taking session workflow."""
        archive = NotesArchive(temp_work_dir, mock_logger)

        # Start session
        file_path = run_async(archive.start(trial_number=1))
        assert archive.recording is True
        assert file_path.exists()

        # Add various notes
        run_async(archive.add_note("Session started", modules=["GPS"], trial_number=1))
        run_async(archive.add_note("Participant arrived", modules=[], trial_number=1))
        run_async(archive.add_note("Trial 1 complete", modules=["GPS", "DRT"], trial_number=1))

        # Check counts
        assert archive.note_count == 3

        # Stop and verify
        run_async(archive.stop())
        assert archive.recording is False

        # Reopen and verify persistence
        archive2 = NotesArchive(temp_work_dir, mock_logger)
        run_async(archive2.start(trial_number=1))
        records = run_async(archive2.load_recent(10))

        assert len(records) == 3
        assert records[0].text == "Session started"
        assert records[1].text == "Participant arrived"
        assert records[2].text == "Trial 1 complete"

    def test_cross_trial_notes(
        self, temp_work_dir: Path, mock_logger: MagicMock
    ):
        """Test notes across multiple trials."""
        archive = NotesArchive(temp_work_dir, mock_logger)

        # Trial 1
        run_async(archive.start(trial_number=1))
        run_async(archive.add_note("Trial 1 note", modules=[], trial_number=1))
        run_async(archive.stop())

        # Reset for trial 2 (new file)
        archive.file_path = None
        archive.recording = False
        run_async(archive.start(trial_number=2))
        run_async(archive.add_note("Trial 2 note", modules=[], trial_number=2))

        records = run_async(archive.load_recent(10))
        assert len(records) == 1
        assert records[0].trial_number == 2
