import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk

from dvpn.core import DVPNService, logger

LOG_DIR = Path.home() / ".dvpn" / "logs"


class DVPNApp:
    """Enhanced DVPN UI with peer info and connection stats."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DVPN - Distributed VPN")
        self.root.geometry("1000x700")
        self.service = DVPNService()
        self.ui_thread: threading.Thread | None = None
        self._build_ui()
        self._update_loop()

    def _build_ui(self) -> None:
        """Build the main UI layout."""
        # Top control bar
        control_frame = tk.Frame(self.root, bg="#f0f0f0", height=60)
        control_frame.pack(fill=tk.X, side=tk.TOP)
        control_frame.pack_propagate(False)

        tk.Label(control_frame, text="DVPN", font=("Arial", 18, "bold"), bg="#f0f0f0").pack(side=tk.LEFT, padx=12, pady=8)

        self.status_label = tk.Label(control_frame, text="Status: Stopped", font=("Arial", 12), bg="#f0f0f0", fg="#666")
        self.status_label.pack(side=tk.LEFT, padx=12)

        button_frame = tk.Frame(control_frame, bg="#f0f0f0")
        button_frame.pack(side=tk.RIGHT, padx=12, pady=8)

        self.start_btn = tk.Button(button_frame, text="Start", command=self.start_service, width=10, bg="#4CAF50", fg="white")
        self.start_btn.pack(side=tk.LEFT, padx=4)

        self.stop_btn = tk.Button(button_frame, text="Stop", command=self.stop_service, width=10, bg="#f44336", fg="white", state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        # Notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Status tab
        status_frame = tk.Frame(notebook)
        notebook.add(status_frame, text="Status & Info")
        self._build_status_tab(status_frame)

        # Peers tab
        peers_frame = tk.Frame(notebook)
        notebook.add(peers_frame, text="Peers")
        self._build_peers_tab(peers_frame)

        # Logs tab
        logs_frame = tk.Frame(notebook)
        notebook.add(logs_frame, text="Logs")
        self._build_logs_tab(logs_frame)

    def _build_status_tab(self, parent: tk.Frame) -> None:
        """Build status and info display."""
        info_frame = tk.LabelFrame(parent, text="Connection Status", padx=12, pady=8)
        info_frame.pack(fill=tk.X, padx=8, pady=8)

        self.info_labels = {}
        fields = [
            ("Service Status", "service_status"),
            ("Node ID", "node_id"),
            ("Current Peer", "current_peer"),
            ("Known Peers", "known_peers"),
            ("Connection Uptime", "uptime"),
            ("Kill Switch", "kill_switch"),
            ("IPv6 Status", "ipv6_status"),
        ]

        for label_text, key in fields:
            row = tk.Frame(info_frame)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=f"{label_text}:", width=20, anchor="w", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
            label = tk.Label(row, text="—", width=40, anchor="w", font=("Arial", 10), fg="#333")
            label.pack(side=tk.LEFT, padx=8)
            self.info_labels[key] = label

    def _build_peers_tab(self, parent: tk.Frame) -> None:
        """Build peer list display."""
        tk.Label(parent, text="Discovered Peers", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=8)
        self.peers_text = scrolledtext.ScrolledText(parent, height=20, state=tk.DISABLED, wrap=tk.WORD)
        self.peers_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def _build_logs_tab(self, parent: tk.Frame) -> None:
        """Build logs display."""
        tk.Label(parent, text="Local Logs (~/.dvpn/logs/dvpn.log)", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=8)
        self.log_text = scrolledtext.ScrolledText(parent, height=20, state=tk.DISABLED, wrap=tk.WORD, font=("Courier", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def start_service(self) -> None:
        """Start DVPN service."""
        def run():
            try:
                self.service.start()
            except Exception as exc:
                self._log_message(f"Error: {exc}")

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.ui_thread = threading.Thread(target=run, daemon=True)
        self.ui_thread.start()

    def stop_service(self) -> None:
        """Stop DVPN service."""
        self.service.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._log_message("DVPN service stopped")

    def _log_message(self, msg: str) -> None:
        """Add message to log display."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _update_loop(self) -> None:
        """Update UI periodically."""
        try:
            # Update status
            status = self.service.get_status()
            self.status_label.config(text=f"Status: {'Running' if status['running'] else 'Stopped'}")
            
            # Update info labels
            self.info_labels["service_status"].config(text="Running" if status["running"] else "Stopped")
            self.info_labels["node_id"].config(text=status["node_id"])
            self.info_labels["current_peer"].config(text=status["current_peer"])
            self.info_labels["known_peers"].config(text=str(status["known_peers"]))
            uptime_str = f"{status['uptime']:.1f}s" if status["uptime"] > 0 else "—"
            self.info_labels["uptime"].config(text=uptime_str)
            self.info_labels["kill_switch"].config(text="Enabled" if status["kill_switch"] else "Disabled", fg="#4CAF50" if status["kill_switch"] else "#666")
            self.info_labels["ipv6_status"].config(text="Disabled", fg="#4CAF50")

            # Update peers list
            if status["running"] and self.service.peer_registry:
                fresh = self.service.peer_registry.get_fresh_peers()
                peers_text = f"Total: {len(fresh)}\n\n"
                for peer in sorted(fresh, key=lambda p: p.reliability, reverse=True):
                    peers_text += f"Node: {peer.node_id[:8]}\n"
                    peers_text += f"  Endpoint: {peer.endpoint}\n"
                    peers_text += f"  Reliability: {peer.reliability:.1%}\n"
                    peers_text += f"  Last Seen: {time.time() - peer.last_seen:.0f}s ago\n"
                    peers_text += f"  Sightings: {peer.seen_count}\n\n"
                
                self.peers_text.config(state=tk.NORMAL)
                self.peers_text.delete("1.0", tk.END)
                self.peers_text.insert(tk.END, peers_text)
                self.peers_text.config(state=tk.DISABLED)

            # Update logs
            log_file = LOG_DIR / "dvpn.log"
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-100:]
                log_text = "".join(lines)
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete("1.0", tk.END)
                self.log_text.insert(tk.END, log_text)
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)

        except Exception as exc:
            logger.debug("UI update error: %s", exc)

        self.root.after(2000, self._update_loop)

    def run(self) -> None:
        """Start the application."""
        self.root.mainloop()
