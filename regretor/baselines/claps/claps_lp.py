"""CLAPS LPs re-implemented with HiGHS (no PuLP/Clp, no external penalty files).

Mapping to the repo (`weights_optimization.py`, `convert_solution_to_shadow_format.py`):

Counter-RAPTOR-style guard LP (`model_opt_problem` / `model_opt_problem_for_shadow`, obj_function 3):
  variables  R[l, j] >= 0                         for client cluster l, guard-only relay j
  objective  min Σ_l Σ_j W_l R[l, j] P[l, j]                       (obj 3)
  (2)        Σ_j R[l, j] = G·Wgg                   for every l     ("\\sum R(i) == G*Wgg")
  (3)        L(j) = Σ_l W_l R[l, j] <= BW_j        for every j     ("L(i) <= BW_i")
  (4)        R[l, j] <= θ·BW_j·Wgg                                 (GPA / θ constraint)
  (5)        Σ_j R[l, j] P[l, j] <= V_l·G·Wgg      for every l     (no worse than vanilla)
  with Wgg = SWgg = (E+D)/G unless disable_SWgg (repo default uses SWgg).
  Repo difference: (5) is written with RHS V_l·G there although Σ_j R = G·Wgg; we use the scale-
  consistent RHS (``vanilla_rhs="consistent"``) and keep the repo form as ``vanilla_rhs="repo"``.
  Derived middle weights (compute_claps_g_weights): guard j offers BW_j − L(j) at the middle
  position; other relays keep the vanilla middle weights.

DeNASA-GE exit LP (`model_opt_problem_for_denasa_exit`):
  variables  R[l, e] >= 0 over exit relays; Σ_e R[l, e] = exit-position total; LE(e) = Σ_l W_l R[l, e]
  <= BW_e; R[l, e] <= θ·BW_e; objective Σ W_l R[l, e] P[l, e]. The repo keys rows by (client cluster,
  guard AS); we key them by client cluster only to keep the LP tractable (documented deviation).
"""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog


def guard_lp(W, P, BW, Wgg, theta, vanilla_rhs="consistent"):
    """W: (L,) cluster densities; P: (L, J) penalties; BW: (J,) guard consensus weights."""
    L, J = P.shape
    G = BW.sum()
    tot = G * Wgg
    n = L * J
    c = (W[:, None] * P).ravel()
    # equality: Σ_j R[l, j] = G·Wgg
    A_eq = sparse.kron(sparse.eye(L), np.ones((1, J)), format="csr")
    b_eq = np.full(L, tot)
    # L(j) <= BW_j
    A1 = sparse.kron(W[None, :], sparse.eye(J), format="csr")
    b1 = BW.copy()
    # no worse than vanilla: Σ_j R[l, j] P[l, j] <= V_l·G·Wgg, V_l = Σ_j (BW_j/G) P[l, j]
    V = P @ (BW / G)
    rows = np.repeat(np.arange(L), J)
    A2 = sparse.csr_matrix((P.ravel(), (rows, np.arange(n))), shape=(L, n))
    b2 = V * (tot if vanilla_rhs == "consistent" else G)
    A_ub = sparse.vstack([A1, A2], format="csr")
    b_ub = np.concatenate([b1, b2])
    ub = np.tile(theta * BW * Wgg, L)
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=np.column_stack([np.zeros(n), ub]),
                  method="highs")
    if res.status != 0:
        return None, res
    R = np.maximum(res.x.reshape(L, J), 0.0)
    return R, res


def exit_lp(W, P, BW, total, theta):
    L, J = P.shape
    n = L * J
    c = (W[:, None] * P).ravel()
    A_eq = sparse.kron(sparse.eye(L), np.ones((1, J)), format="csr")
    b_eq = np.full(L, total)
    A_ub = sparse.kron(W[None, :], sparse.eye(J), format="csr")
    b_ub = BW.copy()
    ub = np.tile(theta * BW, L)
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=np.column_stack([np.zeros(n), ub]),
                  method="highs")
    if res.status != 0:
        return None, res
    return np.maximum(res.x.reshape(L, J), 0.0), res
