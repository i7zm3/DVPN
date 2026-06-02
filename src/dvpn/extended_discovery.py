"""
Extended peer discovery module for internet-scale DVPN.
Supports relay servers and eventual DHT integration.
"""

import json
import logging
import socket
import threading
import time
from typing import Optional, Dict, List
from dvpn.discovery import Peer

logger = logging.getLogger("dvpn")


class RelayClient:
    """Client for connecting to a relay server for peer discovery."""

    def __init__(self, relay_url: str, node_id: str, public_key: str):
        self.relay_url = relay_url
        self.node_id = node_id
        self.public_key = public_key
        self.connected = False
        self.socket: Optional[socket.socket] = None

    def connect(self) -> bool:
        """Connect to relay server."""
        try:
            host, port = self.relay_url.rsplit(":", 1)
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((host, int(port)))
            self.connected = True
            logger.info("Connected to relay server %s", self.relay_url)
            return True
        except Exception as exc:
            logger.warning("Failed to connect to relay: %s", exc)
            self.connected = False
            return False

    def announce(self, endpoint: str) -> bool:
        """Announce presence to relay."""
        if not self.connected:
            return False
        try:
            msg = {
                "type": "announce",
                "node_id": self.node_id,
                "public_key": self.public_key,
                "endpoint": endpoint,
            }
            self.socket.sendall(json.dumps(msg).encode("utf-8") + b"\n")
            logger.debug("Announced to relay")
            return True
        except Exception as exc:
            logger.warning("Announce failed: %s", exc)
            self.connected = False
            return False

    def get_peers(self) -> List[Peer]:
        """Fetch peer list from relay."""
        if not self.connected:
            return []
        try:
            msg = {"type": "get_peers"}
            self.socket.sendall(json.dumps(msg).encode("utf-8") + b"\n")
            response = self.socket.recv(65536).decode("utf-8")
            data = json.loads(response)
            peers = []
            for p in data.get("peers", []):
                peers.append(Peer(
                    node_id=p["node_id"],
                    public_key=p["public_key"],
                    endpoint=p["endpoint"],
                ))
            logger.debug("Fetched %d peers from relay", len(peers))
            return peers
        except Exception as exc:
            logger.warning("Get peers failed: %s", exc)
            self.connected = False
            return []

    def disconnect(self) -> None:
        """Disconnect from relay."""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.connected = False


class ExtendedDiscovery:
    """Discovery combining LAN and relay-based peer finding."""

    def __init__(self, node_id: str, public_key: str, relay_urls: Optional[List[str]] = None):
        self.node_id = node_id
        self.public_key = public_key
        self.relay_urls = relay_urls or []
        self.relay_clients: Dict[str, RelayClient] = {}
        self.peers: Dict[str, Peer] = {}
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def add_relay(self, relay_url: str) -> None:
        """Add a relay server for discovery."""
        if relay_url not in self.relay_urls:
            self.relay_urls.append(relay_url)
            logger.info("Added relay: %s", relay_url)

    def start(self) -> None:
        """Start extended discovery."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._discover_loop, daemon=True)
        self.thread.start()
        logger.info("Extended discovery started with %d relays", len(self.relay_urls))

    def stop(self) -> None:
        """Stop discovery."""
        self.running = False
        for relay in self.relay_clients.values():
            relay.disconnect()

    def _discover_loop(self) -> None:
        """Main discovery loop."""
        while self.running:
            try:
                # Connect to and query relays
                for relay_url in self.relay_urls:
                    if relay_url not in self.relay_clients:
                        client = RelayClient(relay_url, self.node_id, self.public_key)
                        self.relay_clients[relay_url] = client

                    client = self.relay_clients[relay_url]
                    if not client.connected:
                        client.connect()

                    if client.connected:
                        peers = client.get_peers()
                        for peer in peers:
                            if peer.node_id != self.node_id:
                                self.peers[peer.node_id] = peer

                time.sleep(10)
            except Exception as exc:
                logger.debug("Extended discovery error: %s", exc)
                time.sleep(5)

    def get_peers(self) -> List[Peer]:
        """Get all discovered peers."""
        return list(self.peers.values())
