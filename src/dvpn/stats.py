import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConnectionStats:
    """Track connection quality metrics for a peer."""
    peer_id: str
    connected_at: float = field(default_factory=time.time)
    bytes_sent: int = 0
    bytes_received: int = 0
    latency_ms: float = 0.0
    connection_duration: float = 0.0
    handshake_count: int = 0
    last_handshake: float = field(default_factory=time.time)
    is_active: bool = False

    def quality_score(self) -> float:
        """
        Calculate a quality score (0-100) based on connection metrics.
        Higher is better.
        """
        score = 50.0
        
        # Favor lower latency
        if self.latency_ms < 10:
            score += 20
        elif self.latency_ms < 50:
            score += 10
        elif self.latency_ms > 200:
            score -= 15

        # Favor longer connections
        if self.connection_duration > 300:
            score += 15
        elif self.connection_duration > 60:
            score += 5

        # Favor recent handshakes
        time_since_handshake = time.time() - self.last_handshake
        if time_since_handshake < 30:
            score += 10
        elif time_since_handshake > 120:
            score -= 10

        # Penalize inactive connections
        if not self.is_active:
            score -= 20

        return max(0.0, min(100.0, score))

    def update_duration(self) -> None:
        """Update connection duration."""
        self.connection_duration = time.time() - self.connected_at

    def record_handshake(self) -> None:
        """Record a successful handshake."""
        self.last_handshake = time.time()
        self.handshake_count += 1
