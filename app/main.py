import os
import random
import shutil
import subprocess
import threading
import time
from collections import deque
from ipaddress import ip_address
from pathlib import Path

from app.audit import audit_log
from app.bandwidth import BandwidthAllocator, measure_throughput_mbps
from app.control import ControlServer
from app.fallback import FallbackProvisioner
from app.metrics import Metrics
from app.network import auto_network_config, derive_wg_public_key
from app.payment import PaymentVerifier
from app.pool import PoolClient, Provider, fastest_provider, mesh_cycle
from app.security import SecureTokenStore
from app.startup import StartupManager
from app.tray import run_tray


class RotationRequested(Exception):
    pass


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def write_wg_config(provider: Provider, wg_config_path: Path) -> None:
    private_key = env("WG_PRIVATE_KEY")
    address = (provider.client_ip or "").strip() or env("WG_ADDRESS")
    dns = os.getenv("WG_DNS", "1.1.1.1").strip()
    listen_port = env("NODE_PORT", "51820")
    keepalive = env("WG_PERSISTENT_KEEPALIVE", "25")
    interface_lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {address}",
        f"ListenPort = {listen_port}",
    ]
    if dns:
        interface_lines.append(f"DNS = {dns}")

    peer_lines = [
        "[Peer]",
        f"PublicKey = {provider.public_key}",
        f"AllowedIPs = {provider.allowed_ips}",
        f"Endpoint = {provider.endpoint}",
        f"PersistentKeepalive = {keepalive}",
    ]
    cfg = "\n".join(interface_lines + [""] + peer_lines) + "\n"
    wg_config_path.parent.mkdir(parents=True, exist_ok=True)
    wg_config_path.write_text(cfg)
    wg_config_path.chmod(0o600)


def write_wg_server_config(wg_config_path: Path) -> None:
    private_key = env("WG_PRIVATE_KEY")
    address = env("WG_PROVIDER_ADDRESS", "10.66.0.1/24")
    listen_port = env("NODE_PORT", "51820")
    dns = os.getenv("WG_DNS", "").strip()
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {address}",
        f"ListenPort = {listen_port}",
    ]
    if dns:
        lines.append(f"DNS = {dns}")
    cfg = "\n".join(lines) + "\n"
    wg_config_path.parent.mkdir(parents=True, exist_ok=True)
    wg_config_path.write_text(cfg)
    wg_config_path.chmod(0o600)


def render_danted_config(danted_template_path: Path, danted_config_path: Path) -> None:
    port = env("SOCKS_PORT", "1080")
    content = danted_template_path.read_text().replace("${SOCKS_PORT}", port)
    danted_config_path.parent.mkdir(parents=True, exist_ok=True)
    danted_config_path.write_text(content)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def endpoint_host(endpoint: str) -> str:
    if endpoint.startswith("["):
        host, remainder = endpoint.split("]", 1)
        if not remainder.startswith(":"):
            raise ValueError("Invalid endpoint format")
        return host[1:]
    host, _ = endpoint.rsplit(":", 1)
    return host


def ensure_wg_private_key() -> None:
    key = os.getenv("WG_PRIVATE_KEY", "")
    valid = False
    if key:
        try:
            subprocess.run(
                ["wg", "pubkey"],
                input=key,
                text=True,
                capture_output=True,
                check=True,
                timeout=3,
            )
            valid = True
        except Exception:
            valid = False
    if valid:
        return
    generated = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True, timeout=3).stdout.strip()
    if not generated:
        raise RuntimeError("Unable to generate WireGuard private key")
    os.environ["WG_PRIVATE_KEY"] = generated


class DVPNService:
    def __init__(self) -> None:
        self.wg_enabled = env("ENABLE_WIREGUARD", "true").lower() == "true"
        self.socks_enabled = env("ENABLE_SOCKS", "true").lower() == "true"
        self.wg_quick_cmd = env("WG_QUICK_CMD", "wg-quick")
        self.danted_cmd = env("DANTED_CMD", "danted")
        self.wg_config_path = Path(env("WG_CONFIG_PATH", "/tmp/dvpn/wg0.conf"))
        self.danted_template_path = Path(env("DANTED_TEMPLATE_PATH", "scripts/danted.conf.template"))
        self.danted_config_path = Path(env("DANTED_CONFIG_PATH", "/tmp/dvpn/danted.conf"))

        self.user_id = env("USER_ID", "local-user")
        passphrase = env("TOKEN_STORE_PASSPHRASE", env("PAYMENT_TOKEN", "local-dev-token"))
        self.token_store = SecureTokenStore(Path(env("TOKEN_STORE_PATH", "/tmp/dvpn/token.store")), passphrase)
        loaded = self.token_store.load_token() or env("PAYMENT_TOKEN", "")
        self.pool = PoolClient(
            env("POOL_URL"),
            timeout=int(env("CONNECT_TIMEOUT_SECONDS", "5")),
            pool_token=loaded,
        )
        self.pay = PaymentVerifier(env("PAYMENT_API_URL"), loaded, timeout=int(env("CONNECT_TIMEOUT_SECONDS", "5")))

        self.fallback = FallbackProvisioner(
            enabled=env("FALLBACK_ENABLED", "false").lower() == "true",
            script_path=Path(env("FALLBACK_SCRIPT_PATH", "scripts/setup_fallback_node.sh")),
            orchestrator_url=env("FALLBACK_ORCHESTRATOR_URL", "https://orchestrator.example.com"),
            timeout=int(env("FALLBACK_TIMEOUT_SECONDS", "30")),
        )
        self.mesh_sample_size = int(env("MESH_SAMPLE_SIZE", "3"))
        self.auto_network_enabled = env("AUTO_NETWORK_CONFIG", "true").lower() == "true"
        self.upnp_enabled = env("UPNP_ENABLED", "true").lower() == "true"
        self.node_register_enabled = env("NODE_REGISTER_ENABLED", "true").lower() == "true"
        self.node_port = int(env("NODE_PORT", "51820"))
        self.node_id = env("NODE_ID", f"node-{self.user_id}")
        self.node_public_endpoint = env("NODE_PUBLIC_ENDPOINT", "")
        self.node_registered = False
        self.killswitch_enabled = False
        self.startup = StartupManager("DVPN")
        self.bandwidth_test_url = env("BANDWIDTH_TEST_URL", "https://speed.cloudflare.com/__down?bytes=25000000")
        self.bandwidth_sample_seconds = int(env("BANDWIDTH_SAMPLE_SECONDS", "4"))
        self.bandwidth_total_mbps = float(env("BANDWIDTH_TOTAL_MBPS", "0"))
        if self.bandwidth_total_mbps <= 0:
            try:
                self.bandwidth_total_mbps = measure_throughput_mbps(
                    self.bandwidth_test_url,
                    timeout=int(env("CONNECT_TIMEOUT_SECONDS", "5")),
                    sample_seconds=self.bandwidth_sample_seconds,
                )
            except Exception:
                self.bandwidth_total_mbps = 100.0
        self.bandwidth = BandwidthAllocator(self.bandwidth_total_mbps, fraction_per_connection=0.5)
        self.metrics = Metrics()
        self.metrics.set_gauge("dvpn_bandwidth_total_mbps", self.bandwidth_total_mbps)
        self.retry_seconds = int(env("RETRY_SECONDS", "15"))
        self.endpoint_rotate_seconds = int(env("ENDPOINT_ROTATE_SECONDS", "240"))
        self.endpoint_rotate_jitter_seconds = int(env("ENDPOINT_ROTATE_JITTER_SECONDS", "45"))
        self.rotation_rng = random.SystemRandom()
        self.log_stdout = env("LOG_STDOUT", "false").lower() == "true"
        self.running = True
        self.desired_connected = True
        self.last_provider_id: str | None = None
        self.current_pool_event: str = "uninitialized"
        self.current_connection_event: str = "disconnected"
        self.current_phase: str = "idle"
        # In-memory only, bounded. This is used for debugging via /logs without persisting anything.
        self.recent_logs: deque[str] = deque(maxlen=200)
        self.socks_proc: subprocess.Popen | None = None
        self.last_detected_public_ip: str | None = None
        self.last_detected_local_ip: str | None = None
        self.provider_forward_disable_cmd = env("PROVIDER_FORWARD_DISABLE_CMD", "").strip()
        self.provider_forward_enable_cmd = env(
            "PROVIDER_FORWARD_ENABLE_CMD",
            f"{Path(__file__).resolve().parent.parent}/scripts/provider_enable_forwarding.sh",
        ).strip()
        self.pool_pruned_on_startup = False
        self.provider_server_ready = False
        self.provider_forwarding_applied = False
        self.handled_claim_nonces: set[str] = set()

    def log(self, message: str) -> None:
        line = f"[dvpn] {message}"
        self.recent_logs.append(line)
        if self.log_stdout:
            print(line, flush=True)
        audit_log("service_log", message=message)

    def log_pool(self, message: str) -> None:
        self.current_pool_event = message
        self.log(f"pool: {message}")

    def log_connection(self, message: str) -> None:
        self.current_connection_event = message
        self.log(f"connection: {message}")

    def set_phase(self, phase: str) -> None:
        self.current_phase = phase
        self.log_connection(f"phase={phase}")

    def restore_provider_forwarding(self) -> None:
        if not self.provider_forward_disable_cmd or not self.provider_forwarding_applied:
            return
        try:
            subprocess.run(self.provider_forward_disable_cmd, shell=True, check=True)
            self.log_connection("provider forwarding restored")
        except Exception as err:
            self.log_connection(f"provider forwarding restore failed: {err}")
        finally:
            self.provider_forwarding_applied = False

    def ensure_provider_forwarding(self) -> None:
        if not self.provider_forward_enable_cmd or self.provider_forwarding_applied:
            return
        try:
            subprocess.run(self.provider_forward_enable_cmd, shell=True, check=True)
            self.provider_forwarding_applied = True
            self.log_connection("provider forwarding enabled")
        except Exception as err:
            self.log_connection(f"provider forwarding enable failed: {err}")

    def next_rotation_deadline(self) -> float:
        jitter = self.rotation_rng.randint(0, max(0, self.endpoint_rotate_jitter_seconds))
        return time.time() + max(30, self.endpoint_rotate_seconds + jitter)

    def maybe_prune_pool_on_startup(self) -> None:
        if self.pool_pruned_on_startup:
            return
        try:
            result = self.pool.prune_dead_endpoints()
            removed = int(result.get("removed", 0))
            remaining = int(result.get("remaining", 0))
            self.log_pool(f"startup prune complete: removed={removed} remaining={remaining}")
        except Exception as err:
            self.log_pool(f"startup prune skipped: {err}")
        finally:
            self.pool_pruned_on_startup = True

    def ensure_provider_server_up(self) -> None:
        if not self.wg_enabled:
            return
        if self.provider_server_ready:
            return
        write_wg_server_config(self.wg_config_path)
        self.wg_down()
        self.wg_up()
        self.provider_server_ready = True
        self.log_connection("provider wireguard server ready")

    def apply_provider_claim(self, claim: dict) -> None:
        lease_nonce = str(claim.get("lease_nonce", "")).strip()
        client_ip = str(claim.get("client_ip", "")).strip()
        client_pub = str(claim.get("client_public_key", "")).strip()
        if not lease_nonce or not client_ip or not client_pub:
            return
        if lease_nonce in self.handled_claim_nonces:
            return
        if shutil.which("wg") is None:
            self.log_connection("provider claim skipped: missing wg command")
            return
        run(["wg", "set", "wg0", "peer", client_pub, "allowed-ips", client_ip, "persistent-keepalive", "25"])
        self.handled_claim_nonces.add(lease_nonce)
        self.log_connection(f"provider peer added {client_ip}")

    def poll_provider_claim_once(self) -> None:
        try:
            claim = self.pool.fetch_next_claim(self.node_id)
        except Exception as err:
            self.log_pool(f"provider claim fetch failed: {err}")
            return
        if claim:
            self.apply_provider_claim(claim)

    def subscription_active(self) -> bool:
        self.pool.set_token(self.pay.token)
        return self.pay.is_active("pool-access")

    def wg_down(self) -> None:
        if not self.wg_enabled:
            return
        if not self.wg_config_path.exists():
            # First run / disconnected state: nothing to tear down yet.
            return
        if shutil.which(self.wg_quick_cmd) is None:
            self.log(f"wireguard disabled: missing command {self.wg_quick_cmd}")
            self.wg_enabled = False
            return
        try:
            run([self.wg_quick_cmd, "down", str(self.wg_config_path)])
        except subprocess.CalledProcessError:
            pass
        self.provider_server_ready = False

    def wg_up(self) -> None:
        if not self.wg_enabled:
            return
        if shutil.which(self.wg_quick_cmd) is None:
            self.log(f"wireguard disabled: missing command {self.wg_quick_cmd}")
            self.wg_enabled = False
            return
        run([self.wg_quick_cmd, "up", str(self.wg_config_path)])

    def start_socks(self) -> None:
        if not self.socks_enabled:
            return
        if shutil.which(self.danted_cmd) is None:
            self.log(f"socks disabled: missing command {self.danted_cmd}")
            self.socks_enabled = False
            return
        if self.socks_proc and self.socks_proc.poll() is None:
            return
        render_danted_config(self.danted_template_path, self.danted_config_path)
        self.socks_proc = subprocess.Popen([self.danted_cmd, "-f", str(self.danted_config_path), "-D"])

    def stop_socks(self) -> None:
        if self.socks_proc and self.socks_proc.poll() is None:
            self.socks_proc.terminate()

    def start(self) -> dict:
        if self.killswitch_enabled:
            self.log("start blocked: killswitch enabled")
            return {"ok": False, "killswitch_enabled": True}
        self.desired_connected = True
        self.log("requested start")
        return {"ok": True}

    def stop(self) -> dict:
        self.desired_connected = False
        if self.last_provider_id:
            self.bandwidth.close_connection(self.last_provider_id)
            self.metrics.set_gauge("dvpn_active_connections", self.bandwidth.active_count)
        self.wg_down()
        self.stop_socks()
        self.restore_provider_forwarding()
        self.set_phase("stopped")
        self.log_connection("stopped")
        return {"ok": True}

    def payment_flow(self) -> dict:
        session = self.pay.begin_checkout(user_id=self.user_id)
        return {"ok": True, "checkout": session}

    def restart(self) -> dict:
        if self.killswitch_enabled:
            return {"ok": False, "killswitch_enabled": True}
        self.log_connection("restarting")
        self.wg_down()
        self.stop_socks()
        self.set_phase("restarting")
        self.last_provider_id = None
        self.desired_connected = True
        return {"ok": True}

    def toggle_killswitch(self) -> dict:
        self.killswitch_enabled = not self.killswitch_enabled
        if self.killswitch_enabled:
            self.desired_connected = False
            self.wg_down()
            self.stop_socks()
            self.restore_provider_forwarding()
        self.log_connection(f"killswitch={self.killswitch_enabled}")
        return {"ok": True, "killswitch_enabled": self.killswitch_enabled}

    def toggle_start_on_boot(self) -> dict:
        desired = not self.startup.is_enabled()
        self.startup.set_enabled(desired)
        current = self.startup.is_enabled()
        return {"ok": True, "start_on_boot": current}

    def exit(self) -> dict:
        self.running = False
        self.stop()
        self.log_connection("exit")
        return {"ok": True}

    def get_logs(self) -> dict:
        return {
            "ok": True,
            "logs": list(self.recent_logs)[-80:],
        }

    def metrics_text(self) -> str:
        return self.metrics.render_prometheus()

    def status(self) -> dict:
        return {
            "ok": True,
            "desired_connected": self.desired_connected,
            "killswitch_enabled": self.killswitch_enabled,
            "start_on_boot": self.startup.is_enabled(),
            "pool": self.current_pool_event,
            "connection": self.current_connection_event,
            "phase": self.current_phase,
        }

    def verify_handshake(self, provider: Provider, timeout_seconds: int = 20) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    ["wg", "show", "wg0", "latest-handshakes"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=3,
                )
                for line in proc.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) != 2:
                        continue
                    pub, ts = parts
                    if pub == provider.public_key and ts.isdigit() and int(ts) > 0:
                        return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def maybe_register_node(self) -> None:
        if self.node_registered or not self.node_register_enabled:
            return
        private_key = env("WG_PRIVATE_KEY", "")
        public_key = derive_wg_public_key(private_key) if private_key else None
        if not public_key:
            self.log_pool("node registration skipped: unable to derive WireGuard public key")
            return

        endpoint = self.node_public_endpoint
        local_ip = None
        public_ip = None
        upnp_mapped = False
        if self.auto_network_enabled:
            net = auto_network_config(self.upnp_enabled, self.node_port)
            local_ip = net.local_ip
            public_ip = net.public_ip
            self.last_detected_local_ip = local_ip
            self.last_detected_public_ip = public_ip
            upnp_mapped = net.upnp_mapped
            if net.cgnat_suspected:
                self.log_pool("network warning: cgnat suspected; direct inbound may fail")
            if self.upnp_enabled and not upnp_mapped:
                self.log_pool("network warning: upnp mapping unavailable")
            if not endpoint and public_ip:
                # If public_ip is IPv6, wrap in brackets for host:port formatting.
                endpoint = f"[{public_ip}]:{self.node_port}" if ":" in public_ip else f"{public_ip}:{self.node_port}"

        if not endpoint:
            self.log_pool("node registration skipped: no public endpoint detected")
            return

        try:
            self.pool.register_node(
                node_id=self.node_id,
                endpoint=endpoint,
                public_key=public_key,
                allowed_ips="0.0.0.0/0,::/0",
                metadata={
                    "user_id": self.user_id,
                    "auto_network_config": self.auto_network_enabled,
                    "upnp_mapped": upnp_mapped,
                    "cgnat_suspected": getattr(net, "cgnat_suspected", False) if self.auto_network_enabled else False,
                    "local_ip": local_ip,
                    "public_ip": public_ip,
                },
            )
            self.node_registered = True
            self.metrics.inc("dvpn_node_register_success_total")
            self.log_pool(f"registered local node as {self.node_id} ({endpoint})")
        except Exception as err:
            self.metrics.inc("dvpn_node_register_failure_total")
            self.log_pool(f"node registration failed: {err}")

    def choose_pool_provider(self) -> Provider:
        providers = self.pool.fetch_providers()
        providers = [p for p in providers if p.id != self.node_id]
        if self.auto_network_enabled and (not self.last_detected_public_ip and not self.last_detected_local_ip):
            net = auto_network_config(self.upnp_enabled, self.node_port)
            self.last_detected_local_ip = net.local_ip
            self.last_detected_public_ip = net.public_ip
        rejected: list[str] = []
        safe: list[Provider] = []
        my_public_ip = self.last_detected_public_ip
        my_local_ip = self.last_detected_local_ip
        for provider in providers:
            try:
                host = endpoint_host(provider.endpoint)
                if my_public_ip and host == my_public_ip:
                    rejected.append(f"{provider.id}:same_public_ip")
                    continue
                if my_local_ip and host == my_local_ip:
                    rejected.append(f"{provider.id}:same_local_ip")
                    continue
                parsed = ip_address(host)
                if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
                    rejected.append(f"{provider.id}:non_public_ip")
                    continue
            except ValueError:
                # Hostname or public IP: allow unless explicitly same as local/public.
                pass
            safe.append(provider)
        providers = safe
        if rejected:
            self.log_pool(f"rejected unsafe providers: {','.join(rejected)}")
        if not providers:
            raise RuntimeError("No non-self providers available in pool")
        ordered = mesh_cycle(providers, previous_provider_id=self.last_provider_id)
        sample_size = min(max(self.mesh_sample_size, 1), len(ordered))
        sampled = ordered[:sample_size]
        return fastest_provider(sampled)

    def loop(self) -> None:
        while self.running:
            if not self.desired_connected:
                time.sleep(1)
                continue
            if self.killswitch_enabled:
                time.sleep(1)
                continue
            try:
                if not self.subscription_active():
                    self.metrics.inc("dvpn_payment_failure_total")
                    self.log_pool("payment inactive: pool access blocked")
                    if self.last_provider_id:
                        self.bandwidth.close_connection(self.last_provider_id)
                        self.metrics.set_gauge("dvpn_active_connections", self.bandwidth.active_count)
                        self.last_provider_id = None
                    self.wg_down()
                    self.stop_socks()
                    self.restore_provider_forwarding()
                    self.set_phase("payment_blocked")
                    time.sleep(self.retry_seconds)
                    continue

                self.maybe_register_node()
                self.maybe_prune_pool_on_startup()
                self.start_socks()
                self.set_phase("control_plane")
                source = "pool"
                try:
                    chosen = self.choose_pool_provider()
                except Exception as pool_err:
                    if "No non-self providers available in pool" in str(pool_err):
                        self.ensure_provider_forwarding()
                        self.ensure_provider_server_up()
                        self.poll_provider_claim_once()
                        self.log_pool("no non-self providers available; provider standby")
                        self.set_phase("provider_standby")
                        time.sleep(3)
                        continue
                    self.metrics.inc("dvpn_fallback_attempt_total")
                    self.log_pool(f"pool connect failed: {pool_err}; trying fallback")
                    chosen = self.fallback.provision(self.pay.token, self.user_id)
                    source = "fallback"

                if not self.pay.is_active(chosen.id):
                    self.metrics.inc("dvpn_payment_failure_total")
                    raise RuntimeError(f"Payment inactive for provider {chosen.id}")

                if source == "pool":
                    self.pool.mark_approved(chosen, self.pay.token)
                self.token_store.save_token(self.pay.token)

                self.last_provider_id = chosen.id
                granted_mbps = self.bandwidth.open_connection(chosen.id)
                self.metrics.set_gauge("dvpn_last_granted_mbps", granted_mbps)
                self.metrics.set_gauge("dvpn_active_connections", self.bandwidth.active_count)
                self.log_pool(f"using provider {chosen.id} ({source})")
                self.log_connection(f"provider selected {chosen.id}; grant={granted_mbps:.2f}Mbps")
                if self.wg_enabled:
                    write_wg_config(chosen, self.wg_config_path)
                    self.wg_down()
                    self.wg_up()
                    self.set_phase("tunnel_up")
                    if not self.verify_handshake(chosen):
                        raise RuntimeError(f"wireguard handshake not confirmed for {chosen.id}")
                    self.set_phase("handshake_confirmed")
                    self.set_phase("traffic_verified")
                else:
                    self.log_connection("wireguard skipped (ENABLE_WIREGUARD=false)")
                    self.set_phase("control_plane_only")
                self.metrics.inc("dvpn_connect_success_total")
                rotate_at = self.next_rotation_deadline()

                while self.running and self.desired_connected:
                    if self.socks_proc and self.socks_proc.poll() is not None:
                        raise RuntimeError("SOCKS server stopped unexpectedly")
                    if time.time() >= rotate_at:
                        raise RotationRequested("endpoint rotation interval reached")
                    time.sleep(10)
            except RotationRequested as rotation:
                self.log_connection(str(rotation))
                self.set_phase("rotating")
                if self.last_provider_id:
                    self.bandwidth.close_connection(self.last_provider_id)
                    self.metrics.set_gauge("dvpn_active_connections", self.bandwidth.active_count)
                    self.last_provider_id = None
                self.wg_down()
                continue
            except Exception as err:
                self.metrics.inc("dvpn_connect_failure_total")
                self.log_connection(f"reconnect loop: {err}")
                self.set_phase("error")
                if self.last_provider_id:
                    self.bandwidth.close_connection(self.last_provider_id)
                    self.metrics.set_gauge("dvpn_active_connections", self.bandwidth.active_count)
                    self.last_provider_id = None
                self.wg_down()
                time.sleep(self.retry_seconds)


def main() -> None:
    ensure_wg_private_key()
    service = DVPNService()
    control_host = env("CONTROL_HOST", "127.0.0.1")
    control_port = int(env("CONTROL_PORT", "8765"))
    payment_portal_url = env("PAYMENT_PORTAL_URL", "https://payments.example.com/portal")

    control = ControlServer(
        control_host,
        control_port,
        {
            "start": service.start,
            "stop": service.stop,
            "restart": service.restart,
            "logs": service.get_logs,
            "payments": service.payment_flow,
            "killswitch": service.toggle_killswitch,
            "start_on_boot": service.toggle_start_on_boot,
            "exit": service.exit,
        },
        metrics_fn=service.metrics_text,
        status_fn=service.status,
    )
    control.start()

    tray_enabled = env("ENABLE_TRAY", "false").lower() == "true"
    try:
        if tray_enabled:
            worker = threading.Thread(target=service.loop, daemon=True)
            worker.start()
            run_tray(f"http://{control_host}:{control_port}", payment_portal_url)
            service.exit()
            worker.join(timeout=5)
        else:
            service.loop()
    finally:
        control.stop()
        service.stop()


if __name__ == "__main__":
    main()
