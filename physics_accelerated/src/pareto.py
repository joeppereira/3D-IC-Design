"""NSGA-II multi-objective search, with a hypervolume comparison against random
sampling.

gepa.py described itself as "GEPA Multi-Objective Optimization" but drew 50
random placements per generation and kept whichever minimised predicted peak
temperature -- a single objective, no dominance, no selection, and ten
independent random batches rather than ten generations.

This module implements the real thing:

    non-dominated sorting   (Deb et al. 2002, fast O(MN^2) ranking)
    crowding distance       (diversity along each front)
    tournament selection    (rank first, then crowding)
    SBX crossover + polynomial mutation
    hypervolume indicator   (Monte Carlo, to prove the front actually improves)

The claim it supports is falsifiable: at equal evaluation budget, NSGA-II must
dominate random sampling on hypervolume, or there is no search happening.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# --- dominance ---------------------------------------------------------------
def dominates(a: np.ndarray, b: np.ndarray) -> bool:
    """True if a dominates b (all objectives minimised, at least one strictly)."""
    return bool(np.all(a <= b) and np.any(a < b))


def fast_non_dominated_sort(f: np.ndarray) -> list[np.ndarray]:
    """Partition into fronts. f is [n_individuals, n_objectives], minimised."""
    n = f.shape[0]
    dominated_by = np.zeros(n, dtype=int)
    dominates_list: list[list[int]] = [[] for _ in range(n)]
    fronts: list[list[int]] = [[]]

    for p in range(n):
        for q in range(p + 1, n):
            if dominates(f[p], f[q]):
                dominates_list[p].append(q)
                dominated_by[q] += 1
            elif dominates(f[q], f[p]):
                dominates_list[q].append(p)
                dominated_by[p] += 1
    fronts[0] = [i for i in range(n) if dominated_by[i] == 0]

    i = 0
    while fronts[i]:
        nxt: list[int] = []
        for p in fronts[i]:
            for q in dominates_list[p]:
                dominated_by[q] -= 1
                if dominated_by[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    return [np.asarray(fr, dtype=int) for fr in fronts if len(fr)]


def crowding_distance(f: np.ndarray) -> np.ndarray:
    """Deb's crowding distance within one front."""
    n, m = f.shape
    if n <= 2:
        return np.full(n, np.inf)
    d = np.zeros(n)
    for j in range(m):
        order = np.argsort(f[:, j])
        d[order[0]] = d[order[-1]] = np.inf
        span = f[order[-1], j] - f[order[0], j]
        if span <= 0:
            continue
        d[order[1:-1]] += (f[order[2:], j] - f[order[:-2], j]) / span
    return d


def pareto_front(f: np.ndarray) -> np.ndarray:
    """Indices of the non-dominated set."""
    return fast_non_dominated_sort(f)[0]


# --- hypervolume -------------------------------------------------------------
def hypervolume(f: np.ndarray, reference: np.ndarray,
                ideal: np.ndarray | None = None,
                samples: int = 200_000, seed: int = 0) -> float:
    """Fraction of the box [ideal, reference] dominated by the front.

    The box MUST be fixed across every call being compared. An earlier version
    derived the lower corner from the front itself, so a search that pushed the
    front toward lower objectives enlarged its own box and scored *worse* than a
    search that did nothing -- which made NSGA-II look like it was regressing.

    Exact in two objectives by sweep; Monte Carlo above that.
    """
    if f.size == 0:
        return 0.0
    front = f[pareto_front(f)]
    reference = np.asarray(reference, float)
    ideal = np.zeros_like(reference) if ideal is None else np.asarray(ideal, float)
    span = reference - ideal
    if np.any(span <= 0):
        return 0.0

    # keep only members inside the box
    inside = np.all(front < reference, axis=1) & np.all(front >= ideal, axis=1)
    front = front[inside]
    if front.size == 0:
        return 0.0

    if front.shape[1] == 2:
        order = np.argsort(front[:, 0])
        pts = front[order]
        area, prev_f2 = 0.0, reference[1]
        for f1, f2 in pts:
            if f2 >= prev_f2:
                continue
            area += (reference[0] - f1) * (prev_f2 - f2)
            prev_f2 = f2
        return float(area / (span[0] * span[1]))

    rng = np.random.default_rng(seed)
    pts = ideal + rng.random((samples, f.shape[1])) * span
    covered = np.zeros(samples, dtype=bool)
    for row in front:
        covered |= np.all(pts >= row, axis=1)
    return float(covered.mean())


# --- search ------------------------------------------------------------------
@dataclass
class SearchResult:
    genomes: np.ndarray
    objectives: np.ndarray
    front_index: np.ndarray
    evaluations: int
    history: list[float] = field(default_factory=list)

    @property
    def front(self) -> np.ndarray:
        return self.objectives[self.front_index]


def _sbx(p1, p2, lo, hi, rng, eta=15.0):
    u = rng.random(p1.shape)
    beta = np.where(u <= 0.5, (2 * u) ** (1 / (eta + 1)),
                    (1 / (2 * (1 - u))) ** (1 / (eta + 1)))
    c1 = 0.5 * ((1 + beta) * p1 + (1 - beta) * p2)
    c2 = 0.5 * ((1 - beta) * p1 + (1 + beta) * p2)
    return np.clip(c1, lo, hi), np.clip(c2, lo, hi)


def _polynomial_mutation(x, lo, hi, rng, eta=20.0, prob=None):
    prob = prob if prob is not None else 1.0 / len(x)
    out = x.copy()
    for i in range(len(x)):
        if rng.random() >= prob:
            continue
        span = hi[i] - lo[i]
        if span <= 0:
            continue
        u = rng.random()
        delta = ((2 * u) ** (1 / (eta + 1)) - 1 if u < 0.5
                 else 1 - (2 * (1 - u)) ** (1 / (eta + 1)))
        out[i] = np.clip(x[i] + delta * span, lo[i], hi[i])
    return out


def nsga2(evaluate, lo, hi, pop_size: int = 40, generations: int = 25,
          seed: int = 0, reference: np.ndarray | None = None,
          ideal: np.ndarray | None = None) -> SearchResult:
    """Minimise every objective returned by `evaluate(genomes) -> [n, m]`."""
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    pop = lo + rng.random((pop_size, len(lo))) * (hi - lo)
    obj = evaluate(pop)
    evals = pop_size
    history = []

    for _ in range(generations):
        # --- offspring ---
        fronts = fast_non_dominated_sort(obj)
        rank = np.empty(len(pop), dtype=int)
        crowd = np.empty(len(pop))
        for r, fr in enumerate(fronts):
            rank[fr] = r
            crowd[fr] = crowding_distance(obj[fr])

        def tournament():
            a, b = rng.integers(0, len(pop), 2)
            if rank[a] != rank[b]:
                return a if rank[a] < rank[b] else b
            return a if crowd[a] > crowd[b] else b

        children = []
        while len(children) < pop_size:
            c1, c2 = _sbx(pop[tournament()], pop[tournament()], lo, hi, rng)
            children.append(_polynomial_mutation(c1, lo, hi, rng))
            if len(children) < pop_size:
                children.append(_polynomial_mutation(c2, lo, hi, rng))
        children = np.asarray(children)
        child_obj = evaluate(children)
        evals += len(children)

        # --- environmental selection on the combined pool ---
        pool = np.vstack([pop, children])
        pool_obj = np.vstack([obj, child_obj])
        survivors: list[int] = []
        for fr in fast_non_dominated_sort(pool_obj):
            if len(survivors) + len(fr) <= pop_size:
                survivors.extend(fr.tolist())
            else:
                d = crowding_distance(pool_obj[fr])
                order = fr[np.argsort(-d)]
                survivors.extend(order[:pop_size - len(survivors)].tolist())
                break
        pop, obj = pool[survivors], pool_obj[survivors]
        if reference is not None:
            history.append(hypervolume(obj, reference, ideal, samples=20_000))

    return SearchResult(pop, obj, pareto_front(obj), evals, history)


def random_search(evaluate, lo, hi, evaluations: int, seed: int = 0,
                  reference: np.ndarray | None = None,
                  ideal: np.ndarray | None = None) -> SearchResult:
    """The baseline NSGA-II must beat: what gepa.py actually did."""
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    genomes = lo + rng.random((evaluations, len(lo))) * (hi - lo)
    obj = evaluate(genomes)
    hv = [hypervolume(obj, reference, ideal, samples=20_000)] \
        if reference is not None else []
    return SearchResult(genomes, obj, pareto_front(obj), evaluations, hv)
