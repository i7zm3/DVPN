import os
import platform
import subprocess
from pathlib import Path


class StartupManager:
    def __init__(self, app_name: str = "DVPN") -> None:
        self.app_name = app_name
        self.system = platform.system().lower()
        self.cwd = Path.cwd()
        self.command = os.getenv("STARTUP_COMMAND", f"{Path(os.sys.executable)} -m app.main")

    def is_enabled(self) -> bool:
        if self.system == "linux":
            return self._linux_file().exists()
        if self.system == "darwin":
            return self._mac_file().exists()
        if self.system == "windows":
            return self._windows_has_key()
        return False

    def set_enabled(self, enabled: bool) -> None:
        if self.system == "linux":
            self._linux_set(enabled)
            return
        if self.system == "darwin":
            self._mac_set(enabled)
            return
        if self.system == "windows":
            self._windows_set(enabled)
            return
        raise RuntimeError(f"Unsupported OS for startup toggle: {self.system}")

    def _linux_file(self) -> Path:
        return Path.home() / ".config" / "autostart" / "dvpn-native.desktop"

    def _linux_set(self, enabled: bool) -> None:
        file = self._linux_file()
        if not enabled:
            file.unlink(missing_ok=True)
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        line = f"Exec=sh -lc 'cd {self.cwd} && {self.command}'"
        file.write_text(
            "\n".join(
                [
                    "[Desktop Entry]",
                    "Type=Application",
                    f"Name={self.app_name}",
                    line,
                    "X-GNOME-Autostart-enabled=true",
                ]
            )
            + "\n"
        )

    def _mac_file(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / "com.dvpn.native.plist"

    def _mac_set(self, enabled: bool) -> None:
        file = self._mac_file()
        if not enabled:
            subprocess.run(["launchctl", "unload", str(file)], check=False)
            file.unlink(missing_ok=True)
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            "\n".join(
                [
                    '<?xml version="1.0" encoding="UTF-8"?>',
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                    '<plist version="1.0">',
                    "<dict>",
                    "<key>Label</key><string>com.dvpn.native</string>",
                    "<key>ProgramArguments</key>",
                    "<array>",
                    "<string>/bin/sh</string>",
                    "<string>-lc</string>",
                    f"<string>cd {self.cwd} && {self.command}</string>",
                    "</array>",
                    "<key>RunAtLoad</key><true/>",
                    "</dict>",
                    "</plist>",
                ]
            )
            + "\n"
        )
        subprocess.run(["launchctl", "load", str(file)], check=False)

    def _windows_has_key(self) -> bool:
        cmd = [
            "reg",
            "query",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "/v",
            "DVPNNative",
        ]
        return subprocess.run(cmd, capture_output=True, text=True).returncode == 0

    def _windows_set(self, enabled: bool) -> None:
        key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
        if not enabled:
            subprocess.run(["reg", "delete", key, "/v", "DVPNNative", "/f"], check=False)
            return
        command = f'cmd /c "cd /d {self.cwd} && {self.command}"'
        subprocess.run(["reg", "add", key, "/v", "DVPNNative", "/t", "REG_SZ", "/d", command, "/f"], check=True)
