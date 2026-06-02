import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext

from dvpn.core import DVPNService, LOG_DIR


class DVPNApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DVPN")
        self.root.geometry("700x500")
        self.service = DVPNService()
        self._build_ui()
        self._update_ui_loop()

    def _build_ui(self) -> None:
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill=tk.X, padx=12, pady=12)

        self.status_label = tk.Label(top_frame, text="Status: stopped", anchor="w")
        self.status_label.pack(fill=tk.X)

        button_frame = tk.Frame(top_frame)
        button_frame.pack(fill=tk.X, pady=(8, 0))

        self.start_button = tk.Button(button_frame, text="Start DVPN", command=self.start_service)
        self.start_button.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_button = tk.Button(button_frame, text="Stop DVPN", command=self.stop_service, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)

        log_label = tk.Label(self.root, text="Local logs")
        log_label.pack(anchor="w", padx=12)

        self.log_text = scrolledtext.ScrolledText(self.root, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

    def start_service(self) -> None:
        def run_service():
            try:
                self.service.start()
            except Exception as exc:
                self._append_log(f"Error starting service: {exc}")

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="Status: starting")
        threading.Thread(target=run_service, daemon=True).start()

    def stop_service(self) -> None:
        self.service.stop()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="Status: stopped")
        self._append_log("DVPN stopped")

    def _append_log(self, message: str) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _read_log_file(self) -> None:
        log_file = LOG_DIR / "dvpn.log"
        if not log_file.exists():
            return
        try:
            with open(log_file, "r", encoding="utf-8") as handle:
                lines = handle.readlines()[-200:]
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete("1.0", tk.END)
            self.log_text.insert(tk.END, "".join(lines))
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _update_ui_loop(self) -> None:
        self._read_log_file()
        status = "running" if self.service.running else "stopped"
        self.status_label.config(text=f"Status: {status}")
        self.root.after(2000, self._update_ui_loop)

    def run(self) -> None:
        self.root.mainloop()
