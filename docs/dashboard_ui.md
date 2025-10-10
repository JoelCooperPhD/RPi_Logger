# RPi Logger Dashboard UI

The dashboard is an experimental, Textual-based interface that unifies control of the camera, eye tracker, and audio recorder modules. It runs entirely inside the terminal, rendering a rich interface that works well on constrained Raspberry Pi deployments without requiring a desktop environment.

## Launching

Ensure you are in the project root, then run:

```bash
uv run python ui/dashboard.py
```

The command starts the Textual application in your current terminal session. Press `q` at any time to exit.

## Live overview

- **Module list (left column)** – Each sensor module renders as a card that shows its lifecycle state (offline, starting, reconnecting, ready, recording, or error) along with a short status summary.
- **Details panel (right column)** – Displays richer metrics for the selected module, including recording directories, device counts, frame/gaze statistics, and recently saved files.
- **Activity log (bottom)** – Streams structured log lines with colour-coded severity so you can spot warnings and errors quickly.

## Controls

Keyboard shortcuts are global unless otherwise noted:

| Shortcut | Action |
|----------|--------|
| `s` | Start the selected module |
| `x` | Stop the selected module |
| `space` | Toggle recording for the selected module |
| `r` | Refresh module status (camera: status report, eye tracker: snapshot, audio: device scan) |
| `d` | Open the audio device selector modal (audio module only) |
| `ctrl+l` | Clear the log view |
| `q` | Quit the dashboard |

## Audio device selection

When the audio module is selected, press `d` to open the microphone selector modal. Use the space bar to toggle devices, then press **Save** to apply changes. The dashboard automatically refreshes the audio status so you can confirm the active microphone set. If auto-selection is enabled and no devices are currently chosen, the newest detected microphone is activated automatically.

## Notes & tips

- The dashboard does not automatically start the camera or eye tracker modules. Use `s` on each card when you are ready to begin a session.
- All actions respect the asynchronous backends; long-running operations (for example, camera discovery) keep the UI responsive while running in the background.
- Standard CLI entrypoints remain available and can be used in parallel if you prefer scripting.
- Logs written by the underlying modules continue to be stored on disk when configured; the dashboard only mirrors them for live diagnostics.

## Troubleshooting

- **No modules appear** – Ensure you are running from the repository root so relative paths resolve correctly.
- **Camera or eye tracker never reaches READY** – Verify sensors are connected and powered. The dashboard surfaces warning/error states in the log view.
- **Audio modal is empty** – The system did not detect microphones. Run `arecord -l` in a separate terminal to confirm the OS can see the devices.

Feedback on the dashboard workflow is welcome—the UI is intended to evolve into the primary control surface for the logger.
