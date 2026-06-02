import sys
import time
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dvpn.stats import ConnectionStats
from dvpn.discovery import Peer, PeerRegistry


class TestConnectionStats(unittest.TestCase):
    """Test connection statistics and quality scoring."""

    def test_initial_quality_score(self):
        """New connection should have baseline score."""
        stats = ConnectionStats(peer_id="test_peer")
        score = stats.quality_score()
        self.assertGreaterEqual(score, 30)
        self.assertLessEqual(score, 70)

    def test_low_latency_improves_score(self):
        """Low latency should improve quality score."""
        stats1 = ConnectionStats(peer_id="test_peer", latency_ms=200.0)
        stats2 = ConnectionStats(peer_id="test_peer", latency_ms=5.0)
        self.assertGreater(stats2.quality_score(), stats1.quality_score())

    def test_long_connection_improves_score(self):
        """Longer active connections should score higher."""
        now = time.time()
        stats1 = ConnectionStats(peer_id="test_peer", connected_at=now)
        stats2 = ConnectionStats(peer_id="test_peer", connected_at=now - 400)
        stats2.update_duration()
        self.assertGreater(stats2.quality_score(), stats1.quality_score())

    def test_inactive_connection_decreases_score(self):
        """Inactive connections should score lower."""
        stats_active = ConnectionStats(peer_id="test_peer", is_active=True)
        stats_inactive = ConnectionStats(peer_id="test_peer", is_active=False)
        self.assertGreater(stats_active.quality_score(), stats_inactive.quality_score())

    def test_handshake_tracking(self):
        """Should track handshakes correctly."""
        stats = ConnectionStats(peer_id="test_peer")
        self.assertEqual(stats.handshake_count, 0)
        stats.record_handshake()
        self.assertEqual(stats.handshake_count, 1)
        self.assertGreater(stats.last_handshake, 0)


class TestPeer(unittest.TestCase):
    """Test peer object functionality."""

    def test_peer_freshness(self):
        """Peer should be fresh within timeout."""
        peer = Peer(
            node_id="test",
            public_key="key",
            endpoint="127.0.0.1:51820"
        )
        self.assertTrue(peer.is_fresh(timeout_sec=10.0))

    def test_peer_reliability_decrease(self):
        """Unreachable peer should decrease reliability."""
        peer = Peer(
            node_id="test",
            public_key="key",
            endpoint="127.0.0.1:51820"
        )
        initial_reliability = peer.reliability
        peer.mark_unreachable()
        self.assertLess(peer.reliability, initial_reliability)
        self.assertGreaterEqual(peer.reliability, 0.0)

    def test_peer_reliability_increase(self):
        """Reachable peer should increase reliability."""
        peer = Peer(
            node_id="test",
            public_key="key",
            endpoint="127.0.0.1:51820"
        )
        peer.mark_unreachable()
        reliability_after_unreachable = peer.reliability
        peer.mark_reachable()
        self.assertGreater(peer.reliability, reliability_after_unreachable)


class TestPeerRegistry(unittest.TestCase):
    """Test peer registry management."""

    def setUp(self):
        """Create fresh registry for each test."""
        self.registry = PeerRegistry()

    def test_add_peer(self):
        """Should add new peers."""
        peer = Peer("node1", "key1", "127.0.0.1:51820")
        self.registry.add_or_update(peer)
        self.assertEqual(self.registry.count(), 1)

    def test_update_peer(self):
        """Should update existing peer."""
        peer1 = Peer("node1", "key1", "127.0.0.1:51820")
        self.registry.add_or_update(peer1)
        peer2 = Peer("node1", "key1", "192.168.1.1:51820")
        self.registry.add_or_update(peer2)
        self.assertEqual(self.registry.count(), 1)
        fresh = self.registry.get_fresh_peers()
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0].endpoint, "192.168.1.1:51820")

    def test_get_best_peer(self):
        """Should select best peer by quality metrics."""
        peer1 = Peer("node1", "key1", "127.0.0.1:51820")
        peer2 = Peer("node2", "key2", "127.0.0.2:51820")
        peer2.seen_count = 5
        peer2.reliability = 0.9
        self.registry.add_or_update(peer1)
        self.registry.add_or_update(peer2)
        best = self.registry.get_best_peer()
        self.assertEqual(best.node_id, "node2")

    def test_stale_peer_cleanup(self):
        """Should remove stale peers."""
        peer1 = Peer("node1", "key1", "127.0.0.1:51820")
        peer1.last_seen = time.time() - 400  # Over 5 minutes old
        self.registry.add_or_update(peer1)
        self.assertEqual(self.registry.count(), 1)
        self.registry.clear_stale(timeout_sec=300)
        self.assertEqual(self.registry.count(), 0)

    def test_mark_peer_reachable(self):
        """Should increase reliability on success."""
        peer = Peer("node1", "key1", "127.0.0.1:51820")
        self.registry.add_or_update(peer)
        peer.mark_unreachable()
        reliability_low = peer.reliability
        self.registry.mark_peer_reachable("node1")
        self.assertGreater(peer.reliability, reliability_low)


if __name__ == "__main__":
    unittest.main()
