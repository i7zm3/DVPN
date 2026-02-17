import threading


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {
            "dvpn_connect_success_total": 0,
            "dvpn_connect_failure_total": 0,
            "dvpn_fallback_attempt_total": 0,
            "dvpn_payment_failure_total": 0,
            "dvpn_node_register_success_total": 0,
            "dvpn_node_register_failure_total": 0,
        }
        self._gauges: dict[str, float] = {
            "dvpn_active_connections": 0,
            "dvpn_bandwidth_total_mbps": 0,
            "dvpn_last_granted_mbps": 0,
        }

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def render_prometheus(self) -> str:
        with self._lock:
            lines: list[str] = []
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
            return "\n".join(lines) + "\n"
