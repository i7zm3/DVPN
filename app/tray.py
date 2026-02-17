import json
import urllib.request
import webbrowser


def _call(endpoint: str, action: str) -> None:
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/{action}", data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=3):
        return


def run_tray(endpoint: str, payment_portal_url: str) -> None:
    try:
        import pystray
        from PIL import Image
    except Exception:
        print("[dvpn] pystray/Pillow not installed; tray icon disabled")
        return

    image = Image.new("RGB", (64, 64), color=(0, 120, 255))

    def start_action(icon, item):
        _call(endpoint, "start")

    def stop_action(icon, item):
        _call(endpoint, "stop")

    def logs_action(icon, item):
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/logs", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        print("\n".join(data.get("logs", [])))

    def payments_action(icon, item):
        _call(endpoint, "payments")
        webbrowser.open(payment_portal_url)

    def exit_action(icon, item):
        _call(endpoint, "exit")
        icon.stop()

    icon = pystray.Icon(
        "dvpn",
        image,
        "DVPN",
        menu=pystray.Menu(
            pystray.MenuItem("Start", start_action),
            pystray.MenuItem("Stop", stop_action),
            pystray.MenuItem("Logs", logs_action),
            pystray.MenuItem("Payments", payments_action),
            pystray.MenuItem("Exit", exit_action),
        ),
    )
    icon.run()
