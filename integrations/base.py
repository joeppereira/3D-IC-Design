"""Hook framework for 3DIC-X -> EDA interchange.

Every hook is a *pure emitter*: it reads a DesignRecord, writes files, and
returns a manifest.  It never invokes a vendor binary and never needs a
license to run, which is what makes the whole layer testable in CI.

See reports/eda_vendor_integration_spec.md for the contract and the T0-T3
claim ladder.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Claim ladder (spec section 1.1) -----------------------------------------
TIER_EMITTED = "T0"      # standard file written, read back by an independent parser
TIER_INGESTED = "T1"     # a licensed vendor tool loaded it cleanly
TIER_CORRELATED = "T2"   # vendor high-fidelity result compared, error band published
TIER_SIGNOFF = "T3"      # out of scope for 3DIC-X, permanently

# --- Fidelity of the upstream data (spec section 1.4) -----------------------
FIDELITY_MEASURED = "MEASURED"     # silicon or lab data
FIDELITY_FIELD = "FIELD_SOLVED"   # full-wave / FEA solver output
FIDELITY_SURROGATE = "SURROGATE"  # FNO / ROM / PINN prediction
FIDELITY_SYNTHETIC = "SYNTHETIC"  # derived from an analytic heuristic
FIDELITY_ORDER = [FIDELITY_SYNTHETIC, FIDELITY_SURROGATE, FIDELITY_FIELD, FIDELITY_MEASURED]

SEV_INFO, SEV_WARN, SEV_ERROR = "info", "warning", "error"


@dataclass
class Finding:
    severity: str
    check: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7}] {self.check}: {self.message}"


@dataclass
class HookResult:
    vendor: str
    tool: str
    tier: str
    fidelity: str
    files: list[str] = field(default_factory=list)
    driver: str | None = None
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == SEV_ERROR for f in self.findings)

    def manifest(self, outdir: Path) -> dict:
        return {
            "vendor": self.vendor,
            "tool": self.tool,
            "tier": self.tier,
            "fidelity": self.fidelity,
            "driver": self.driver,
            "files": [
                {"path": p, "sha256": sha256_of(outdir / p), "bytes": (outdir / p).stat().st_size}
                for p in sorted(self.files)
            ],
            "findings": [asdict(f) for f in self.findings],
            "notes": self.notes,
            "ok": self.ok,
        }


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + git_sha()


# --- Provenance (spec section 1.4) ------------------------------------------
PROVENANCE_FIELDS = ("run_id", "git_sha", "design_record", "generator", "fidelity",
                     "validation", "claim_limit")
CLAIM_LIMIT = ("Architectural exploration only. Re-verify in a certified flow "
               "before tape-out.")


def provenance(generator: str, fidelity: str, design_hash: str, rid: str,
               validation: str = "pending") -> dict:
    return {
        "run_id": rid,
        "git_sha": git_sha(),
        "design_record": f"sha256:{design_hash[:16]}",
        "generator": generator,
        "fidelity": fidelity,
        "validation": validation,
        "claim_limit": CLAIM_LIMIT,
    }


def provenance_header(prov: dict, comment: str = "*") -> str:
    """Render the provenance block using the comment syntax of the target format."""
    lines = [f"{comment} 3DIC-X handoff artifact -- NOT A SIGN-OFF DECK"]
    width = max(len(k) for k in PROVENANCE_FIELDS) + 1
    for k in PROVENANCE_FIELDS:
        lines.append(f"{comment} {k + ':':<{width}} {prov[k]}")
    return "\n".join(lines) + "\n"


def write_text_with_provenance(path: Path, body: str, prov: dict,
                               comment: str = "#") -> Path:
    """Write any driver/auxiliary file with the mandatory provenance block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = provenance_header(prov, comment)
    if body.startswith("#!"):                     # keep the shebang first
        shebang, _, rest = body.partition("\n")
        path.write_text(shebang + "\n" + header + rest.lstrip("\n") + "\n")
    else:
        path.write_text(header + body.rstrip("\n") + "\n")
    return path


def write_sidecar(path: Path, prov: dict) -> Path:
    """For binary formats (GDSII) that cannot carry a comment header."""
    side = path.with_suffix(path.suffix + ".provenance.json")
    side.write_text(json.dumps(prov, indent=2) + "\n")
    return side


class VendorHook(ABC):
    vendor: str = "neutral"
    tool: str = "unnamed"
    tier: str = TIER_EMITTED
    fidelity: str = FIDELITY_SURROGATE
    requires: tuple[str, ...] = ()
    rid: str = ""

    @property
    def target(self) -> str:
        return f"{self.vendor}:{self.tool}"

    @abstractmethod
    def emit(self, design, outdir: Path) -> HookResult:
        """Write artifacts into outdir and return the manifest."""

    def validate(self, design, result: HookResult, outdir: Path) -> list[Finding]:
        """T0 self-check with open tooling. Subclasses override with real parsers."""
        findings: list[Finding] = []
        for rel in result.files:
            p = outdir / rel
            if not p.exists():
                findings.append(Finding(SEV_ERROR, "exists", f"{rel} was not written"))
            elif p.stat().st_size == 0:
                findings.append(Finding(SEV_ERROR, "non_empty", f"{rel} is empty"))
        if result.fidelity == FIDELITY_SYNTHETIC:
            findings.append(Finding(
                SEV_WARN, "fidelity",
                f"{self.target} is derived from an analytic heuristic; the artifact is "
                "SYNTHETIC and must not be presented as measured or field-solved data"))
        return findings

    def check_requires(self, design) -> list[Finding]:
        missing = [f for f in self.requires if not design.has(f)]
        return [Finding(SEV_ERROR, "requires", f"DesignRecord is missing '{f}'")
                for f in missing]

    def prov(self, design, validation: str = "pending") -> dict:
        return provenance(f"integrations.{self.vendor}.{self.tool}", self.fidelity,
                          design.sha256(), self.rid or run_id(), validation)

    def run(self, design, outdir: Path, rid: str | None = None) -> HookResult:
        self.rid = rid or run_id()
        outdir.mkdir(parents=True, exist_ok=True)
        gaps = self.check_requires(design)
        if any(f.severity == SEV_ERROR for f in gaps):
            return HookResult(self.vendor, self.tool, self.tier, self.fidelity, findings=gaps)
        result = self.emit(design, outdir)
        result.findings.extend(gaps)
        result.findings.extend(self.validate(design, result, outdir))
        return result


HOOK_REGISTRY: dict[str, type[VendorHook]] = {}


def register(cls: type[VendorHook]) -> type[VendorHook]:
    HOOK_REGISTRY[f"{cls.vendor}:{cls.tool}"] = cls
    return cls


def resolve(selector: str) -> list[type[VendorHook]]:
    """'cadence:celsius' -> one hook; 'neutral:all' / 'all' -> many."""
    if selector in HOOK_REGISTRY:
        return [HOOK_REGISTRY[selector]]
    if selector == "all":
        return list(HOOK_REGISTRY.values())
    vendor, _, tool = selector.partition(":")
    if tool in ("", "all"):
        hooks = [c for k, c in HOOK_REGISTRY.items() if k.startswith(vendor + ":")]
        if hooks:
            return hooks
    raise KeyError(f"unknown target '{selector}'; known: {sorted(HOOK_REGISTRY)}")


def fmt_findings(findings: Iterable[Finding]) -> str:
    return "\n".join(f"  {f}" for f in findings) or "  (none)"
