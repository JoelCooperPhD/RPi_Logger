import asyncio
import sys
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger

from .headless_controller import HeadlessController


class InteractiveShell:
    """
    Interactive command-line shell for RPi Logger.

    Provides a command prompt for remote control via SSH.
    """

    def __init__(self, controller: HeadlessController):
        self.logger = get_module_logger("InteractiveShell")
        self.controller = controller
        self.running = True

    async def run(self) -> None:
        """Run the interactive shell."""
        self.logger.info("Starting interactive shell")
        print("\n" + "=" * 60)
        print("RPi Logger - Interactive CLI")
        print("=" * 60)
        print("Type 'help' for available commands, 'quit' to exit")
        print("=" * 60 + "\n")

        # Show initial status
        await self._cmd_status()

        # Main command loop
        while self.running:
            try:
                # Prompt for input
                line = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: input("\nlogger> ").strip()
                )

                if not line:
                    continue

                # Parse and execute command
                await self._execute_command(line)

            except EOFError:
                print("\nEOF received, shutting down...")
                break
            except KeyboardInterrupt:
                print("\n\nInterrupt received. Type 'quit' to exit.")
                continue
            except Exception as e:
                self.logger.error("Command error: %s", e, exc_info=True)
                print(f"Error: {e}")

        self.logger.info("Interactive shell exiting")

    async def _execute_command(self, line: str) -> None:
        """Parse and execute a command line."""
        parts = line.split()
        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:]

        # Command dispatch
        commands = {
            'help': self._cmd_help,
            'list': self._cmd_list,
            'status': self._cmd_status,
            'start': self._cmd_start,
            'stop': self._cmd_stop,
            'session': self._cmd_session,
            'trial': self._cmd_trial,
            'record': self._cmd_record,
            'pause': self._cmd_pause,
            'quit': self._cmd_quit,
            'exit': self._cmd_quit,
        }

        handler = commands.get(cmd)
        if handler:
            await handler(args)
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for available commands")

    async def _cmd_help(self, args=None) -> None:
        """Show help."""
        print("\nAvailable Commands:")
        print("-" * 60)
        print("  help                 - Show this help message")
        print("  list                 - List all available modules")
        print("  status               - Show current system status")
        print("  start <module>       - Start a specific module")
        print("  stop <module>        - Stop a specific module")
        print("  session start [dir]  - Start a new session")
        print("  session stop         - Stop current session")
        print("  record [label]       - Start recording a trial")
        print("  pause                - Stop recording current trial")
        print("  quit / exit          - Shutdown and exit")
        print("-" * 60)

    async def _cmd_list(self, args=None) -> None:
        """List available modules."""
        modules = self.controller.logger_system.get_available_modules()
        selected = self.controller.logger_system.get_selected_modules()
        running = self.controller.logger_system.get_running_modules()

        print("\nAvailable Modules:")
        print("-" * 60)
        for module in modules:
            status_parts = []
            if module.name in selected:
                status_parts.append("enabled")
            if module.name in running:
                status_parts.append("RUNNING")

            status_str = f" [{', '.join(status_parts)}]" if status_parts else ""
            print(f"  {module.name}{status_str}")
        print("-" * 60)

    async def _cmd_status(self, args=None) -> None:
        """Show system status."""
        status = self.controller.get_status()

        print("\nSystem Status:")
        print("-" * 60)
        print(f"  Session: {'ACTIVE' if status['session_active'] else 'Inactive'}")
        if status['session_active']:
            print(f"    Directory: {status['session_dir']}")
            print(f"    Trials completed: {status['trial_counter']}")
            print(f"  Trial: {'RECORDING' if status['trial_active'] else 'Not recording'}")

        print(f"\n  Running Modules ({len(status['running_modules'])}):")
        if status['running_modules']:
            for module in status['running_modules']:
                print(f"    - {module}")
        else:
            print("    (none)")

        print("-" * 60)

    async def _cmd_start(self, args) -> None:
        """Start a module."""
        if not args:
            print("Error: Please specify a module name")
            print("Usage: start <module>")
            await self._cmd_list()
            return

        module_name = args[0]
        modules = [m.name for m in self.controller.logger_system.get_available_modules()]

        if module_name not in modules:
            print(f"Error: Module '{module_name}' not found")
            await self._cmd_list()
            return

        print(f"Starting module: {module_name}...")
        success = await self.controller.start_module(module_name)

        if success:
            print(f"✓ Module {module_name} started successfully")
        else:
            print(f"✗ Failed to start module {module_name}")

    async def _cmd_stop(self, args) -> None:
        """Stop a module."""
        if not args:
            print("Error: Please specify a module name")
            print("Usage: stop <module>")
            return

        module_name = args[0]
        running = self.controller.logger_system.get_running_modules()

        if module_name not in running:
            print(f"Error: Module '{module_name}' is not running")
            return

        print(f"Stopping module: {module_name}...")
        success = await self.controller.stop_module(module_name)

        if success:
            print(f"✓ Module {module_name} stopped successfully")
        else:
            print(f"✗ Failed to stop module {module_name}")

    async def _cmd_session(self, args) -> None:
        """Control session."""
        if not args:
            print("Error: Please specify 'start' or 'stop'")
            print("Usage: session start [directory]")
            print("       session stop")
            return

        action = args[0].lower()

        if action == "start":
            if self.controller.session_active:
                print("Error: Session already active")
                return

            session_dir = Path(args[1]) if len(args) > 1 else None

            print("Starting session...")
            success = await self.controller.start_session(session_dir)

            if success:
                status = self.controller.get_status()
                print(f"✓ Session started")
                print(f"  Directory: {status['session_dir']}")
            else:
                print("✗ Failed to start session")

        elif action == "stop":
            if not self.controller.session_active:
                print("Error: No active session")
                return

            print("Stopping session...")
            success = await self.controller.stop_session()

            if success:
                print("✓ Session stopped")
            else:
                print("✗ Failed to stop session")

        else:
            print(f"Error: Unknown session action '{action}'")
            print("Usage: session start [directory]")
            print("       session stop")

    async def _cmd_trial(self, args) -> None:
        """Start a trial (alias for record)."""
        await self._cmd_record(args)

    async def _cmd_record(self, args) -> None:
        """Start recording a trial."""
        if not self.controller.session_active:
            print("Error: No active session. Start a session first.")
            print("Usage: session start [directory]")
            return

        if self.controller.trial_active:
            print("Error: Trial already recording. Pause current trial first.")
            return

        trial_label = " ".join(args) if args else ""

        next_trial = self.controller.trial_counter + 1
        print(f"Starting trial {next_trial}" + (f" (label: {trial_label})" if trial_label else "") + "...")

        success = await self.controller.start_trial(trial_label)

        if success:
            print(f"✓ Recording trial {next_trial}")
        else:
            print("✗ Failed to start trial")

    async def _cmd_pause(self, args=None) -> None:
        """Stop recording the current trial."""
        if not self.controller.trial_active:
            print("Error: No active trial")
            return

        print("Stopping trial...")
        success = await self.controller.stop_trial()

        if success:
            print(f"✓ Trial {self.controller.trial_counter} completed")
        else:
            print("✗ Failed to stop trial")

    async def _cmd_quit(self, args=None) -> None:
        """Quit the shell."""
        print("\nShutting down...")
        self.running = False
        await self.controller.shutdown()
