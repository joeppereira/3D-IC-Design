"""What does PhysicsNeMo's default domain padding actually buy on our problem?

PhysicsNeMo's FNO takes `padding=8` by default; our FNO2d has no padding at all.
Citing their default is not evidence, so this trains their FNO on our z-refined
mixed training set twice -- padding=0 and padding=8, everything else identical --
and measures the three things that matter:

    held-out field RMSE and peak error  (does it cost accuracy?)
    error in the outer ring vs the core  (is the boundary the weak spot?)
    far-edge error vs opposite-edge power  (is the wrap gone?)

Both arms use PhysicsNeMo's model and a plain MSE data loss, so the only
difference is the padding. That makes this an ablation of padding rather than a
comparison of our training recipe against theirs; the PINO residual term our
production model uses is absent from both arms and would have to be re-measured
on top.

One seed, so the tail statistics (peak error, antipodal slope) are indicative
rather than settled -- see reports/physicsnemo_gap_review.md section 1.5, which
is why the recommendation there is a multi-seed trial rather than adoption.

Needs PhysicsNeMo, which is an optional dependency:

    pip install nvidia-physicsnemo
    python physics_accelerated/src/padding_ablation.py    # ~8 min, CPU
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from physicsnemo.models.fno import FNO

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "physics_accelerated/data"
GRID, EPOCHS, SEED = 16, 40, 2

x_tr = torch.load(DATA / "x_mixed_z2_train.pt", map_location="cpu", weights_only=True)
y_tr = torch.load(DATA / "y_mixed_z2_train.pt", map_location="cpu", weights_only=True)
x_te = torch.load(DATA / "x_mixed_z2_test.pt", map_location="cpu", weights_only=True)
y_te = torch.load(DATA / "y_mixed_z2_test.pt", map_location="cpu", weights_only=True)
channels = x_tr.shape[1]

# Normalisation from the training split only, as train.py does.
mean, std = float(y_tr.mean()), float(y_tr.std())
loader = DataLoader(TensorDataset(x_tr, (y_tr - mean) / std),
                    batch_size=32, shuffle=True)

ii, jj = np.meshgrid(np.arange(GRID), np.arange(GRID), indexing="ij")
edge_dist = np.minimum.reduce([ii, jj, GRID - 1 - ii, GRID - 1 - jj])
OUTER, CORE = edge_dist == 0, edge_dist >= 4


def antipodal_slope(err: np.ndarray, power: np.ndarray) -> float:
    """Kelvin of edge error per watt sitting on the opposite edge."""
    p, e = [], []
    for a, b in ((0, -1), (-1, 0)):
        p.append(power[:, :, a].sum(axis=1)); e.append(err[:, :, b].mean(axis=1))
        p.append(power[:, a, :].sum(axis=1)); e.append(err[:, b, :].mean(axis=1))
    p, e = np.concatenate(p), np.concatenate(e)
    A = np.vstack([p, np.ones_like(p)]).T
    return float(np.linalg.lstsq(A, e, rcond=None)[0][0])


results = {}
for padding in (0, 8):
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    model = FNO(in_channels=channels, out_channels=channels, decoder_layers=1,
                decoder_layer_size=128, decoder_activation_fn="gelu",
                dimension=2, latent_channels=32, num_fno_layers=4,
                num_fno_modes=8, padding=padding, activation_fn="gelu",
                coord_features=True)
    opt = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = optim.lr_scheduler.StepLR(opt, step_size=10, gamma=0.5)
    crit = nn.MSELoss()

    t0 = time.perf_counter()
    for epoch in range(EPOCHS):
        model.train()
        tot = 0.0
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
            tot += loss.item()
        sched.step()
        if (epoch + 1) % 10 == 0:
            print(f"  padding={padding} epoch {epoch + 1:2d}/{EPOCHS} "
                  f"train MSE {tot / len(loader):.5f}", flush=True)
    train_s = time.perf_counter() - t0

    model.eval()
    with torch.no_grad():
        pred = model(x_te) * std + mean
    err = (pred - y_te).numpy()
    row = {
        "padding": padding,
        "train_s": train_s,
        "field_rmse_k": float(torch.sqrt(((pred - y_te) ** 2).mean())),
        "peak_mean_abs_k": float((pred.amax(dim=(1, 2, 3))
                                  - y_te.amax(dim=(1, 2, 3))).abs().mean()),
        "peak_max_abs_k": float((pred.amax(dim=(1, 2, 3))
                                 - y_te.amax(dim=(1, 2, 3))).abs().max()),
        "outer_ring_mean_abs_k": float(np.abs(err[:, :, OUTER]).mean()),
        "core_mean_abs_k": float(np.abs(err[:, :, CORE]).mean()),
        "antipodal_slope_k_per_w": antipodal_slope(err[:, 0], x_te.numpy().sum(axis=1)),
    }
    row["outer_over_core"] = row["outer_ring_mean_abs_k"] / row["core_mean_abs_k"]
    results[f"padding_{padding}"] = row
    print(f"padding={padding}: RMSE {row['field_rmse_k']:.4f} K | peak "
          f"{row['peak_mean_abs_k']:.4f} K | outer/core "
          f"{row['outer_over_core']:.2f}x | antipodal "
          f"{row['antipodal_slope_k_per_w']:+.4f} K/W | {train_s:.0f} s",
          flush=True)

Path(REPO / "reports/padding_ablation.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
