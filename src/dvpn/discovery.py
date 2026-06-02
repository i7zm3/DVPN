import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("dvpn")


@dataclass
class Peer:
    """Represents a discovered peer node."""
    node_id: str
    public_key: str
    endpoint: str
    last_seen: float = field(default_factory=time.time)
    seen_count: int = 0
    reliability: float = 1.0  # 0-1, tracks if peer is reachable

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "public_key": self.public_key,
            "endpoint": self.endpoint,
            "last_seen": self.last_seen,
            "seen_count": self.seen_count,
            "reliability": self.reliability,
        }

    def is_fresh(self, timeout_sec: float = 180.0) -> bool:
        """Check if peer was seen recently."""
        return time.time() - self.last_seen < timeout_sec

    def mark_seen(self) -> None:
        """Update last seen and increment counter."""
        self.last_seen = time.time()
        self.seen_count += 1

    def mark_unreachable(self) -> None:
        """Decrease reliability on failed connection."""
        self.reliability = max(0.0, self.reliability - 0.1)

    def mark_reachable(self) -> None:
        """Increase reliability on successful connection."""
        self.reliability = min(1.0, self.reliability + 0.05)


class PeerRegistry:
    """Manages discovered peers and their health."""

    def __init__(self):
        self.peers: Dict[str, Peer] = {}
        self.lock = __import__("threading").Lock()

    def add_or_update(self, peer: Peer) -> None:
        """Add or update a peer in the registry."""
        with self.lock:
            if peer.node_id in self.peers:
                existing = self.peers[peer.node_id]
                existing.mark_seen()
                existing.endpoint = peer.endpoint  # Update endpoint if changed
            else:
                self.peers[peer.node_id] = peer
                logger.debug("New peer registered: %s", peer.node_id)

    def get_fresh_peers(self, timeout_sec: float = 180.0) -> list:
        """Get all recently-seen peers."""
        with self.lock:
            return [p for p in self.peers.values() if p.is_fresh(timeout_sec)]

    def get_best_peer(self, timeout_sec: float = 180.0) -> Optional[Peer]:
        """
        Select best peer based on:
        - Freshness (recency of last_seen)
        - Reliability (connection success rate)
        - Consistency (seen_count)
        """
        fresh = self.get_fresh_peers(timeout_sec)
        if not fresh:
            return None

        # Scoring: older peers are penalized more
        def peer_score(p: Peer) -> float:
            age = time.time() - p.last_seen
            recency = 1.0 / (1.0 + age / 60.0)  # Decay over 1 minute
            consistency = min(1.0, p.seen_count / 10.0)  # Cap at 10 sightings
            return recency * 0.6 + p.reliability * 0.3 + consistency * 0.1

        return max(fresh, key=peer_score)

    def mark_peer_reachable(self, node_id: str) -> None:
        """Record successful connection to peer."""
        with self.lock:
            if node_id in self.peers:
                self.peers[node_id].mark_reachable()

    def mark_peer_unreachable(self, node_id: str) -> None:
        """Record failed connection to peer."""
        with self.lock:
            if node_id in self.peers:
                self.peers[node_id].mark_unreachable()

    def clear_stale(self, timeout_sec: float = 300.0) -> None:
        """Remove peers not seen recently."""
        with self.lock:
            now = time.time()
            self.peers = {
                k: v
                for k, v in self.peers.items()
                if now - v.last_seen < timeout_sec
            }

    def count(self) -> int:
        """Get number of known peers."""
        with self.lock:
            return len(self.peers)


class EnhancedPeerDiscovery:
    """Improved peer discovery with better filtering and caching."""

    def __init__(self, own_id: str, own_public_key: str, port: int, registry: PeerRegistry):
        self.own_id = own_id
        self.own_public_key = own_public_key
        self.port = port
        self.registry = registry
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.thread = None

    def _build_message(self) -> str:
        """Build discovery announcement payload."""
        payload = {
            "node_id": self.own_id,
            "public_key": self.own_public_key,
            "endpoint": f"{self._local_address()}:{self.port}",
            "timestamp": time.time(),
        }
        return json.dumps(payload)

    def _local_address(self) -> str:
        """Get local IP address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 53))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def start(self) -> None:
        """Start discovery broadcaster and listener."""
        if self.running:
            return
        self.running = True
        self.thread = __import__("threading").Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Enhanced peer discovery started")

    def stop(self) -> None:
        """Stop discovery."""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass

    def _run(self) -> None:
        """Main discovery loop."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("", self.port))
            mreq = socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0")
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self.socket.settimeout(2.0)

            broadcast_interval = 5.0
            last_broadcast = 0.0
            cleanup_interval = 60.0
            last_cleanup = time.time()

            while self.running:
                now = time.time()

                # Broadcast discovery
                if now - last_broadcast > broadcast_interval:
                    try:
                        msg = self._build_message().encode("utf-8")
                        self.socket.sendto(msg, ("239.255.255.250", self.port))
                        last_broadcast = now
                    except Exception as exc:
                        logger.warning("Discovery broadcast failed: %s", exc)

                # Receive discovery responses
                try:
                    data, _ = self.socket.recvfrom(4096)
                    self._process_discovery(data)
                except socket.timeout:
                    pass
                except Exception as exc:
                    logger.debug("Discovery receive error: %s", exc)

                # Periodic cleanup
                if now - last_cleanup > cleanup_interval:
                    self.registry.clear_stale()
                    last_cleanup = now

        except Exception as exc:
            logger.error("Discovery error: %s", exc)
        finally:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass

    def _process_discovery(self, data: bytes) -> None:
        """Process incoming discovery packet."""
        try:
            payload = json.loads(data.decode("utf-8"))
            node_id = payload.get("node_id")
            if not node_id or node_id == self.own_id:
                return
            peer = Peer(
                node_id=node_id,
                public_key=payload.get("public_key", ""),
                endpoint=payload.get("endpoint", ""),
            )
            self.registry.add_or_update(peer)
        except Exception as exc:
            logger.debug("Invalid discovery packet: %s", exc)
