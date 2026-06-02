import logging
import subprocess
import threading
import time
import uuid
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
    """Create necessary directories."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger() -> logging.Logger:
    """Setup logging to file."""
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
    """Enhanced WireGuard interface manager with stats tracking."""

    def __init__(self):
        self.private_key = ""
        self.public_key = ""
        self.current_peer: Optional[Peer] = None
        self.connection_stats: Dict[str, ConnectionStats] = {}

    def _run(self, command, input_text=None, check=True):
        """Execute system command with error handling."""
        try:
            res = subprocess.run(
                command,
                input=input_text.encode("utf-8") if input_text else None,
                capture_output=True,
                check=check,
                text=True,
                timeout=30,
            )
            return res.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("Command timeout: %s", command)
            raise
        except subprocess.CalledProcessError as exc:
            logger.error("Command failed: %s stderr: %s", command, exc.stderr)
            raise

    def generate_keys(self) -> None:
        """Generate WireGuard key pair."""
        logger.info("Generating WireGuard key pair")
        try:
            self.private_key = self._run(["wg", "genkey"])
            self.public_key = self._run(["wg", "pubkey"], input_text=self.private_key)
            logger.info("Keys generated. Public key: %s", self.public_key[:20] + "...")
        except Exception as exc:
            logger.error("Failed to generate keys: %s", exc)
            raise

    def write_config(self, peer: Peer) -> None:
        """Write WireGuard configuration file."""
        logger.info("Writing WireGuard config for peer %s", peer.node_id[:8])
        config = [
            "[Interface]",
            f"PrivateKey = {self.private_key}",
            "Address = 10.99.99.2/24",
            f"ListenPort = {WG_PORT}",
            "SaveConfig = false",
            "# Kill switch managed via iptables",
            "",
            "[Peer]",
            f"PublicKey = {peer.public_key}",
            f"Endpoint = {peer.endpoint}",
            "AllowedIPs = 0.0.0.0/0",
            "PersistentKeepalive = 25",
        ]
        try:
            WG_CONFIG_PATH.write_text("\n".join(config), encoding="utf-8")
            WG_CONFIG_PATH.chmod(0o600)
            logger.info("WireGuard config written to %s", WG_CONFIG_PATH)
        except Exception as exc:
            logger.error("Failed to write config: %s", exc)
            raise

    def start_interface(self, peer: Peer) -> None:
        """Bring up WireGuard interface with peer."""
        try:
            self.current_peer = peer
            self.write_config(peer)

            # Attempt graceful teardown if already up
            self._run(["wg-quick", "down", str(WG_CONFIG_PATH)], check=False)
            time.sleep(0.5)

            # Bring up new interface
            self._run(["wg-quick", "up", str(WG_CONFIG_PATH)])

            # Initialize stats for this peer
            if peer.node_id not in self.connection_stats:
                self.connection_stats[peer.node_id] = ConnectionStats(peer_id=peer.node_id)
            self.connection_stats[peer.node_id].is_active = True

            logger.info("WireGuard interface %s started with peer %s", INTERFACE, peer.node_id[:8])
        except Exception as exc:
            logger.error("Failed to start WireGuard: %s", exc)
            raise

    def stop_interface(self) -> None:
        """Bring down WireGuard interface."""
        try:
            if self.current_peer:
                stats = self.connection_stats.get(self.current_peer.node_id)
                if stats:
                    stats.is_active = False
                    stats.update_duration()
                    logger.info(
                        "Connection to %s: duration=%.1fs bytes_sent=%d bytes_recv=%d",
                        self.current_peer.node_id[:8],
                        stats.connection_duration,
                        stats.bytes_sent,
                        stats.bytes_received,
                    )

            self._run(["wg-quick", "down", str(WG_CONFIG_PATH)], check=False)
            self.clear_kill_switch()
            self.current_peer = None
            logger.info("WireGuard interface %s stopped", INTERFACE)
        except Exception as exc:
            logger.warning("Error stopping interface: %s", exc)

    def disable_ipv6(self) -> None:
        """Disable IPv6 system-wide and per-interface."""
        logger.info("Disabling IPv6")
        sysctl_paths = [
            ("/proc/sys/net/ipv6/conf/all/disable_ipv6", "1"),
            ("/proc/sys/net/ipv6/conf/default/disable_ipv6", "1"),
            (f"/proc/sys/net/ipv6/conf/{INTERFACE}/disable_ipv6", "1"),
        ]
        for path, value in sysctl_paths:
            try:
                with open(path, "w") as f:
                    f.write(value)
                logger.debug("IPv6 disabled: %s", path)
            except FileNotFoundError:
                logger.debug("IPv6 path not found: %s", path)
            except PermissionError:
                logger.error("Permission denied disabling IPv6: %s", path)
                raise

    def apply_kill_switch(self, peer: Peer) -> None:
        """Apply iptables-based kill switch for the peer."""
        logger.info("Applying kill switch for peer %s", peer.node_id[:8])
        endpoint_ip = peer.endpoint.split(":")[0]

        commands = [
            ["iptables", "-N", "DVPN"],
            ["iptables", "-F", "DVPN"],
            ["iptables", "-I", "OUTPUT", "-j", "DVPN"],
            ["iptables", "-A", "DVPN", "-o", "lo", "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-o", INTERFACE, "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-p", "udp", "--dport", str(WG_PORT), "-d", endpoint_ip, "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
            ["iptables", "-A", "DVPN", "-j", "DROP"],
        ]

        for cmd in commands:
            try:
                self._run(cmd, check=False)
            except Exception as exc:
                logger.warning("Kill switch command failed: %s %s", cmd, exc)

        logger.info("Kill switch enabled")

    def clear_kill_switch(self) -> None:
        """Remove iptables kill switch rules."""
        logger.info("Clearing kill switch rules")
        commands = [
            ["iptables", "-D", "OUTPUT", "-j", "DVPN"],
            ["iptables", "-F", "DVPN"],
            ["iptables", "-X", "DVPN"],
        ]
        for cmd in commands:
            try:
                self._run(cmd, check=False)
            except Exception:
                pass
        logger.info("Kill switch cleared")


class DVPNService:
    """Main DVPN service orchestrator."""

    def __init__(self):
        self.node_id = str(uuid.uuid4())
        self.wg = WireGuardManager()
        self.peer_registry = PeerRegistry()
        self.discovery: Optional[EnhancedPeerDiscovery] = None
        self.rotation_timer: Optional[threading.Timer] = None
        self.running = False
        self.stats_tracker: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the DVPN service."""
        logger.info("Starting DVPN service (node_id=%s)", self.node_id[:8])
        self.wg.generate_keys()
        self.wg.disable_ipv6()
        
        self.discovery = EnhancedPeerDiscovery(
            own_id=self.node_id,
            own_public_key=self.wg.public_key,
            port=WG_PORT,
            registry=self.peer_registry,
        )
        self.discovery.start()
        self.running = True
        self._start_stats_tracker()
        self._schedule_rotation()

    def stop(self) -> None:
        """Stop the DVPN service."""
        logger.info("Stopping DVPN service")
        self.running = False
        if self.rotation_timer:
            self.rotation_timer.cancel()
        if self.discovery:
            self.discovery.stop()
        self.wg.stop_interface()
        logger.info("DVPN service stopped")

    def _schedule_rotation(self) -> None:
        """Schedule peer rotation every 2 minutes."""
        if not self.running:
            return
        self.rotation_timer = threading.Timer(120.0, self._rotate_peer)
        self.rotation_timer.daemon = True
        self.rotation_timer.start()
        self._rotate_peer()

    def _rotate_peer(self) -> None:
        """Select and connect to best available peer."""
        if not self.running or not self.discovery:
            return
        
        peer = self.peer_registry.get_best_peer()
        if peer is None:
            logger.debug("No peer available; waiting")
            self._schedule_rotation()
            return

        # Skip if already connected to same peer
        if self.wg.current_peer and peer.node_id == self.wg.current_peer.node_id:
            logger.debug("Already connected to best peer")
            self._schedule_rotation()
            return

        logger.info(
            "Rotating to peer %s (reliability=%.1f, seen=%d)",
            peer.node_id[:8],
            peer.reliability,
            peer.seen_count,
        )

        try:
            self.wg.apply_kill_switch(peer)
            self.wg.start_interface(peer)
            self.peer_registry.mark_peer_reachable(peer.node_id)
        except Exception as exc:
            logger.error("Failed to rotate to peer %s: %s", peer.node_id[:8], exc)
            self.peer_registry.mark_peer_unreachable(peer.node_id)

        self._schedule_rotation()

    def _start_stats_tracker(self) -> None:
        """Start background thread tracking connection stats."""
        def track_stats():
            while self.running:
                try:
                    if self.wg.current_peer:
                        stats = self.wg.connection_stats.get(self.wg.current_peer.node_id)
                        if stats:
                            stats.update_duration()
                    time.sleep(5)
                except Exception as exc:
                    logger.debug("Stats tracking error: %s", exc)

        self.stats_tracker = threading.Thread(target=track_stats, daemon=True)
        self.stats_tracker.start()

    def get_status(self) -> Dict:
        """Get current service status."""
        peer_count = self.peer_registry.count()
        current_peer_id = self.wg.current_peer.node_id[:8] if self.wg.current_peer else "none"
        
        stats = None
        if self.wg.current_peer:
            stats = self.wg.connection_stats.get(self.wg.current_peer.node_id)
        
        return {
            "running": self.running,
            "node_id": self.node_id[:8],
            "known_peers": peer_count,
            "current_peer": current_peer_id,
            "uptime": stats.connection_duration if stats else 0,
            "kill_switch": self.running,
            "ipv6_disabled": True,
        }
