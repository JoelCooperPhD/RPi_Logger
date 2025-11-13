
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .recording import RecordingManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class NotesHandler:

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.recording_manager = RecordingManager(session_dir)

    async def start_recording(self) -> bool:
        return await self.recording_manager.start_recording()

    def stop_recording(self) -> bool:
        return self.recording_manager.stop_recording()

    async def add_note(self, note_text: str) -> Optional[Dict[str, Any]]:
        if not note_text.strip():
            logger.warning("Cannot add empty note")
            return None

        recording_modules = await self._get_recording_modules()

        return await self.recording_manager.add_note(note_text, recording_modules)

    async def get_all_notes(self) -> List[Dict[str, Any]]:
        return await self.recording_manager.get_all_notes()

    def get_session_elapsed_time(self) -> str:
        return self.recording_manager.get_session_elapsed_time()

    @property
    def recording(self) -> bool:
        return self.recording_manager.recording

    @property
    def note_count(self) -> int:
        return self.recording_manager.note_count

    async def _get_recording_modules(self) -> List[str]:
        recording_modules = []

        try:
            import json
            from pathlib import Path
            import aiofiles

            running_modules_file = Path(__file__).parent.parent.parent.parent.parent / "data" / "running_modules.json"

            import asyncio
            if not await asyncio.to_thread(running_modules_file.exists):
                return []

            async with aiofiles.open(running_modules_file, 'r') as f:
                content = await f.read()
                module_states = json.loads(content)

            for module_name, state in module_states.items():
                if isinstance(state, dict) and state.get('recording', False):
                    recording_modules.append(module_name)

            logger.debug("Recording modules: %s", recording_modules)

        except Exception as e:
            logger.debug("Failed to query recording modules: %s", e)

        return recording_modules
