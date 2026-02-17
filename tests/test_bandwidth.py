import unittest

from app.bandwidth import BandwidthAllocator


class TestBandwidthAllocator(unittest.TestCase):
    def test_half_total_granted_for_first_connection(self):
        allocator = BandwidthAllocator(total_mbps=200.0, fraction_per_connection=0.5)
        granted = allocator.open_connection("conn-1")
        self.assertAlmostEqual(granted, 100.0)

    def test_each_new_connection_gets_half_total_until_remaining_exhausted(self):
        allocator = BandwidthAllocator(total_mbps=100.0, fraction_per_connection=0.5)
        grant1 = allocator.open_connection("a")
        grant2 = allocator.open_connection("b")
        grant3 = allocator.open_connection("c")
        self.assertAlmostEqual(grant1, 50.0)
        self.assertAlmostEqual(grant2, 50.0)
        self.assertAlmostEqual(grant3, 0.0)

    def test_release_restores_capacity(self):
        allocator = BandwidthAllocator(total_mbps=100.0, fraction_per_connection=0.5)
        allocator.open_connection("a")
        allocator.open_connection("b")
        allocator.close_connection("a")
        grant = allocator.open_connection("c")
        self.assertAlmostEqual(grant, 50.0)


if __name__ == "__main__":
    unittest.main()
