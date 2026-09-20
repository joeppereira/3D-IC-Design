"""Vendor-neutral interchange hooks (spec section 2).

Phase 0: every vendor flow in sections 3-5 consumes these, so they ship first
and must be T0-green before any vendor-specific work starts.
"""
from __future__ import annotations

from pathlib import Path

from ..base import (VendorHook, HookResult, Finding, register, SEV_INFO, SEV_WARN,
                    FIDELITY_SURROGATE, FIDELITY_SYNTHETIC, TIER_EMITTED)
from ..canonical import DesignRecord
from ..interchange import (stackup, def_io, lef_io, gds_io, spef_io, liberty_io,
                           touchstone_io as ts, spice_io, ibis_io)


@register
class StackupHook(VendorHook):
    vendor, tool = "neutral", "stackup"
    requires = ("dies", "interfaces")

    def emit(self, design: DesignRecord, outdir: Path) -> HookResult:
        p = stackup.write(design, outdir / "stackup_3dic_x.json", self.prov(design))
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity,
                          files=[p.name],
                          notes=["consumed by Celsius, Sigrity/EDB, HyperLynx, "
                                 "Calibre 3DSTACK and 3DIC Compiler"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        return f + stackup.validate(stackup.read(outdir / "stackup_3dic_x.json"))


@register
class LefHook(VendorHook):
    vendor, tool = "neutral", "lef"
    requires = ("macros",)

    def emit(self, design, outdir):
        p = lef_io.write(design, outdir / "3dic_x.lef", self.prov(design))
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=[p.name])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        return f + lef_io.validate(lef_io.read(outdir / "3dic_x.lef"), design)


@register
class DefHook(VendorHook):
    vendor, tool = "neutral", "def"
    requires = ("dies", "macros")

    def emit(self, design, outdir):
        files = []
        for die in design.dies:
            if not design.macros_on(die.name):
                continue
            p = def_io.write(design, die, outdir / f"{die.name}.def", self.prov(design))
            files.append(p.name)
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=files,
                          notes=["one DEF per die: a 3D stack is N DEFs plus the "
                                 "stack description, never a flattened view"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        for die in design.dies:
            path = outdir / f"{die.name}.def"
            if path.exists():
                f += def_io.validate(def_io.read(path), die, design.macros_on(die.name))
        return f


@register
class GdsHook(VendorHook):
    vendor, tool = "neutral", "gds"
    requires = ("dies", "macros")

    def emit(self, design, outdir):
        files = []
        for die in design.dies:
            if not design.macros_on(die.name):
                continue
            p = gds_io.write(design, die, outdir / f"{die.name}.gds", self.prov(design))
            files += [p.name, p.name + ".provenance.json"]
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=files,
                          notes=["replaces gds_export.tcl, in which every functional "
                                 "command was commented out"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        for die in design.dies:
            path = outdir / f"{die.name}.gds"
            if path.exists():
                f += gds_io.validate(gds_io.read(path), design, die)
        f.append(Finding(SEV_WARN, "gds_external_parser",
                         "KLayout/gdstk are not installed here; stream-out is verified "
                         "by this repo's own independent reader only"))
        return f


@register
class SpefHook(VendorHook):
    vendor, tool = "neutral", "spef"
    requires = ("nets",)

    def emit(self, design, outdir):
        p = spef_io.write(design, outdir / "3dic_x.spef", self.prov(design))
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=[p.name],
                          notes=[f"{len(design.nets)} modeled nets only -- a fabricated "
                                 "full-chip SPEF would be worse than none"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        return f + spef_io.validate(spef_io.read(outdir / "3dic_x.spef"), design)


@register
class LibertyHook(VendorHook):
    vendor, tool = "neutral", "liberty"
    requires = ("macros",)

    def emit(self, design, outdir):
        p = liberty_io.write(design, outdir / "3dic_x_macros.lib", self.prov(design))
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=[p.name],
                          notes=["pins and PG intent only; no timing arcs without a "
                                 "characterized source"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        return f + liberty_io.validate(liberty_io.read(outdir / "3dic_x_macros.lib"), design)


@register
class TouchstoneHook(VendorHook):
    vendor, tool = "neutral", "touchstone"
    fidelity = FIDELITY_SYNTHETIC
    requires = ("links",)

    def emit(self, design, outdir):
        files, notes = [], []
        for link in design.links:
            freqs, s, info = ts.synth_channel(link)
            p = ts.write(link, outdir / f"{link.name}.s4p", self.prov(design), freqs, s, info)
            files.append(p.name)
            notes.append(f"{link.name}: DC..{info['fmax_ghz']:.0f} GHz, "
                         f"{info['points']} pts, delay {info['group_delay_ps']} ps")
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity,
                          files=files, notes=notes)

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        for link in design.links:
            path = outdir / f"{link.name}.s4p"
            if path.exists():
                freqs, s, _ = ts.read(path)
                f += ts.validate(freqs, s, link)
        return f


@register
class IbisHook(VendorHook):
    vendor, tool = "neutral", "ibis"
    fidelity = FIDELITY_SYNTHETIC
    requires = ("links",)

    def emit(self, design, outdir):
        files = []
        for link in design.links[:1]:      # one buffer model per PHY class
            files.append(ibis_io.write_ibs(design, link, outdir / f"{link.name}.ibs",
                                           self.prov(design)).name)
            files.append(ibis_io.write_ami(design, link, outdir / f"{link.name}.ami",
                                           self.prov(design)).name)
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity, files=files,
                          notes=["buffer + AMI parameters only; the AMI DLL is C work "
                                 "budgeted separately (spec 2.7)"])

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        for name in [x for x in result.files if x.endswith(".ibs")]:
            f += ibis_io.validate(ibis_io.read_ibs(outdir / name))
        return f


@register
class SpiceHook(VendorHook):
    vendor, tool = "neutral", "spice"
    requires = ("links",)

    def emit(self, design, outdir):
        files, notes = [], []
        for link in design.links[:1]:
            p = spice_io.write_ngspice(design, link, outdir / f"{link.name}_ngspice.sp",
                                       self.prov(design, validation="ngspice"))
            files.append(p.name)
            notes.append("LTRA lossy line; runnable in ngspice/Xyce today")
        return HookResult(self.vendor, self.tool, self.tier, self.fidelity,
                          files=files, driver=files[0] if files else None, notes=notes)

    def validate(self, design, result, outdir):
        f = super().validate(design, result, outdir)
        for link in design.links[:1]:
            path = outdir / f"{link.name}_ngspice.sp"
            if path.exists():
                f += spice_io.validate(spice_io.run_ngspice(path), link, design)
        return f
