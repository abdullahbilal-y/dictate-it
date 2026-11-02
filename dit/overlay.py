import threading
import queue
import time
import tkinter as tk

class StatusOverlay:
    """Non-blocking floating status badge that shows recording and transcription state."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._cmd_queue = queue.Queue()
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run_tk, daemon=True)
            self._thread.start()

    def _run_tk(self):
        try:
            root = tk.Tk()
            self.root = root
            root.title("D^it Status")
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.88)
            root.config(bg="#1e1e2e")

            # Center top of screen
            screen_width = root.winfo_screenwidth()
            w, h = 220, 42
            x = (screen_width - w) // 2
            y = 35
            root.geometry(f"{w}x{h}+{x}+{y}")

            self.label = tk.Label(
                root,
                text="",
                font=("Segoe UI", 11, "bold"),
                bg="#1e1e2e",
                fg="#ffffff"
            )
            self.label.pack(expand=True, fill="both")
            root.withdraw()

            def _poll():
                try:
                    while not self._cmd_queue.empty():
                        cmd, arg = self._cmd_queue.get_nowait()
                        if cmd == "show":
                            text, color = arg
                            self.label.config(text=text, fg=color)
                            root.deiconify()
                            root.lift()
                        elif cmd == "hide":
                            root.withdraw()
                except Exception:
                    pass
                root.after(50, _poll)

            root.after(50, _poll)
            root.mainloop()
        except Exception as e:
            print(f"[Overlay] GUI disabled: {e}")

    def show_recording(self):
        if not self.enabled:
            return
        self._cmd_queue.put(("show", ("🎙️  Listening...", "#ff5555")))

    def show_transcribing(self):
        if not self.enabled:
            return
        self._cmd_queue.put(("show", ("⚡  Transcribing...", "#f1fa8c")))

    def show_success(self, snippet: str = ""):
        if not self.enabled:
            return
        display = "✓  Dictated"
        self._cmd_queue.put(("show", (display, "#50fa7b")))
        # Auto hide after 1.2s
        def _delay_hide():
            time.sleep(1.2)
            self.hide()
        threading.Thread(target=_delay_hide, daemon=True).start()

    def hide(self):
        if not self.enabled:
            return
        self._cmd_queue.put(("hide", None))
