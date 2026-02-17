import json
import os
import urllib.request
import webbrowser
from pathlib import Path

from app.tray_qt import run_tray_qt


def _call(endpoint: str, action: str) -> None:
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/{action}", data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=3):
        return


def _get_status(endpoint: str) -> dict:
    with urllib.request.urlopen(f"{endpoint.rstrip('/')}/status", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def run_tray(endpoint: str, payment_portal_url: str) -> None:
    backend = os.getenv("TRAY_BACKEND", "auto").lower()
    if backend in ("qt", "auto"):
        try:
            run_tray_qt(endpoint, payment_portal_url)
            return
        except Exception as err:
            if backend == "qt":
                print(f"[dvpn] qt tray failed: {err}")
                return
            print(f"[dvpn] qt tray unavailable, falling back to pystray: {err}")

    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        print("[dvpn] pystray/Pillow not installed; tray icon disabled")
        return

    def icon_image() -> "Image.Image":
        icon_path = Path("assets/dvpn-tray.png")
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA")
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, size - 2, size - 2), fill=(12, 34, 56, 255), outline=(94, 178, 255, 255), width=2)
        shield = [(32, 10), (50, 18), (46, 40), (32, 54), (18, 40), (14, 18)]
        d.polygon(shield, fill=(35, 150, 255, 255), outline=(200, 235, 255, 255))
        d.line((22, 33, 30, 41, 43, 24), fill=(240, 250, 255, 255), width=4)
        return img

    image = icon_image()

    def start_action(icon, item):
        _call(endpoint, "start")

    def restart_action(icon, item):
        _call(endpoint, "restart")

    def stop_action(icon, item):
        _call(endpoint, "stop")

    def logs_action(icon, item):
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/logs", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        print("\n".join(data.get("logs", [])))

    def start_on_boot_action(icon, item):
        _call(endpoint, "start_on_boot")

    def killswitch_action(icon, item):
        _call(endpoint, "killswitch")

    def payments_action(icon, item):
        _call(endpoint, "payments")
        webbrowser.open(payment_portal_url)

    def exit_action(icon, item):
        _call(endpoint, "exit")
        icon.stop()

    def start_on_boot_checked(item):
        try:
            return bool(_get_status(endpoint).get("start_on_boot"))
        except Exception:
            return False

    def killswitch_checked(item):
        try:
            return bool(_get_status(endpoint).get("killswitch_enabled"))
        except Exception:
            return False

    icon = pystray.Icon(
        "dvpn",
        image,
        "DVPN",
        menu=pystray.Menu(
            pystray.MenuItem("Start", start_action),
            pystray.MenuItem("Stop", stop_action),
            pystray.MenuItem("Restart", restart_action),
            pystray.MenuItem("Start On Boot", start_on_boot_action, checked=start_on_boot_checked),
            pystray.MenuItem("Killswitch", killswitch_action, checked=killswitch_checked),
            pystray.MenuItem("Logs", logs_action, default=True),
            pystray.MenuItem("Payments", payments_action),
            pystray.MenuItem("Exit", exit_action),
        ),
    )
    icon.run()
