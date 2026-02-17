import json
import sys
import urllib.request
import webbrowser
from pathlib import Path


def _call(endpoint: str, action: str) -> None:
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/{action}", data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=3):
        return


def _get_status(endpoint: str) -> dict:
    with urllib.request.urlopen(f"{endpoint.rstrip('/')}/status", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_logs(endpoint: str) -> list[str]:
    with urllib.request.urlopen(f"{endpoint.rstrip('/')}/logs", timeout=3) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("logs", [])


def run_tray_qt(endpoint: str, payment_portal_url: str) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv)
    icon_path = Path("assets/dvpn-tray.png")
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("DVPN")

    menu = QMenu()
    start_action = QAction("Start", menu)
    stop_action = QAction("Stop", menu)
    restart_action = QAction("Restart", menu)
    start_boot_action = QAction("Start On Boot", menu)
    start_boot_action.setCheckable(True)
    killswitch_action = QAction("Killswitch", menu)
    killswitch_action.setCheckable(True)
    logs_action = QAction("Logs", menu)
    payments_action = QAction("Payments", menu)
    exit_action = QAction("Exit", menu)

    start_action.triggered.connect(lambda: _call(endpoint, "start"))
    stop_action.triggered.connect(lambda: _call(endpoint, "stop"))
    restart_action.triggered.connect(lambda: _call(endpoint, "restart"))
    start_boot_action.triggered.connect(lambda: _call(endpoint, "start_on_boot"))
    killswitch_action.triggered.connect(lambda: _call(endpoint, "killswitch"))
    logs_action.triggered.connect(lambda: print("\n".join(_get_logs(endpoint))))
    payments_action.triggered.connect(lambda: (_call(endpoint, "payments"), webbrowser.open(payment_portal_url)))
    exit_action.triggered.connect(lambda: (_call(endpoint, "exit"), app.quit()))

    for action in [start_action, stop_action, restart_action, start_boot_action, killswitch_action, logs_action, payments_action, exit_action]:
        menu.addAction(action)

    tray.setContextMenu(menu)
    tray.show()

    def refresh_checks() -> None:
        try:
            status = _get_status(endpoint)
            start_boot_action.setChecked(bool(status.get("start_on_boot", False)))
            killswitch_action.setChecked(bool(status.get("killswitch_enabled", False)))
        except Exception:
            return

    timer = QTimer()
    timer.timeout.connect(refresh_checks)
    timer.start(3000)
    refresh_checks()
    app.exec()
