import ssl
import threading
import time
import urllib.request


def measure_throughput_mbps(test_url: str, timeout: int = 8, sample_seconds: int = 4) -> float:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    start = time.time()
    total = 0
    with urllib.request.urlopen(test_url, timeout=timeout, context=context) as response:
        while time.time() - start < sample_seconds:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
    duration = max(time.time() - start, 0.001)
    bits_per_second = (total * 8) / duration
    return bits_per_second / 1_000_000


class BandwidthAllocator:
    def __init__(self, total_mbps: float, fraction_per_connection: float = 0.5) -> None:
        self.total_mbps = max(total_mbps, 0.1)
        self.fraction_per_connection = max(min(fraction_per_connection, 1.0), 0.01)
        self._lock = threading.Lock()
        self._active: dict[str, float] = {}

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def open_connection(self, connection_id: str) -> float:
        with self._lock:
            # Per request: allocate 1/2 total bandwidth per new connection event.
            requested = self.total_mbps * self.fraction_per_connection
            remaining = max(self.total_mbps - sum(self._active.values()), 0.0)
            granted = min(requested, remaining)
            self._active[connection_id] = granted
            return granted

    def close_connection(self, connection_id: str) -> None:
        with self._lock:
            self._active.pop(connection_id, None)
