import unittest
from praxis.hardware import (GPU, Profile, estimate_tokens_per_s, fits, parse_nvidia_smi, parse_meminfo,
                             profile_from_config, usable_ram_bytes)
from praxis.catalog import CATALOG, Model, recommend

GB = 2**30


def rig(vram_gb, ram_gb=32, bw=224, name="NVIDIA GeForce RTX 3050"):
    gpus = [GPU(name, int(vram_gb * GB), bw)] if vram_gb else []
    return Profile(os="windows", cpu="AMD Ryzen 7 7700", cores=16, ram_bytes=int(ram_gb * GB), ram_bw_gbps=70, gpus=gpus)


class Parsing(unittest.TestCase):
    def test_nvidia_smi_csv(self):
        gpus = parse_nvidia_smi("NVIDIA GeForce RTX 3050, 8192\nNVIDIA GeForce RTX 3050, 6144\n")
        self.assertEqual([g.vram_bytes for g in gpus], [8192 * 2**20, 6144 * 2**20])
        self.assertEqual(gpus[0].name, "NVIDIA GeForce RTX 3050")

    def test_nvidia_smi_garbage_and_empty(self):
        self.assertEqual(parse_nvidia_smi(""), [])
        self.assertEqual(parse_nvidia_smi("No devices were found"), [])

    def test_known_gpu_bandwidth_table(self):
        g8 = parse_nvidia_smi("NVIDIA GeForce RTX 3050, 8192")[0]
        g6 = parse_nvidia_smi("NVIDIA GeForce RTX 3050 6GB, 6144")[0]
        self.assertEqual(g8.bw_gbps, 224)   # 8GB: 128-bit @ 14Gbps-class
        self.assertEqual(g6.bw_gbps, 168)   # 6GB variant is a different, slower card

    def test_meminfo(self):
        self.assertEqual(parse_meminfo("MemTotal:       32768000 kB\nMemAvailable:   20000000 kB\n"), 32768000 * 1024)


class Fit(unittest.TestCase):
    def test_usable_ram_reserves_for_the_os(self):
        self.assertLess(usable_ram_bytes(rig(8)), 32 * GB)
        self.assertGreater(usable_ram_bytes(rig(8)), 20 * GB)

    def test_32gb_rig_fits_25gb_moe_but_not_75gb(self):
        p = rig(8)
        self.assertTrue(fits(25 * GB, p))
        self.assertFalse(fits(75 * GB, p))

    def test_fits_in_vram_only_for_small_models(self):
        self.assertTrue(fits(5.3 * GB, rig(8), vram_only=True))
        self.assertFalse(fits(5.3 * GB, rig(6), vram_only=True))   # 6GB card: KV cache + overhead pushes it out
        self.assertFalse(fits(1 * GB, rig(0), vram_only=True))     # no GPU at all


class Speed(unittest.TestCase):
    """The physical model: tokens/s ~ bandwidth / bytes-read-per-token. Directionally right, labeled an estimate."""

    def test_moe_3b_active_spilled_to_ram_beats_dense_27b_spilled_to_ram(self):
        p = rig(8)
        moe = estimate_tokens_per_s(24 * GB, 35, 3, p)     # qwen3.6:35b-a3b
        dense = estimate_tokens_per_s(17 * GB, 27, 27, p)  # qwen3.6:27b
        self.assertGreater(moe, 2.5 * dense)
        self.assertGreater(moe, 8)         # usable interactively
        self.assertLess(dense, 8)

    def test_fits_entirely_in_vram_is_fastest(self):
        p = rig(8)
        self.assertGreater(estimate_tokens_per_s(5.3 * GB, 8, 8, p), estimate_tokens_per_s(5.3 * GB, 8, 8, rig(0)))

    def test_cpu_only_uses_ram_bandwidth(self):
        self.assertGreater(estimate_tokens_per_s(2.2 * GB, 3, 3, rig(0)), 5)

    def test_slower_vram_card_is_slower(self):
        fast, slow = rig(8, bw=224), rig(6, bw=168)
        self.assertGreater(estimate_tokens_per_s(5.0 * GB, 8, 8, fast), estimate_tokens_per_s(5.0 * GB, 8, 8, slow))


class Recommend(unittest.TestCase):
    def test_every_catalog_entry_has_provenance(self):
        for m in CATALOG:
            self.assertTrue(m.tag and m.size_gb > 0 and m.total_b >= m.active_b > 0 and m.source and m.checked, m.tag)

    def test_3050_8gb_32gb_ddr5_gets_moe_daily_driver_and_in_vram_helper(self):
        r = recommend(rig(8))
        daily = r["daily"]; fast = r["fast"]
        self.assertTrue(daily.model.active_b <= 4 and daily.model.total_b >= 27)      # a ~3B-active MoE
        self.assertGreater(daily.tps, 8)
        self.assertTrue(fast.vram_only and fast.model.size_gb <= 6)
        self.assertNotIn("128b", daily.model.tag)

    def test_6gb_card_still_gets_a_sane_plan(self):
        r = recommend(rig(6, bw=168))
        self.assertGreater(r["daily"].tps, 6)
        self.assertLessEqual(r["fast"].model.size_gb, 3.0)   # smaller helper so it really fits 6GB with KV cache

    def test_no_gpu_cpu_only_plan(self):
        r = recommend(rig(0))
        self.assertIsNotNone(r["daily"])
        self.assertFalse(r["fast"].vram_only if r["fast"] else False)

    def test_tiny_machine_recommends_small_models_only(self):
        p = Profile("linux", "cpu", 4, int(8 * GB), 40, [])
        r = recommend(p)
        self.assertLessEqual(r["daily"].model.size_gb, 5)

    def test_big_workstation_prefers_dense_quality_models(self):
        p = Profile("linux", "cpu", 32, int(128 * GB), 120, [GPU("RTX 4090", 24 * GB, 1008)])
        r = recommend(p)
        self.assertGreater(r["daily"].tps, 15)
        self.assertGreater(r["deep"].model.size_gb, 15)

    def test_pull_commands_use_exact_tags(self):
        r = recommend(rig(8))
        self.assertTrue(all(x.model.tag in x.pull_cmd for x in r.values() if x))


class Overrides(unittest.TestCase):
    def test_config_override_wins_over_detection(self):
        p = profile_from_config({"vram_gb": 8, "ram_gb": 32, "gpu_name": "RTX 3050", "ram_bw_gbps": 70}, detected=rig(0, 16))
        self.assertEqual(p.vram_total, 8 * GB); self.assertEqual(p.ram_bytes, 32 * GB)

    def test_zero_means_use_detected(self):
        det = rig(8)
        p = profile_from_config({"vram_gb": 0, "ram_gb": 0}, detected=det)
        self.assertEqual(p.vram_total, det.vram_total)


if __name__ == "__main__":
    unittest.main()
