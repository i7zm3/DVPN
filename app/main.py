import os
import subprocess
import threading
import time
from pathlib import Path

from app.bandwidth import BandwidthAllocator, measure_throughput_mbps
from app.control import ControlServer
from app.fallback import FallbackProvisioner
from app.network import auto_network_config, derive_wg_public_key
from app.payment import PaymentVerifier
from app.pool import PoolClient, Provider, fastest_provider, mesh_cycle
from app.security import SecureTokenStore
from app.tray import run_tray

WG_CONFIG_PATH = Path("/etc/wireguard/wg0.conf")
DANTED_TEMPLATE_PATH = Path("/etc/danted.conf.template")
DANTED_CONFIG_PATH = Path("/tmp/danted.conf")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def write_wg_config(provider: Provider) -> None:
    private_key = env("WG_PRIVATE_KEY")
    address = env("WG_ADDRESS")
    dns = env("WG_DNS", "1.1.1.1")
    keepalive = env("WG_PERSISTENT_KEEPALIVE", "25")

    cfg = f"""[Interface]
PrivateKey = {private_key}
Address = {address}
DNS = {dns}

[Peer]
PublicKey = {provider.public_key}
AllowedIPs = {provider.allowed_ips}
Endpoint = {provider.endpoint}
PersistentKeepalive = {keepalive}
"""
    WG_CONFIG_PATH.write_text(cfg)


def render_danted_config() -> None:
    port = env("SOCKS_PORT", "1080")
    content = DANTED_TEMPLATE_PATH.read_text().replace("${SOCKS_PORT}", port)
    DANTED_CONFIG_PATH.write_text(content)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


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
        self.pool = PoolClient(env("POOL_URL"), timeout=int(env("CONNECT_TIMEOUT_SECONDS", "5")))
        self.user_id = env("USER_ID", "local-user")
        passphrase = env("TOKEN_STORE_PASSPHRASE", env("PAYMENT_TOKEN", "local-dev-token"))
        self.token_store = SecureTokenStore(Path(env("TOKEN_STORE_PATH", "/tmp/dvpn/token.store")), passphrase)
        loaded = self.token_store.load_token() or env("PAYMENT_TOKEN", "")
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
        self.retry_seconds = int(env("RETRY_SECONDS", "15"))
        self.running = True
        self.desired_connected = True
        self.last_provider_id: str | None = None
        self.logs: list[str] = []
        self.socks_proc: subprocess.Popen | None = None

    def log(self, message: str) -> None:
        line = f"[dvpn] {message}"
        self.logs.append(line)
        self.logs = self.logs[-200:]
        print(line, flush=True)

    def wg_down(self) -> None:
        try:
            run(["wg-quick", "down", "wg0"])
        except subprocess.CalledProcessError:
            pass

    def wg_up(self) -> None:
        run(["wg-quick", "up", "wg0"])

    def start_socks(self) -> None:
        if self.socks_proc and self.socks_proc.poll() is None:
            return
        render_danted_config()
        self.socks_proc = subprocess.Popen(["danted", "-f", str(DANTED_CONFIG_PATH), "-D"])

    def stop_socks(self) -> None:
        if self.socks_proc and self.socks_proc.poll() is None:
            self.socks_proc.terminate()

    def start(self) -> dict:
        self.desired_connected = True
        self.log("requested start")
        return {"ok": True}

    def stop(self) -> dict:
        self.desired_connected = False
        if self.last_provider_id:
            self.bandwidth.close_connection(self.last_provider_id)
        self.wg_down()
        self.stop_socks()
        self.log("requested stop")
        return {"ok": True}

    def payment_flow(self) -> dict:
        session = self.pay.begin_checkout(user_id=self.user_id)
        return {"ok": True, "checkout": session}

    def exit(self) -> dict:
        self.running = False
        self.stop()
        self.log("requested exit")
        return {"ok": True}

    def get_logs(self) -> dict:
        return {"ok": True, "logs": self.logs[-50:]}

    def maybe_register_node(self) -> None:
        if self.node_registered or not self.node_register_enabled:
            return
        private_key = env("WG_PRIVATE_KEY", "")
        public_key = derive_wg_public_key(private_key) if private_key else None
        if not public_key:
            self.log("node registration skipped: unable to derive WireGuard public key")
            return

        endpoint = self.node_public_endpoint
        local_ip = None
        public_ip = None
        upnp_mapped = False
        if self.auto_network_enabled:
            net = auto_network_config(self.upnp_enabled, self.node_port)
            local_ip = net.local_ip
            public_ip = net.public_ip
            upnp_mapped = net.upnp_mapped
            if not endpoint and public_ip:
                endpoint = f"{public_ip}:{self.node_port}"

        if not endpoint:
            self.log("node registration skipped: no public endpoint detected")
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
                    "local_ip": local_ip,
                    "public_ip": public_ip,
                },
            )
            self.node_registered = True
            self.log(f"registered local node in pool as {self.node_id} ({endpoint})")
        except Exception as err:
            self.log(f"node registration failed: {err}")

    def choose_pool_provider(self) -> Provider:
        providers = self.pool.fetch_providers()
        ordered = mesh_cycle(providers, previous_provider_id=self.last_provider_id)
        sample_size = min(max(self.mesh_sample_size, 1), len(ordered))
        sampled = ordered[:sample_size]
        return fastest_provider(sampled)

    def loop(self) -> None:
        while self.running:
            if not self.desired_connected:
                time.sleep(1)
                continue
            try:
                self.maybe_register_node()
                self.start_socks()
                source = "pool"
                try:
                    chosen = self.choose_pool_provider()
                except Exception as pool_err:
                    self.log(f"pool connect failed: {pool_err}; trying fallback")
                    chosen = self.fallback.provision(self.pay.token, self.user_id)
                    source = "fallback"

                if not self.pay.is_active(chosen.id):
                    raise RuntimeError(f"Payment inactive for provider {chosen.id}")

                if source == "pool":
                    self.pool.mark_approved(chosen.id, self.pay.token)
                self.token_store.save_token(self.pay.token)

                self.last_provider_id = chosen.id
                granted_mbps = self.bandwidth.open_connection(chosen.id)
                self.log(f"bandwidth grant for {chosen.id}: {granted_mbps:.2f} Mbps")
                write_wg_config(chosen)
                self.wg_down()
                self.wg_up()

                while self.running and self.desired_connected:
                    if self.socks_proc and self.socks_proc.poll() is not None:
                        raise RuntimeError("SOCKS server stopped unexpectedly")
                    time.sleep(10)
            except Exception as err:
                self.log(f"reconnect loop: {err}")
                if self.last_provider_id:
                    self.bandwidth.close_connection(self.last_provider_id)
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
            "logs": service.get_logs,
            "payments": service.payment_flow,
            "exit": service.exit,
        },
    )
    control.start()

    tray_enabled = env("ENABLE_TRAY", "false").lower() == "true"
    if tray_enabled:
        threading.Thread(
            target=run_tray,
            args=(f"http://{control_host}:{control_port}", payment_portal_url),
            daemon=True,
        ).start()

    try:
        service.loop()
    finally:
        control.stop()
        service.stop()


if __name__ == "__main__":
    main()
