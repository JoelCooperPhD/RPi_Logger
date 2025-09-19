#!/usr/bin/env python3
"""
Simple Car Data Logger - Main Controller
Coordinates all data logging modules in separate processes
"""
from multiprocessing import Process, Queue
import time
import sys
import os
import importlib.util
from pathlib import Path

class CarDataLogger:
    def __init__(self):
        self.modules = []
        self.current_session = None
        self.running = True
        
        # Create data directory if it doesn't exist
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        
    def start_module(self, module_name, module_file):
        """Start a module in its own process"""
        if not os.path.exists(module_file):
            print(f"Warning: Module file {module_file} not found, skipping...")
            return None
            
        try:
            # Create communication queues for this module
            command_queue = Queue()
            status_queue = Queue()
            
            # Dynamically import the module
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Check if module has the required run_in_process function
            if not hasattr(module, 'run_in_process'):
                print(f"Warning: {module_file} doesn't have run_in_process function, skipping...")
                return None
            
            # Start the module process
            process = Process(target=module.run_in_process, args=(command_queue, status_queue))
            process.start()
            
            module_info = {
                'name': module_name,
                'file': module_file,
                'process': process,
                'command_queue': command_queue,
                'status_queue': status_queue,
                'last_status': 'starting',
                'start_time': time.time()
            }
            
            self.modules.append(module_info)
            print(f"Started {module_name} module (PID: {process.pid})")
            return module_info
            
        except Exception as e:
            print(f"Error starting {module_name}: {e}")
            return None
    
    def send_command_to_module(self, module_name, command):
        """Send command to specific module"""
        for module in self.modules:
            if module['name'] == module_name:
                try:
                    module['command_queue'].put(command, timeout=1)
                    return True
                except Exception as e:
                    print(f"Error sending command to {module_name}: {e}")
                    return False
        print(f"Module {module_name} not found")
        return False
    
    def broadcast_command(self, command):
        """Send command to all modules"""
        success_count = 0
        for module in self.modules:
            try:
                module['command_queue'].put(command, timeout=1)
                success_count += 1
            except Exception as e:
                print(f"Error sending command to {module['name']}: {e}")
        
        print(f"Command sent to {success_count}/{len(self.modules)} modules")
        return success_count
    
    def collect_status(self):
        """Collect status updates from all modules"""
        status_updates = []
        
        for module in self.modules:
            while not module['status_queue'].empty():
                try:
                    status = module['status_queue'].get_nowait()
                    status_updates.append(status)
                    module['last_status'] = status.get('status', 'unknown')
                    
                    # Print status update
                    timestamp = time.strftime('%H:%M:%S', time.localtime(status.get('timestamp', time.time())))
                    print(f"[{timestamp}] {status['module']}: {status['status']}")
                    
                except Exception as e:
                    print(f"Error reading status from {module['name']}: {e}")
                    break
        
        return status_updates
    
    def check_module_health(self):
        """Check if modules are still running and healthy"""
        dead_modules = []
        
        for module in self.modules:
            if not module['process'].is_alive():
                exit_code = module['process'].exitcode
                print(f"WARNING: Module {module['name']} has died (exit code: {exit_code})")
                dead_modules.append(module)
        
        # Remove dead modules from the list
        for dead_module in dead_modules:
            self.modules.remove(dead_module)
        
        return len(dead_modules) == 0
    
    def show_status(self):
        """Display current system status"""
        print("\n" + "="*50)
        print("SYSTEM STATUS")
        print("="*50)
        print(f"Active Session: {self.current_session or 'None'}")
        print(f"Running Modules: {len(self.modules)}")
        print()
        
        for i, module in enumerate(self.modules, 1):
            uptime = int(time.time() - module['start_time'])
            status = "RUNNING" if module['process'].is_alive() else "DEAD"
            print(f"{i}. {module['name']}")
            print(f"   Status: {status}")
            print(f"   Last Update: {module['last_status']}")
            print(f"   Uptime: {uptime}s")
            print(f"   PID: {module['process'].pid}")
            print()
    
    def start_recording_session(self):
        """Start a new recording session"""
        if self.current_session:
            print("Session already active. Stop current session first.")
            return False
        
        # Generate session name with timestamp
        session_name = time.strftime("session_%Y%m%d_%H%M%S")
        
        print(f"\nStarting recording session: {session_name}")
        
        # Create session directory
        session_dir = self.data_dir / session_name
        session_dir.mkdir(exist_ok=True)
        
        # Send start command to all modules
        command = {
            'action': 'start_session',
            'session_name': session_name,
            'session_dir': str(session_dir)
        }
        
        success_count = self.broadcast_command(command)
        
        if success_count > 0:
            self.current_session = session_name
            print(f"Session '{session_name}' started successfully")
            return True
        else:
            print("Failed to start session - no modules responded")
            return False
    
    def stop_recording_session(self):
        """Stop current recording session"""
        if not self.current_session:
            print("No active session to stop")
            return False
        
        print(f"\nStopping recording session: {self.current_session}")
        
        command = {'action': 'stop_session'}
        success_count = self.broadcast_command(command)
        
        if success_count > 0:
            print(f"Session '{self.current_session}' stopped successfully")
            self.current_session = None
            return True
        else:
            print("Failed to stop session - no modules responded")
            return False
    
    def restart_module(self, module_name):
        """Restart a specific module"""
        # Find the module
        target_module = None
        for module in self.modules:
            if module['name'] == module_name:
                target_module = module
                break
        
        if not target_module:
            print(f"Module {module_name} not found")
            return False
        
        print(f"Restarting module {module_name}...")
        
        # Stop the module
        try:
            target_module['command_queue'].put({'action': 'shutdown'}, timeout=1)
            target_module['process'].join(timeout=3)
            if target_module['process'].is_alive():
                target_module['process'].terminate()
        except:
            pass
        
        # Remove from modules list
        self.modules.remove(target_module)
        
        # Restart it
        new_module = self.start_module(target_module['name'], target_module['file'])
        return new_module is not None
    
    def shutdown_all_modules(self):
        """Gracefully shutdown all modules"""
        if not self.modules:
            return
        
        print("\nShutting down all modules...")
        
        # Send shutdown command to all modules
        shutdown_command = {'action': 'shutdown'}
        for module in self.modules:
            try:
                module['command_queue'].put(shutdown_command, timeout=1)
            except:
                pass  # Queue might be closed or full
        
        # Wait for graceful shutdown
        for module in self.modules:
            print(f"Waiting for {module['name']} to shutdown...")
            module['process'].join(timeout=5)  # Wait up to 5 seconds
            
            # Force terminate if still alive
            if module['process'].is_alive():
                print(f"Force terminating {module['name']}")
                module['process'].terminate()
                module['process'].join()  # Wait for termination
        
        self.modules.clear()
        print("All modules stopped")
    
    def run_interactive_mode(self):
        """Run the interactive command-line interface"""
        print("Car Data Logger Started")
        print("Type 'help' for available commands")
        
        try:
            while self.running:
                # Collect any status updates
                self.collect_status()
                
                # Check module health
                self.check_module_health()
                
                # Show prompt
                session_indicator = f"[{self.current_session}]" if self.current_session else ""
                prompt = f"\ncar-logger{session_indicator}> "
                
                try:
                    command = input(prompt).strip().lower()
                except EOFError:
                    break
                
                if not command:
                    continue
                
                # Process commands
                if command == 'help' or command == 'h':
                    self.show_help()
                elif command == 'start' or command == '1':
                    self.start_recording_session()
                elif command == 'stop' or command == '2':
                    self.stop_recording_session()
                elif command == 'status' or command == '3':
                    self.show_status()
                elif command == 'quit' or command == 'q' or command == '4':
                    self.running = False
                elif command.startswith('restart '):
                    module_name = command.split(' ', 1)[1]
                    self.restart_module(module_name)
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'help' for available commands")
        
        except KeyboardInterrupt:
            print("\nReceived interrupt signal...")
        
        finally:
            self.shutdown_all_modules()
    
    def show_help(self):
        """Show available commands"""
        print("\nAvailable Commands:")
        print("  start (1)     - Start recording session")
        print("  stop (2)      - Stop current recording session") 
        print("  status (3)    - Show system and module status")
        print("  restart <mod> - Restart specific module")
        print("  help (h)      - Show this help")
        print("  quit (q)      - Quit the application")

def main():
    """Main entry point"""
    print("Initializing Car Data Logger...")
    
    # Create the main logger instance
    logger = CarDataLogger()
    
    # Start all available modules
    available_modules = [
        ("camera", "RPiCam.py"),
        ("gps", "GPS_logger.py"),
        ("obd", "OBD_reader.py"),
        ("sensors", "sensor_hub.py")
    ]
    
    started_modules = 0
    for name, filename in available_modules:
        if logger.start_module(name, filename):
            started_modules += 1
    
    if started_modules == 0:
        print("No modules could be started. Exiting...")
        sys.exit(1)
    
    print(f"Successfully started {started_modules} modules")
    
    # Give modules time to initialize
    time.sleep(2)
    
    # Collect any initialization status
    logger.collect_status()
    
    # Run the interactive interface
    logger.run_interactive_mode()
    
    print("Car Data Logger stopped")

if __name__ == "__main__":
    main()