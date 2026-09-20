"""T0 gate for every registered hook: emit cleanly, with an honest manifest."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from integrations.base import (HOOK_REGISTRY, resolve, sha256_of, TIER_EMITTED,
                               FIDELITY_ORDER, PROVENANCE_FIELDS)
from integrations.canonical import load_design
from integrations import vendors  # noqa: F401  registers hooks

TEXT_SUFFIXES = {".def", ".lef", ".spef", ".lib", ".s4p", ".sp", ".tcl", ".json",
                 ".csv", ".ibs", ".ami", ".rule", ".cmd", ".sh", ".txt", ".py"}


class TestHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()
        cls._tmp = tempfile.TemporaryDirectory(prefix="3dicx-hooks-")
        cls.root = Path(cls._tmp.name)
        cls.results = {}
        for key in sorted(HOOK_REGISTRY):
            hook = HOOK_REGISTRY[key]()
            outdir = cls.root / key.replace(":", "_")
            cls.results[key] = (hook, outdir, hook.run(cls.design, outdir, rid="test-run"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_registry_is_populated(self):
        self.assertGreaterEqual(len(HOOK_REGISTRY), 15)
        for vendor in ("neutral", "cadence", "synopsys", "siemens"):
            self.assertTrue(any(k.startswith(vendor + ":") for k in HOOK_REGISTRY),
                            f"no hooks registered for {vendor}")

    def test_every_hook_emits_without_errors(self):
        for key, (hook, outdir, result) in self.results.items():
            with self.subTest(target=key):
                errs = [f for f in result.findings if f.severity == "error"]
                self.assertEqual([], errs, f"{key}: {[str(e) for e in errs]}")
                self.assertTrue(result.ok)
                self.assertTrue(result.files, f"{key} emitted no files")

    def test_hooks_need_no_vendor_tools(self):
        """Pure emitters: nothing here may require a license to run."""
        for key, (hook, outdir, result) in self.results.items():
            with self.subTest(target=key):
                self.assertEqual(result.tier, TIER_EMITTED,
                                 f"{key} claims {result.tier} without vendor evidence")
                self.assertIn(result.fidelity, FIDELITY_ORDER)

    def test_manifest_hashes_match_files(self):
        for key, (hook, outdir, result) in self.results.items():
            man = result.manifest(outdir)
            for entry in man["files"]:
                with self.subTest(target=key, file=entry["path"]):
                    path = outdir / entry["path"]
                    self.assertTrue(path.exists())
                    self.assertEqual(entry["sha256"], sha256_of(path))
                    self.assertEqual(entry["bytes"], path.stat().st_size)

    def test_every_text_artifact_carries_provenance(self):
        skip = {"manifest.json", "assembly.json", "primewave_sweep_plan.json"}
        for key, (hook, outdir, result) in self.results.items():
            for rel in result.files:
                path = outdir / rel
                if path.suffix not in TEXT_SUFFIXES or path.name in skip:
                    continue
                if rel.endswith(".provenance.json"):
                    doc = json.loads(path.read_text())
                    self.assertEqual(set(PROVENANCE_FIELDS), set(doc))
                    continue
                with self.subTest(target=key, file=rel):
                    head = path.read_text(errors="ignore")[:3000]
                    if path.suffix == ".json":
                        self.assertIn("provenance", head)
                    else:
                        self.assertIn("3DIC-X handoff artifact", head,
                                      f"{rel} has no provenance header")
                        self.assertIn("claim_limit", head)
                        self.assertIn("fidelity", head)

    def test_synthetic_fidelity_is_flagged(self):
        """Anything derived from the dB-per-inch heuristic must say so."""
        for key, (hook, outdir, result) in self.results.items():
            if result.fidelity != "SYNTHETIC":
                continue
            with self.subTest(target=key):
                self.assertTrue(any(f.check == "fidelity" for f in result.findings),
                                f"{key} is SYNTHETIC but emits no warning")

    def test_selector_resolution(self):
        self.assertEqual(len(resolve("all")), len(HOOK_REGISTRY))
        self.assertGreaterEqual(len(resolve("neutral:all")), 8)
        self.assertEqual(len(resolve("cadence:celsius")), 1)
        with self.assertRaises(KeyError):
            resolve("acme:nonexistent")

    # --- vendor-specific physical invariants --------------------------------
    def test_celsius_power_map_conserves_power(self):
        _, outdir, _ = self.results["cadence:celsius"]
        for die in self.design.dies:
            path = outdir / f"power_map_{die.name}.csv"
            rows = list(csv.DictReader(
                ln for ln in path.read_text().splitlines() if not ln.startswith("#")))
            total = sum(float(r["power_w"]) for r in rows)
            with self.subTest(die=die.name):
                self.assertAlmostEqual(total, die.power_w, places=6)
                self.assertEqual(len(rows), 256)

    def test_voltus_current_profile_respects_didt(self):
        _, outdir, _ = self.results["cadence:voltus_fi"]
        rows = list(csv.DictReader(
            ln for ln in (outdir / "current_profile.csv").read_text().splitlines()
            if not ln.startswith("#")))
        t = [float(r["time_ns"]) for r in rows]
        i = [float(r["current_a"]) for r in rows]
        slopes = [(i[k + 1] - i[k]) / (t[k + 1] - t[k])
                  for k in range(len(rows) - 1) if t[k + 1] > t[k]]
        self.assertLessEqual(max(slopes), self.design.didt_a_per_ns * 1.001)
        self.assertGreater(max(i), 0.0)

    def test_calibre_stack_is_contiguous_in_z(self):
        _, outdir, _ = self.results["siemens:calibre_3dstack"]
        asm = json.loads((outdir / "assembly.json").read_text())
        self.assertEqual(asm["units"]["length"], "um")
        z = 0.0
        for entry in asm["stack"]:
            self.assertAlmostEqual(entry["z_bottom_um"], z, places=6)
            z = entry["z_top_um"]
        self.assertAlmostEqual(z, sum(d.thickness_um for d in self.design.dies), places=6)
        names = {e["die"] for e in asm["stack"]}
        for iface in asm["interfaces"]:
            for side in iface["between"]:
                self.assertTrue(side in names or side == "package")

    def test_hyperlynx_bundle_is_self_sufficient(self):
        """Cheapest T1 in the plan: it must ship everything HyperLynx needs."""
        _, outdir, result = self.results["siemens:hyperlynx"]
        names = set(result.files)
        self.assertIn("stackup_3dic_x.json", names)
        self.assertTrue(any(n.endswith(".s4p") for n in names))
        self.assertTrue(any(n.endswith(".ibs") for n in names))
        self.assertTrue(any(n.endswith(".ami") for n in names))

    def test_sigrity_port_count_matches_links(self):
        _, outdir, _ = self.results["cadence:sigrity_edb"]
        rows = list(csv.DictReader(
            ln for ln in (outdir / "port_definitions.csv").read_text().splitlines()
            if not ln.startswith("#")))
        self.assertEqual(len(rows), 4 * len(self.design.links))

    def test_drivers_are_emitted_where_a_tool_must_be_run(self):
        for key in ("cadence:celsius", "cadence:voltus_fi", "synopsys:primesim",
                    "synopsys:starrc", "siemens:calibre_3dstack", "siemens:hyperlynx"):
            hook, outdir, result = self.results[key]
            with self.subTest(target=key):
                self.assertIsNotNone(result.driver, f"{key} has no driver script")
                self.assertTrue((outdir / result.driver).exists())


if __name__ == "__main__":
    unittest.main()
