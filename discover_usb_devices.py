#!/usr/bin/env python3
import serial.tools.list_ports

def discover_usb_serial_devices():
    print("=" * 80)
    print("USB Serial Device Discovery")
    print("=" * 80)

    ports = serial.tools.list_ports.comports()

    if not ports:
        print("\nNo serial devices found!")
        return

    print(f"\nFound {len(ports)} serial device(s):\n")

    for idx, port in enumerate(ports, 1):
        print(f"Device {idx}:")
        print(f"  Port:         {port.device}")
        print(f"  Description:  {port.description}")
        print(f"  Manufacturer: {port.manufacturer}")
        print(f"  VID:          0x{port.vid:04X}" if port.vid else "  VID:          None")
        print(f"  PID:          0x{port.pid:04X}" if port.pid else "  PID:          None")
        print(f"  Serial:       {port.serial_number}")
        print(f"  Location:     {port.location}")
        print(f"  HWID:         {port.hwid}")
        print()

    print("=" * 80)
    print("Please identify which device is your sDRT and note its VID and PID values.")
    print("=" * 80)

if __name__ == "__main__":
    discover_usb_serial_devices()
