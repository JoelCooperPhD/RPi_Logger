"""
Notes module API controller mixin.

Provides Notes-specific methods that are dynamically added to APIController.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional


class NotesApiMixin:
    """
    Mixin class providing Notes module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def get_notes_config(self) -> Dict[str, Any]:
        """Get Notes module configuration.

        Returns the typed configuration for the Notes module including
        output_dir, session_prefix, history_limit, auto_start, and log_level.

        Returns:
            Dict with success status and config values.
        """
        result = await self.get_module_config("Notes")
        if result is None:
            return {
                "success": False,
                "error": "module_not_found",
                "message": "Notes module not found",
            }

        # Enhance with Notes-specific defaults from NotesConfig
        config = result.get("config", {})

        # Add default values for Notes-specific settings if not present
        notes_defaults = {
            "output_dir": "notes",
            "session_prefix": "notes",
            "history_limit": 200,
            "auto_start": False,
            "log_level": "info",
        }

        for key, default in notes_defaults.items():
            if key not in config:
                config[key] = default

        return {
            "success": True,
            "module": "Notes",
            "config_path": result.get("config_path"),
            "config": config,
        }

    async def update_notes_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update Notes module configuration.

        Args:
            updates: Dictionary of config key-value pairs to update.
                     Valid keys: output_dir, session_prefix, history_limit,
                     auto_start, log_level

        Returns:
            Result dict with success status and updated keys.
        """
        # Validate Notes-specific settings
        valid_keys = {
            "output_dir", "session_prefix", "history_limit",
            "auto_start", "log_level", "notes.history_limit",
            "notes.auto_start", "notes.last_archive_path",
        }

        invalid_keys = set(updates.keys()) - valid_keys
        if invalid_keys:
            self.logger.warning(
                "Ignoring invalid Notes config keys: %s", invalid_keys
            )
            # Filter to only valid keys
            updates = {k: v for k, v in updates.items() if k in valid_keys}

        if not updates:
            return {
                "success": False,
                "error": "no_valid_updates",
                "message": "No valid configuration keys provided",
            }

        # Validate specific field types
        if "history_limit" in updates:
            try:
                updates["history_limit"] = int(updates["history_limit"])
                if updates["history_limit"] < 1:
                    return {
                        "success": False,
                        "error": "invalid_value",
                        "message": "history_limit must be a positive integer",
                    }
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error": "invalid_value",
                    "message": "history_limit must be a valid integer",
                }

        if "auto_start" in updates:
            if not isinstance(updates["auto_start"], bool):
                # Try to convert string representations
                if isinstance(updates["auto_start"], str):
                    updates["auto_start"] = updates["auto_start"].lower() in {
                        "true", "1", "yes", "on"
                    }
                else:
                    updates["auto_start"] = bool(updates["auto_start"])

        return await self.update_module_config("Notes", updates)

    async def get_notes_status(self) -> Dict[str, Any]:
        """Get Notes module status.

        Returns module state, recording status, note count, and file path.

        Returns:
            Dict with module status information.
        """
        module = await self.get_module("Notes")
        if not module:
            return {
                "success": False,
                "error": "module_not_found",
                "message": "Notes module not found",
            }

        # Get module state
        state = await self.get_module_state("Notes")
        running = module.get("running", False)

        # Build status response
        status = {
            "success": True,
            "module": "Notes",
            "state": state,
            "running": running,
            "enabled": module.get("enabled", False),
            "recording": False,
            "note_count": 0,
            "notes_file": None,
            "session_dir": str(self._session_dir) if self._session_dir else None,
        }

        # If module is running, try to get more detailed status via command
        if running:
            try:
                # The Notes module tracks its own recording state
                # We can infer from the session state
                status["recording"] = self.session_active
            except Exception:
                pass

        return status

    async def get_notes_categories(self) -> Dict[str, Any]:
        """Get available note categories.

        Returns predefined categories that can be used to organize notes.

        Returns:
            Dict with list of available categories.
        """
        # Notes module currently doesn't have explicit categories,
        # but we can define standard ones for future use
        categories = [
            {"id": "general", "name": "General", "description": "General notes"},
            {"id": "observation", "name": "Observation", "description": "Observations during session"},
            {"id": "event", "name": "Event", "description": "Notable events"},
            {"id": "issue", "name": "Issue", "description": "Problems or issues encountered"},
            {"id": "marker", "name": "Marker", "description": "Time markers for later reference"},
        ]

        return {
            "success": True,
            "categories": categories,
        }

    async def get_notes(
        self,
        limit: Optional[int] = None,
        trial_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get notes for the current session.

        Args:
            limit: Maximum number of notes to return (most recent)
            trial_number: Filter notes by trial number

        Returns:
            Dict with success status and list of notes.
        """
        if not self.session_active:
            return {
                "success": False,
                "error": "no_active_session",
                "message": "No active session - cannot retrieve notes",
            }

        # Check if Notes module is running
        running = self.logger_system.is_module_running("Notes")
        if not running:
            return {
                "success": False,
                "error": "module_not_running",
                "message": "Notes module is not running",
            }

        # Try to read notes from the notes file in the session directory
        notes = []
        notes_file = None

        if self._session_dir:
            notes_dir = self._session_dir / "Notes"
            if notes_dir.exists():
                # Find the most recent notes CSV file
                csv_files = sorted(notes_dir.glob("*_notes.csv"), reverse=True)
                if csv_files:
                    notes_file = csv_files[0]
                    notes = await self._read_notes_from_file(
                        notes_file, limit=limit, trial_number=trial_number
                    )

        return {
            "success": True,
            "notes": notes,
            "count": len(notes),
            "notes_file": str(notes_file) if notes_file else None,
            "session_dir": str(self._session_dir) if self._session_dir else None,
        }

    async def _read_notes_from_file(
        self,
        file_path: Path,
        limit: Optional[int] = None,
        trial_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Read notes from a CSV file.

        Args:
            file_path: Path to the notes CSV file
            limit: Maximum number of notes to return
            trial_number: Filter by trial number

        Returns:
            List of note dictionaries.
        """
        import csv
        from datetime import datetime

        notes = []

        try:
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Filter by trial number if specified
                    if trial_number is not None:
                        try:
                            row_trial = int(row.get("trial", 0))
                            if row_trial != trial_number:
                                continue
                        except (TypeError, ValueError):
                            continue

                    # Parse the note record
                    note = {
                        "id": len(notes) + 1,
                        "trial_number": int(row.get("trial", 0)),
                        "text": row.get("content", ""),
                        "module": row.get("module", "Notes"),
                        "device_id": row.get("device_id", "notes"),
                    }

                    # Parse timestamp
                    try:
                        timestamp = float(row.get("record_time_unix", 0))
                        note["timestamp"] = timestamp
                        note["timestamp_iso"] = datetime.fromtimestamp(
                            timestamp
                        ).isoformat(timespec="seconds")
                    except (TypeError, ValueError):
                        note["timestamp"] = 0
                        note["timestamp_iso"] = ""

                    notes.append(note)

        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.error("Error reading notes file %s: %s", file_path, e)

        # Apply limit (return most recent notes)
        if limit is not None and len(notes) > limit:
            notes = notes[-limit:]

        return notes

    async def add_note(
        self,
        note_text: str,
        timestamp: Optional[float] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new note via the Notes module.

        Args:
            note_text: The note content
            timestamp: Optional Unix timestamp (defaults to current time)
            category: Optional category for the note

        Returns:
            Result dict with success status and note details.
        """
        if not self.session_active:
            return {
                "success": False,
                "error": "no_active_session",
                "message": "No active session - cannot add notes",
            }

        # Check if Notes module is running
        running = self.logger_system.is_module_running("Notes")
        if not running:
            return {
                "success": False,
                "error": "module_not_running",
                "message": "Notes module is not running",
            }

        # Build command payload
        command_kwargs = {
            "note_text": note_text,
        }
        if timestamp is not None:
            command_kwargs["note_timestamp"] = timestamp
        if category is not None:
            command_kwargs["category"] = category

        # Send add_note command to the Notes module
        result = await self.send_module_command("Notes", "add_note", **command_kwargs)

        if result.get("success"):
            self.logger.info(
                "Note added via API: %s",
                note_text[:50] + "..." if len(note_text) > 50 else note_text
            )
            return {
                "success": True,
                "message": "Note added successfully",
                "note_text": note_text,
                "timestamp": timestamp,
                "category": category,
            }
        else:
            return {
                "success": False,
                "error": "command_failed",
                "message": "Failed to add note via Notes module",
            }

    async def get_note(self, note_id: int) -> Dict[str, Any]:
        """Get a specific note by ID.

        Args:
            note_id: The note ID (1-based index)

        Returns:
            Result dict with success status and note details.
        """
        # Get all notes and find the one with matching ID
        result = await self.get_notes()
        if not result.get("success"):
            return result

        notes = result.get("notes", [])
        for note in notes:
            if note.get("id") == note_id:
                return {
                    "success": True,
                    "note": note,
                }

        return {
            "success": False,
            "error": "note_not_found",
            "message": f"Note with ID {note_id} not found",
        }

    async def delete_note(self, note_id: int) -> Dict[str, Any]:
        """Delete a note by ID.

        Note: The Notes module stores notes in append-only CSV files,
        so deletion is not currently supported at the file level.
        This endpoint returns an appropriate error.

        Args:
            note_id: The note ID to delete

        Returns:
            Result dict with success status.
        """
        # Notes are stored in append-only CSV files
        # Deletion would require rewriting the file
        return {
            "success": False,
            "error": "not_supported",
            "message": "Note deletion is not currently supported. "
                       "Notes are stored in append-only CSV files for data integrity.",
        }
