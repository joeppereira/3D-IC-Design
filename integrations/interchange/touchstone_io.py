"""Touchstone writer + reader + electrical checks (spec 2.6).

The repo's SI path (serdes_architect/src/si_analyzer.py) is a dB-per-inch budget
calculator, not a channel model.  This module synthesizes a *causal* 4-port from
that budget using a wideband-Debye (Djordjevic-Sarkar style) permittivity, so
the artifact has a physically shaped frequency dependence and still matches the
surrogate's insertion-loss number at Nyquist.

The result is SYNTHETIC, not field-solved.  Every file says so.  Replacing this
with physics_accelerated/src/maxwell_em_solver.py output is what upgrades the
channel claim from T0 to T2 (spec 2.6 step 2).

Port ordering, declared in every file because a mismatched order is the most
common way a downstream engineer gets garbage:
    1,2 = TX P/N     3,4 = RX P/N
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from ..base import Finding, SEV_ERROR, SEV_WARN, SEV_INFO, provenance_header
from ..canonical import Link, MATERIAL_LOSS_DB_PER_INCH

C0 = 299_792_458.0
RHO_CU = 1.72e-8
NP_PER_DB = 1.0 / 8.685889638065035

# Conductor cross-section per material class (m^2) for the DC resistance term.
CONDUCTOR_AREA_M2 = {"FR4": 3.5e-9, "Megtron_7": 3.5e-9, "Twinax": 1.3e-8, "Flyover": 1.3e-8}
# Wideband-Debye corner frequencies (rad/s): 1 kHz .. 1 THz.
M1, M2 = 2 * math.pi * 1e3, 2 * math.pi * 1e12

RHO_DIFF = 0.05      # differential return loss magnitude (~-26 dB)
RHO_COMM = 0.10      # common-mode return loss
DEFAULT_DF_GHZ = 0.25


def freq_grid(link: Link, df_ghz: float = DEFAULT_DF_GHZ,
              fmax_ghz: float | None = None) -> np.ndarray:
    """DC..>=2x Nyquist on a uniform grid (uniform + DC is required for the
    causality check's inverse FFT)."""
    fmax = fmax_ghz if fmax_ghz is not None else 2.0 * link.nyquist_ghz
    n = int(round(fmax / df_ghz))
    return np.arange(0, n + 1, dtype=float) * df_ghz * 1e9


def _eps_debye(f_hz: np.ndarray, dk: float, df: float) -> np.ndarray:
    """Causal wideband-Debye relative permittivity (Djordjevic-Sarkar form)."""
    w = 2 * math.pi * np.maximum(f_hz, 1.0)
    span = math.log(M2 / M1)
    # delta_eps sized so that tan(delta) ~= df at 1 GHz
    delta = dk * df * span / (math.pi / 2.0)
    return dk + delta * np.log((M2 + 1j * w) / (M1 + 1j * w)) / span


def _dc_attenuation_db(link: Link) -> float:
    area = CONDUCTOR_AREA_M2.get(link.material, 3.5e-9)
    r_dc = RHO_CU * (link.reach_mm / 1000.0) / area
    t = (2 * link.z0_ohm) / (2 * link.z0_ohm + r_dc)
    return -20.0 * math.log10(t)


def _min_phase(mag: np.ndarray) -> np.ndarray:
    """Minimum-phase transfer function with the given magnitude response.

    Cepstral construction: fold the real cepstrum of ln|H| to its causal half.
    The result is causal by construction, which a scalar-scaled sqrt(f) loss
    term is not -- that shortcut produced >20% pre-cursor energy on lossy
    channels, which the causality check rejected.
    """
    n_fft = 2 * (len(mag) - 1)
    c = np.fft.irfft(np.log(np.maximum(mag, 1e-300)), n=n_fft)
    folded = np.zeros_like(c)
    half = n_fft // 2
    folded[0] = c[0]
    folded[1:half] = 2.0 * c[1:half]
    folded[half] = c[half]
    return np.exp(np.fft.rfft(folded, n=n_fft))


def _group_delay_s(link: Link, dk: float) -> float:
    return (link.reach_mm / 1000.0) * math.sqrt(dk) / C0


def synth_channel(link: Link, freqs: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (freqs_hz, S[n,4,4], model_info) for one differential link."""
    if freqs is None:
        freqs = freq_grid(link)
    dk, df = link.dk_df
    inches = link.reach_mm / 25.4
    length_m = link.reach_mm / 1000.0

    eps = _eps_debye(freqs, dk, df)
    # gamma from the causal permittivity: dielectric loss + dispersion.
    w = 2 * math.pi * np.maximum(freqs, 1.0)
    gamma_diel = 1j * w * np.sqrt(eps.astype(complex)) / C0
    alpha_diel_db = np.real(gamma_diel) / NP_PER_DB * length_m

    f_ghz = freqs / 1e9
    nyq = link.nyquist_ghz
    dc_db = _dc_attenuation_db(link)
    target_db = MATERIAL_LOSS_DB_PER_INCH.get(link.material, 11.6) * inches

    # Conductor term A*sqrt(f) absorbs whatever the causal dielectric model does
    # not already account for at Nyquist, so IL(Nyquist) matches si_analyzer.
    diel_at_nyq = float(np.interp(nyq, f_ghz, alpha_diel_db))
    a_cond = max(target_db - diel_at_nyq - dc_db, 0.0) / math.sqrt(nyq)
    alpha_db = dc_db + a_cond * np.sqrt(f_ghz) + alpha_diel_db

    tau = _group_delay_s(link, dk)
    phase = np.exp(-2j * math.pi * freqs * tau)
    # Magnitude from the loss model; phase from the minimum-phase construction
    # plus the physical propagation delay -> causal by construction.
    t_diff = _min_phase(np.exp(-alpha_db * NP_PER_DB)) * phase
    t_comm = _min_phase(np.exp(-0.9 * alpha_db * NP_PER_DB)) * np.exp(-2j * math.pi * freqs * 0.98 * tau)

    # Passivity for a symmetric 2-port S=[[r,t],[t,r]] requires |r+t| <= 1
    # (its eigenvalues are r+t and r-t), NOT |r|^2+|t|^2 <= 1.
    rho_d = np.clip(np.minimum(RHO_DIFF, 1.0 - np.abs(t_diff)), 0.0, 1.0)
    rho_c = np.clip(np.minimum(RHO_COMM, 1.0 - np.abs(t_comm)), 0.0, 1.0)

    n = len(freqs)
    smm = np.zeros((n, 4, 4), dtype=complex)       # basis order: d1, c1, d2, c2
    smm[:, 0, 0] = rho_d
    smm[:, 2, 2] = rho_d
    smm[:, 0, 2] = smm[:, 2, 0] = t_diff
    smm[:, 1, 1] = rho_c
    smm[:, 3, 3] = rho_c
    smm[:, 1, 3] = smm[:, 3, 1] = t_comm

    # Orthonormal mixed-mode -> single-ended transform (ports 1,2 = pair A).
    r2 = 1.0 / math.sqrt(2.0)
    T = np.array([[r2, -r2, 0, 0],
                  [r2,  r2, 0, 0],
                  [0, 0, r2, -r2],
                  [0, 0, r2,  r2]])
    s_se = np.einsum("ji,njk,kl->nil", T, smm, T)

    info = {
        "model": "wideband-Debye + sqrt(f) conductor magnitude, minimum-phase + pure delay",
        "dk": dk, "df": df,
        "dc_attenuation_db": round(dc_db, 4),
        "target_il_db_at_nyquist": round(target_db, 3),
        "nyquist_ghz": nyq,
        "fmax_ghz": float(f_ghz[-1]),
        "points": n,
        "group_delay_ps": round(_group_delay_s(link, dk) * 1e12, 2),
        "port_order": "1,2 = TX P/N; 3,4 = RX P/N",
    }
    return freqs, s_se, info


# --- differential extraction -------------------------------------------------
def sdd21(s: np.ndarray) -> np.ndarray:
    return 0.5 * (s[:, 2, 0] - s[:, 3, 0] - s[:, 2, 1] + s[:, 3, 1])


def sdd11(s: np.ndarray) -> np.ndarray:
    return 0.5 * (s[:, 0, 0] - s[:, 1, 0] - s[:, 0, 1] + s[:, 1, 1])


def insertion_loss_db(s: np.ndarray) -> np.ndarray:
    return -20.0 * np.log10(np.maximum(np.abs(sdd21(s)), 1e-300))


def il_at(freqs: np.ndarray, s: np.ndarray, f_ghz: float) -> float:
    return float(np.interp(f_ghz * 1e9, freqs, insertion_loss_db(s)))


# --- checks ------------------------------------------------------------------
def check_passivity(s: np.ndarray, tol: float = 1e-9) -> tuple[bool, float]:
    worst = float(max(np.linalg.svd(m, compute_uv=False)[0] for m in s))
    return worst <= 1.0 + tol, worst


def check_reciprocity(s: np.ndarray, tol: float = 1e-12) -> tuple[bool, float]:
    err = float(np.max(np.abs(s - np.transpose(s, (0, 2, 1)))))
    return err <= tol, err


def check_causality(freqs: np.ndarray, s: np.ndarray,
                    delay_s: float | None = None) -> tuple[float, float]:
    """Pre-cursor energy fraction of the through path's impulse response.

    A causal channel puts no energy before its propagation delay.  Measured
    against the physical delay when known (argmax is unreliable on a heavily
    dispersive channel).  Returns (precursor_fraction, delay_s) -- an honest
    numeric metric, not a claim of exact Kramers-Kronig compliance.
    """
    h = np.fft.irfft(sdd21(s), n=2 * (len(freqs) - 1))
    dt = 1.0 / (2.0 * freqs[-1])
    energy = np.abs(h) ** 2
    total = float(energy.sum()) or 1.0
    if delay_s is None:
        ref = int(np.argmax(energy))
    else:
        ref = int(delay_s / dt)
    guard = max(int(0.1 * ref), 2)
    pre = float(energy[:max(ref - guard, 0)].sum())
    return pre / total, ref * dt


def check_dc(s: np.ndarray) -> tuple[bool, complex]:
    dc = complex(sdd21(s)[0])
    return (abs(dc.imag) <= 1e-12 * max(abs(dc.real), 1.0) and 0.0 < dc.real <= 1.0), dc


# --- file I/O ----------------------------------------------------------------
def write(link: Link, path: Path, prov: dict,
          freqs: np.ndarray | None = None, s: np.ndarray | None = None,
          info: dict | None = None) -> Path:
    if s is None:
        freqs, s, info = synth_channel(link, freqs)
    n_ports = s.shape[1]
    L = [provenance_header(prov, "!").rstrip("\n"),
         f"! link:        {link.name}",
         f"! rate:        {link.rate_gbps} Gbps {link.modulation} "
         f"({link.baud_gbd:g} GBd, Nyquist {link.nyquist_ghz:g} GHz)",
         f"! material:    {link.material}   reach: {link.reach_mm} mm",
         f"! port order:  {info['port_order']}",
         f"! model:       {info['model']}",
         "! WARNING: SYNTHETIC channel derived from an analytic loss budget.",
         "!          Not measured, not field-solved. Do not use for sign-off.",
         f"# GHz S RI R {link.z0_ohm:g}"]
    for i, f in enumerate(freqs):
        row = [f"{f / 1e9:.6f}"]
        for a in range(n_ports):
            for b in range(n_ports):
                v = s[i, a, b]
                row.append(f"{v.real:+.9e} {v.imag:+.9e}")
            if a < n_ports - 1:
                row.append("\n         ")
        L.append(" ".join(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def read(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Independent Touchstone parser (RI format, N ports inferred from data)."""
    text = Path(path).read_text()
    opt = re.search(r"^#\s*(\w+)\s+S\s+(\w+)\s+R\s+([\d.]+)", text, re.M | re.I)
    if not opt:
        raise ValueError("no Touchstone option line")
    unit_mult = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}[opt.group(1).upper()]
    fmt, z0 = opt.group(2).upper(), float(opt.group(3))
    if fmt != "RI":
        raise ValueError(f"only RI is written by this repo, got {fmt}")
    n_ports = int(re.search(r"\.s(\d+)p$", str(path), re.I).group(1))

    nums: list[float] = []
    for line in text.splitlines():
        line = line.split("!", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        nums.extend(float(tok) for tok in line.split())
    stride = 1 + 2 * n_ports * n_ports
    if len(nums) % stride:
        raise ValueError(f"data length {len(nums)} is not a multiple of {stride}")
    arr = np.array(nums).reshape(-1, stride)
    freqs = arr[:, 0] * unit_mult
    body = arr[:, 1:].reshape(-1, n_ports, n_ports, 2)
    s = body[..., 0] + 1j * body[..., 1]
    return freqs, s, {"z0": z0, "n_ports": n_ports, "format": fmt}


def validate(freqs: np.ndarray, s: np.ndarray, link: Link,
             precursor_tol: float = 0.01, delay_s: float | None = None) -> list[Finding]:
    out: list[Finding] = []
    passive, worst = check_passivity(s)
    out.append(Finding(SEV_INFO if passive else SEV_ERROR, "passivity",
                       f"max singular value {worst:.9f} {'<=' if passive else '>'} 1"))
    recip, err = check_reciprocity(s)
    out.append(Finding(SEV_INFO if recip else SEV_ERROR, "reciprocity",
                       f"max |S - S^T| = {err:.3e}"))
    ok_dc, dc = check_dc(s)
    out.append(Finding(SEV_INFO if ok_dc else SEV_ERROR, "dc_point",
                       f"Sdd21(DC) = {dc.real:.6f}{dc.imag:+.1e}j "
                       "(must be real, positive, <= 1)"))
    if delay_s is None:
        delay_s = _group_delay_s(link, link.dk_df[0])
    frac, delay = check_causality(freqs, s, delay_s)
    out.append(Finding(SEV_INFO if frac <= precursor_tol else SEV_ERROR, "causality",
                       f"pre-cursor energy {frac * 100:.4f}% of total "
                       f"(tol {precursor_tol * 100:g}%), delay {delay * 1e12:.1f} ps"))
    il = insertion_loss_db(s)
    if not np.all(np.diff(il[1:]) >= -1e-6):
        out.append(Finding(SEV_WARN, "monotonic_loss",
                           "insertion loss is not monotonic in frequency"))
    if freqs[-1] < 2.0 * link.nyquist_ghz * 1e9 - 1:
        out.append(Finding(SEV_WARN, "bandwidth",
                           f"fmax {freqs[-1] / 1e9:.1f} GHz < 2x Nyquist "
                           f"({2 * link.nyquist_ghz:.1f} GHz)"))
    target = MATERIAL_LOSS_DB_PER_INCH.get(link.material, 11.6) * link.reach_mm / 25.4
    got = il_at(freqs, s, link.nyquist_ghz)
    if abs(got - target) > max(0.5, 0.05 * target):
        out.append(Finding(SEV_ERROR, "il_calibration",
                           f"IL(Nyquist)={got:.2f} dB != si_analyzer budget {target:.2f} dB"))
    else:
        out.append(Finding(SEV_INFO, "il_calibration",
                           f"IL(Nyquist)={got:.2f} dB matches si_analyzer budget "
                           f"{target:.2f} dB"))
    return out
