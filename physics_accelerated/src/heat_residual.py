"""Discrete heat-equation residual, for physics-informed training.

This is what turns the FNO from a data-driven neural operator into a
*physics-informed* neural operator (PINO, Li et al. 2021). An FNO is an
architecture; "physics-informed" is a property of the loss. Trained on labels
alone, the network reproduces whatever the label generator did -- including its
bugs, which is how a solver running on a normalized grid with a hand-tuned scale
constant went unnoticed for months.

The residual is the finite-volume conduction equation evaluated on the predicted
field:

    r = ( sum_nb G_nb (T_nb - T) + G_bc (T_inf - T) + Q ) / sum(G)

Dividing by the total conductance puts r in kelvin, so it is directly
comparable to the data loss and interpretable on its own: "this field violates
the heat equation by X K per cell".  r == 0 exactly when T solves the discrete
equation.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class HeatEquationResidual(nn.Module):
    def __init__(self, dx_m: float, dy_m: float, dz_m, k_w_mk,
                 h_top: float, h_bottom: float, t_ambient_c: float):
        super().__init__()
        dz = torch.as_tensor(dz_m, dtype=torch.float32)
        k = torch.as_tensor(k_w_mk, dtype=torch.float32)
        if dz.shape != k.shape:
            raise ValueError("dz and k must have one entry per layer")
        layers = dz.numel()
        area_z = dx_m * dy_m

        gx = k * (dy_m * dz) / dx_m
        gy = k * (dx_m * dz) / dy_m
        gz = torch.stack([area_z / ((dz[i] / 2) / k[i] + (dz[i + 1] / 2) / k[i + 1])
                          for i in range(layers - 1)]) if layers > 1 \
            else torch.zeros(0)
        g_top = area_z / ((dz[0] / 2) / k[0] + 1.0 / h_top)
        g_bot = area_z / ((dz[-1] / 2) / k[-1] + 1.0 / h_bottom)

        denom = 2.0 * gx + 2.0 * gy
        vert = torch.zeros(layers)
        for i in range(layers):
            if i > 0:
                vert[i] += gz[i - 1]
            if i < layers - 1:
                vert[i] += gz[i]
        vert[0] += g_top
        vert[-1] += g_bot
        denom = denom + vert

        bc = torch.zeros(layers)
        bc[0] += g_top * t_ambient_c
        bc[-1] += g_bot * t_ambient_c

        self.register_buffer("gx", gx.view(1, -1, 1, 1))
        self.register_buffer("gy", gy.view(1, -1, 1, 1))
        self.register_buffer("gz", gz)
        self.register_buffer("denom", denom.view(1, -1, 1, 1))
        self.register_buffer("bc", bc.view(1, -1, 1, 1))
        self.layers = layers

    def forward(self, t_c: torch.Tensor, q_w: torch.Tensor) -> torch.Tensor:
        """Residual in kelvin, same shape as the input field."""
        pad = F.pad(t_c, (1, 1, 1, 1), mode="replicate")   # adiabatic sides
        inplane = self.gx * (pad[:, :, 1:-1, 2:] + pad[:, :, 1:-1, :-2]) \
            + self.gy * (pad[:, :, 2:, 1:-1] + pad[:, :, :-2, 1:-1])

        vertical = torch.zeros_like(t_c)
        for i in range(self.layers):
            if i > 0:
                vertical[:, i] = vertical[:, i] + self.gz[i - 1] * t_c[:, i - 1]
            if i < self.layers - 1:
                vertical[:, i] = vertical[:, i] + self.gz[i] * t_c[:, i + 1]

        return (inplane + vertical + self.bc + q_w) / self.denom - t_c

    def rms_k(self, t_c: torch.Tensor, q_w: torch.Tensor) -> float:
        with torch.no_grad():
            return float(torch.sqrt((self.forward(t_c, q_w) ** 2).mean()))

    @classmethod
    def from_solver(cls, solver, refine_z: int = 1) -> "HeatEquationResidual":
        """Build from serdes_architect's ThermalSolver so the discretisation,
        materials and boundary conditions cannot drift apart.

        `refine_z` splits every layer into that many sub-layers of equal
        thickness and identical material, which is the same stack discretised
        more finely rather than a different stack. It exists because the
        surrogate's discretisation error turned out to be **vertical**: refining
        16x16 to 32x32 in plane moves the peak by -0.27 C on average and not
        even consistently in sign, while going from one z-cell per layer to two
        moves it +1.77 C, consistently positive. A surrogate that predicts on
        the refined stack needs a residual operator defined on the same one.
        """
        if refine_z < 1:
            raise ValueError("refine_z must be at least 1")
        dz = torch.as_tensor(solver.dz, dtype=torch.float32)
        k = torch.as_tensor(solver.k, dtype=torch.float32)
        if refine_z > 1:
            dz = torch.repeat_interleave(dz / refine_z, refine_z)
            k = torch.repeat_interleave(k, refine_z)
        return cls(dx_m=solver.dx, dy_m=solver.dy, dz_m=dz,
                   k_w_mk=k, h_top=solver.h_top,
                   h_bottom=solver.h_bottom, t_ambient_c=solver.t_ambient)
