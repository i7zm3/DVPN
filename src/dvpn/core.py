import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from dvpn.discovery import EnhancedPeerDiscovery, Peer, PeerRegistry
from dvpn.stats import ConnectionStats

CONF_DIR = Path.home() / ".dvpn"
LOG_DIR = CONF_DIR / "logs"
WG_CONFIG_PATH = CONF_DIR / "dvpn.conf"
INTERFACE = "dvpn0"
WG_PORT = 51820
DISCOVERY_PORT = 10000


def ensure_dirs() -> None:
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger() -> logging.Logger:
    ensure_dirs()
    log_path = LOG_DIR / "dvpn.log"
    logger = logging.getLogger("dvpn")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = setup_logger()


class WireGuardManager:
    def __init__(self):
        self.private_key = ""
        self.public_key = ""
        self.current_peer: Optional[Peer] = None

    def _run(self, command, input_text=None):
        try:
            res = subprocess.run(
                command,
                input=input_text.encode("utf-8") if input_text else None,
                capture_output=True,
                check=True,
                text=True,
            )
            return res.stdout.strip()
        except subprocess.CalledProcessError as exc:
            logger.error("Command failed: %s %s", command, exc.stderr)
            raise

    def generate_keys(self) -> None:
        logger.info("Generating WireGuard key pair")
        self.private_key = self._run(["wg", "genkey"])
        self.public_key = self._run(["wg", "pubkey"], input_text=self.private_key)
        logger.info("Keys generated. Public key: %s", self.public_key)

    def write_config(self, peer: Peer) -> None:
        logger.info("Writing WireGuard config for peer %s", peer.node_id)
        config = [
            "[Interface]",
            f"PrivateKey = {self.private_key}",
            f"Address = {ADDRESS}",
            "ListenPort = 51820",
            "SaveConfig = false",
            "# Kill switch is managed separately via iptables",
            "",
            "[Peer]",
            f"PublicKey = {peer.public_key}",
            f"Endpoint = {peer.endpoint}",
            "AllowedIPs = 0.0.0.0/0",
            "PersistentKeepalive = 25",
        ]
        WG_CONFIG_PATH.write_text("\n".join(config), encoding="utf-8")
        logger.info("WireGuard config written to %s", WG_CONFIG_PATH)

    def start_interface(self, peer: Peer) -> None:
        self.current_peer = peer
        self.write_config(peer)
        self._run(["wg-quick", "down", str(WG_CONFIG_PATH)])
        self._run(["wg-quick", "up", str(WG_CONFIG_PATH)])
        logger.info("WireGuard interface %s started", INTERFACE)

    def stop_interface(self) -> None:
        try:
            self._run(["wg-quick", "down", str(WG_CONFIG_PATH)])
            logger.info("WireGuard interface %s stopped", INTERFACE)
        except Exception:
            logger.warning("WireGuard interface %s may not be running", INTERFACE)
        self.clear_kill_switch()
        self.current_peer = None

    def disable_ipv6(self) -> None:
        logger.info("Disabling IPv6 for system and interface")
        for path, value in [
            ("/proc/sys/net/ipv6/conf/all/disable_ipv6", "1"),
            ("/proc/sys/net/ipv6/conf/default/disable_ipv6", "1"),
            (f"/proc/sys/net/ipv6/conf/{INTERFACE}/disable_ipv6", "1"),
        ]:
            try:
                with open(path, "w") as handle:
                    handle.write(value)
                logger.debug("Wrote %s=%s", path, value)
            except FileNotFoundError:
                logger.warning("IPv6 sysctl %s not found", path)
            except PermissionError:
                logger.error("Permission denied when disabling IPv6 at %s", path)
                raise

    def apply_kill_switch(self, peer: Peer) -> None:
        logger.info("Applying kill switch for peer %s", peer.node_id)
        commands = [
            ["iptables", "-N", "DVPN"],
            ["iptables", "-F", "DVPN"],
            ["iptables", "-I", "OUTPUT", "-j", "DVPN"],
            ["iptables", "-A", "DVPN", "-o", "lo", "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-o", INTERFACE, "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-p", "udp", "--dport", str(WG_PORT), "-d", peer.endpoint.split(":")[0], "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-j", "DROP"],
        ]
        for cmd in commands:
            try:
                self._run(cmd)
                logger.debug("Ran kill switch command: %s", cmd)
            except Exception:
                logger.warning("Failed run kill-switch command: %s", cmd)
        logger.info("Kill switch enabled")

    def clear_kill_switch(self) -> None:
        logger.info("Clearing kill switch rules")
        commands = [
            ["iptables", "-D", "OUTPUT", "-j", "DVPN"],
            ["iptables", "-F", "DVPN"],
            ["iptables", "-X", "DVPN"],
        ]
        for cmd in commands:
            try:
                self._run(cmd)
                logger.debug("Ran clear kill-switch command: %s", cmd)
            except Exception:
                logger.debug("Could not clear kill-switch command: %s", cmd)
        logger.info("Kill switch cleared")


class PeerDiscovery(threading.Thread):
    def __init__(self, own_id: str, own_public_key: str, service_port: int):
        super().__init__(daemon=True)
        self.own_id = own_id
        self.own_public_key = own_public_key
        self.service_port = service_port
        self.peers: Dict[str, Peer] = {}
        self.socket = None
        self.running = False

    def _build_message(self) -> str:
        payload = {
            "node_id": self.own_id,
            "public_key": self.own_public_key,
            "endpoint": f"{self._local_address()}:{self.service_port}",
        }
        return json.dumps(payload)

    def _local_address(self) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            except Exception:
                return "127.0.0.1"

    def run(self) -> None:
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("", DISCOVERY_PORT))
        mreq = socket.inet_aton(DISCOVERY_GROUP) + socket.inet_aton("0.0.0.0")
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.socket.settimeout(1.0)

        logger.info("Peer discovery started on %s:%d", DISCOVERY_GROUP, DISCOVERY_PORT)

        while self.running:
            try:
                self.socket.sendto(self._build_message().encode("utf-8"), (DISCOVERY_GROUP, DISCOVERY_PORT))
            except Exception as exc:
                logger.warning("Broadcast failed: %s", exc)

            try:
                data, addr = self.socket.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                logger.warning("Discovery receive error: %s", exc)
                continue

            try:
                payload = json.loads(data.decode("utf-8"))
                node_id = payload.get("node_id")
                if node_id == self.own_id:
                    continue
                peer = Peer(
                    node_id=node_id,
                    public_key=payload.get("public_key", ""),
                    endpoint=payload.get("endpoint", ""),
                )
                peer.last_seen = time.time()
                self.peers[peer.node_id] = peer
                logger.debug("Discovered peer %s at %s", peer.node_id, peer.endpoint)
            except Exception as exc:
                logger.warning("Invalid discovery packet from %s: %s", addr, exc)

    def stop(self) -> None:
        self.running = False
        if self.socket:
            self.socket.close()

    def get_best_peer(self) -> Optional[Peer]:
        now = time.time()
        fresh_peers = [p for p in self.peers.values() if now - p.last_seen < 180]
        if not fresh_peers:
            return None
        return sorted(fresh_peers, key=lambda p: p.last_seen)[0]


class DVPNService:
    def __init__(self):
        self.node_id = str(uuid.uuid4())
        self.wg = WireGuardManager()
        self.discovery: Optional[PeerDiscovery] = None
        self.rotation_timer: Optional[threading.Timer] = None
        self.running = False

    def start(self) -> None:
        logger.info("Starting DVPN service")
        self.wg.generate_keys()
        self.wg.disable_ipv6()
        self.discovery = PeerDiscovery(self.node_id, self.wg.public_key, WG_PORT)
        self.discovery.start()
        self.running = True
        self._schedule_rotation()

    def stop(self) -> None:
        logger.info("Stopping DVPN service")
        self.running = False
        if self.rotation_timer:
            self.rotation_timer.cancel()
        if self.discovery:
            self.discovery.stop()
        self.wg.stop_interface()

    def _schedule_rotation(self) -> None:
        if not self.running:
            return
        logger.info("Scheduling peer rotation")
        self.rotation_timer = threading.Timer(120.0, self._rotate_peer)
        self.rotation_timer.start()
        self._rotate_peer()

    def _rotate_peer(self) -> None:
        if not self.running or not self.discovery:
            return
        peer = self.discovery.get_best_peer()
        if peer is None:
            logger.info("No peer available yet; waiting")
            self._schedule_rotation()
            return
        if self.wg.current_peer and peer.node_id == self.wg.current_peer.node_id:
            logger.info("Same peer still available; keeping current connection")
            self._schedule_rotation()
            return

        logger.info("Rotating to peer %s", peer.node_id)
        try:
            self.wg.apply_kill_switch(peer)
            self.wg.start_interface(peer)
        except Exception as exc:
            logger.error("Failed to rotate to peer %s: %s", peer.node_id, exc)
        self._schedule_rotation()
