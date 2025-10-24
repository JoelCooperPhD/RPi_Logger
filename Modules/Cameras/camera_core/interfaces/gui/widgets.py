
import tkinter as tk
from tkinter import ttk


class StatusIndicator(tk.Canvas):

    def __init__(self, parent, size=12, **kwargs):
        super().__init__(parent, width=size, height=size,
                        highlightthickness=0, **kwargs)
        self.size = size
        self.indicator = self.create_oval(2, 2, size-2, size-2,
                                         fill='gray', outline='darkgray')

    def set_status(self, status: str):
        color_map = {
            'active': '#4CAF50',      # Green
            'inactive': '#9E9E9E',    # Gray
            'warning': '#FFC107',     # Amber
            'error': '#F44336',       # Red
            'recording': '#FF5722',   # Deep Orange
        }
        color = color_map.get(status, '#9E9E9E')
        outline_color = self._darken_color(color)
        self.itemconfig(self.indicator, fill=color, outline=outline_color)

    @staticmethod
    def _darken_color(hex_color: str) -> str:
        rgb = int(hex_color[1:], 16)
        r = max(0, ((rgb >> 16) & 0xFF) - 40)
        g = max(0, ((rgb >> 8) & 0xFF) - 40)
        b = max(0, (rgb & 0xFF) - 40)
        return f'#{r:02x}{g:02x}{b:02x}'


class CameraStatsPanel(ttk.LabelFrame):

    def __init__(self, parent, camera_num: int, **kwargs):
        super().__init__(parent, text=f"Camera {camera_num}", **kwargs)
        self.camera_num = camera_num

        status_frame = ttk.Frame(self)
        status_frame.grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=2)

        self.status_indicator = StatusIndicator(status_frame, size=10)
        self.status_indicator.pack(side='left', padx=(0, 5))

        self.status_label = ttk.Label(status_frame, text="Initializing...")
        self.status_label.pack(side='left')

        ttk.Label(self, text="Capture:").grid(row=1, column=0, sticky='w', padx=5)
        self.capture_fps_label = ttk.Label(self, text="0.0 FPS")
        self.capture_fps_label.grid(row=1, column=1, sticky='w')

        ttk.Label(self, text="Processing:").grid(row=2, column=0, sticky='w', padx=5)
        self.processing_fps_label = ttk.Label(self, text="0.0 FPS")
        self.processing_fps_label.grid(row=2, column=1, sticky='w')

        ttk.Label(self, text="Frames:").grid(row=3, column=0, sticky='w', padx=5)
        self.frames_label = ttk.Label(self, text="0 / 0")
        self.frames_label.grid(row=3, column=1, sticky='w')

        ttk.Label(self, text="Recording:").grid(row=4, column=0, sticky='w', padx=5)
        self.recording_label = ttk.Label(self, text="Not recording")
        self.recording_label.grid(row=4, column=1, sticky='w')

    def update_stats(self, stats: dict):
        if stats.get('recording', False):
            self.status_indicator.set_status('recording')
            self.status_label.config(text="Recording")
        else:
            self.status_indicator.set_status('active')
            self.status_label.config(text="Active")

        capture_fps = stats.get('capture_fps', 0.0)
        self.capture_fps_label.config(text=f"{capture_fps:.1f} FPS")

        processing_fps = stats.get('processing_fps', 0.0)
        self.processing_fps_label.config(text=f"{processing_fps:.1f} FPS")

        captured = stats.get('captured_frames', 0)
        processed = stats.get('processed_frames', 0)
        self.frames_label.config(text=f"{processed:,} / {captured:,}")

        output = stats.get('output')
        if output:
            from pathlib import Path
            filename = Path(output).name
            if len(filename) > 30:
                filename = filename[:27] + "..."
            self.recording_label.config(text=filename)
        else:
            self.recording_label.config(text="Not recording")


class ScrollableLogWidget(tk.Frame):

    def __init__(self, parent, height=5, **kwargs):
        super().__init__(parent, **kwargs)

        self.text = tk.Text(self, height=height, wrap='word', state='disabled',
                           bg='#f5f5f5')
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)

        self.text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.text.tag_config('info', foreground='#1976D2')
        self.text.tag_config('warning', foreground='#F57C00')
        self.text.tag_config('error', foreground='#D32F2F')
        self.text.tag_config('success', foreground='#388E3C')

    def append(self, message: str, level: str = 'info'):
        self.text.config(state='normal')
        self.text.insert('end', f"> {message}\n", level)
        self.text.see('end')  # Auto-scroll to bottom
        self.text.config(state='disabled')

    def clear(self):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.config(state='disabled')
