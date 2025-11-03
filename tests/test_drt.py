import asyncio
import threading
import types
import unittest
import io
from pathlib import Path
from types import SimpleNamespace

from Modules.DRT.drt_core.drt_system import DRTSystem
from Modules.DRT.drt_core.drt_handler import DRTHandler
from Modules.base.usb_serial_manager import USBDeviceMonitor, USBDeviceConfig
from logger_core.commands import StatusMessage


class FakeHandler:
    def __init__(self, start_result=True, stop_result=True):
        self.start_result = start_result
        self.stop_result = stop_result
        self.start_calls = 0
        self.stop_experiment_calls = 0
        self.stop_calls = 0

    async def start_experiment(self):
        self.start_calls += 1
        return self.start_result

    async def stop_experiment(self):
        self.stop_experiment_calls += 1
        return self.stop_result

    async def stop(self):
        self.stop_calls += 1


class DummyDevice:
    def __init__(self, responses):
        self.responses = list(responses)
        self.write_calls = []
        self.is_connected = True

    async def write(self, data: bytes) -> bool:
        self.write_calls.append(data)
        if self.responses:
            return self.responses.pop(0)
        return True


class DRTSystemRecordingTests(unittest.IsolatedAsyncioTestCase):
    def _make_system(self) -> DRTSystem:
        args = SimpleNamespace(
            mode='gui',
            enable_commands=False,
            session_dir=Path('session'),
            output_dir=Path('output'),
            device_vid=0x239A,
            device_pid=0x801E,
            baudrate=9600,
            auto_start_recording=False,
            window_geometry=None,
        )
        system = DRTSystem(args)
        system.initialized = True
        return system

    async def test_start_recording_success(self):
        system = self._make_system()
        handler_a = FakeHandler()
        handler_b = FakeHandler()
        system.device_handlers = {'a': handler_a, 'b': handler_b}

        result = await system.start_recording()

        self.assertTrue(result)
        self.assertTrue(system.recording)
        self.assertEqual(handler_a.start_calls, 1)
        self.assertEqual(handler_b.start_calls, 1)

    async def test_start_recording_rolls_back_on_failure(self):
        system = self._make_system()
        successful = FakeHandler()
        failing = FakeHandler(start_result=False)
        system.device_handlers = {'good': successful, 'bad': failing}

        result = await system.start_recording()

        self.assertFalse(result)
        self.assertFalse(system.recording)
        self.assertEqual(successful.stop_experiment_calls, 1)
        self.assertEqual(failing.start_calls, 1)

    async def test_stop_recording_failure_preserves_state(self):
        system = self._make_system()
        successful = FakeHandler()
        failing = FakeHandler(stop_result=False)
        system.device_handlers = {'good': successful, 'bad': failing}
        system.recording = True

        result = await system.stop_recording()

        self.assertFalse(result)
        self.assertTrue(system.recording)
        self.assertEqual(successful.stop_experiment_calls, 1)
        self.assertEqual(failing.stop_experiment_calls, 1)

    async def test_iso_params_failure_returns_false(self):
        device = DummyDevice([True, False, True, True])
        handler = DRTHandler(device, 'ttyUSB0', Path('.'))

        result = await handler.set_iso_params()

        self.assertFalse(result)
        self.assertEqual(len(device.write_calls), 4)

    async def test_iso_params_success_returns_true(self):
        device = DummyDevice([True, True, True, True])
        handler = DRTHandler(device, 'ttyUSB0', Path('.'))

        result = await handler.set_iso_params()

        self.assertTrue(result)
        self.assertEqual(len(device.write_calls), 4)


    async def test_process_response_emits_status(self):
        stream = io.StringIO()
        handler = DRTHandler(DummyDevice([]), 'ttyUSB0', Path('.'), system=SimpleNamespace(enable_gui_commands=True))
        previous = StatusMessage.output_stream
        StatusMessage.configure(stream)
        try:
            await handler._process_response('CLK>1')
        finally:
            StatusMessage.configure(previous)

        payload = stream.getvalue()
        self.assertIn('drt_event', payload)
        self.assertIn('click_count', payload)


class USBDeviceMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_from_different_loop(self):
        config = USBDeviceConfig(vid=0x1234, pid=0x5678)
        monitor = USBDeviceMonitor(config)

        async def fake_scan(self):
            await asyncio.sleep(0)

        monitor._scan_devices = types.MethodType(fake_scan, monitor)

        loop_holder = {}
        loop_ready = threading.Event()

        def run_loop():
            loop = asyncio.new_event_loop()
            loop_holder['loop'] = loop
            asyncio.set_event_loop(loop)
            loop.run_until_complete(monitor.start())
            loop_ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        try:
            self.assertTrue(loop_ready.wait(timeout=2), 'Monitor loop did not start in time')
            self.assertTrue(monitor._running)

            await monitor.stop()

            async def wait_until_stopped():
                while monitor._running:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(wait_until_stopped(), timeout=1)
        finally:
            loop = loop_holder.get('loop')
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)

        self.assertFalse(monitor._running)


if __name__ == '__main__':
    unittest.main()
