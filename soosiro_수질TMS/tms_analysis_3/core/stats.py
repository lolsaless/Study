# -*- coding: utf-8 -*-
"""
공통 통계 함수 — 여러 분석에서 반복되는 계산을 한곳에 둔다(검증된 한 가지 구현만 쓰기 위함).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402


# ── 기본 ────────────────────────────────────────────────
def robust_z(x):
    x = pd.Series(x, dtype=float)
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    if not mad or np.isnan(mad):
        return x * np.nan
    return (x - med) / mad


def fdr(pvals):
    """Benjamini–Hochberg q-value"""
    p = np.asarray(pvals, dtype=float)
    out = np.full_like(p, np.nan)
    m = ~np.isnan(p)
    if not m.any():
        return out
    pv = p[m]
    n = len(pv)
    order = np.argsort(pv)
    ranked = pv[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(n)
    q[order] = np.clip(ranked, 0, 1)
    out[m] = q
    return out


def to_log(s, var):
    s = pd.Series(s, dtype=float)
    if var in C.LOG_VARS:
        pos = s[s > 0]
        floor = pos.quantile(0.01) / 2 if len(pos) else 1e-3
        return np.log(s.clip(lower=floor))
    return s


def deseason(s, var=None, win=C.ROLL_WIN):
    """이동 중앙값으로 계절·추세를 뺀 편차(로그 항목은 비율 편차). 입력은 연속 일 시계열"""
    x = to_log(s, var) if var else pd.Series(s, dtype=float)
    base = x.rolling(win, center=True, min_periods=max(5, win // 3)).median()
    return x - base


# ── 효과크기·비모수 검정 ────────────────────────────────
def hodges_lehmann(a, b):
    """두 표본 위치 차이의 HL 추정값(b - a 의 중앙값)"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return np.nan
    if len(a) * len(b) > 4e6:
        rng = np.random.default_rng(C.RANDOM_STATE)
        a = rng.choice(a, 2000, replace=False) if len(a) > 2000 else a
        b = rng.choice(b, 2000, replace=False) if len(b) > 2000 else b
    return float(np.median(np.subtract.outer(b, a)))


def cliffs_delta(a, b):
    """Cliff's δ (b>a 쪽 양수). |δ|<0.147 무시, <0.33 작음, <0.474 중간, 그 이상 큼"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return np.nan
    allv = np.concatenate([a, b])
    r = stats.rankdata(allv)
    ra = r[:len(a)].sum()
    u_a = ra - len(a) * (len(a) + 1) / 2
    return float(1 - 2 * u_a / (len(a) * len(b)))


def kruskal_dunn(groups: dict):
    """Kruskal–Wallis + Dunn 사후검정(Holm 보정) + ε² 효과크기
    groups: {이름: 값 배열} → (H, p, eps2, 쌍별 DataFrame)"""
    g = {k: np.asarray(v, float)[~np.isnan(np.asarray(v, float))] for k, v in groups.items()}
    g = {k: v for k, v in g.items() if len(v) >= 3}
    if len(g) < 2:
        return np.nan, np.nan, np.nan, pd.DataFrame()
    H, p = stats.kruskal(*g.values())
    N = sum(len(v) for v in g.values())
    eps2 = (H - len(g) + 1) / (N - len(g))
    allv = np.concatenate(list(g.values()))
    ranks = stats.rankdata(allv)
    _, cnt = np.unique(allv, return_counts=True)
    tie = 1 - (cnt ** 3 - cnt).sum() / (N ** 3 - N)
    mean_r, i = {}, 0
    for k, v in g.items():
        mean_r[k] = ranks[i:i + len(v)].mean()
        i += len(v)
    rows = []
    keys = list(g)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            se = np.sqrt(tie * N * (N + 1) / 12 * (1 / len(g[ka]) + 1 / len(g[kb])))
            z = (mean_r[ka] - mean_r[kb]) / se
            rows.append({"A": ka, "B": kb, "z": z, "p": 2 * stats.norm.sf(abs(z)),
                         "중앙값A": np.median(g[ka]), "중앙값B": np.median(g[kb]),
                         "cliffs_delta(B-A)": cliffs_delta(g[ka], g[kb])})
    d = pd.DataFrame(rows)
    if len(d):
        order = np.argsort(d["p"].values)
        m = len(d)
        adj = np.empty(m)
        run = 0
        for rank, idx in enumerate(order):
            run = max(run, min(1, d["p"].values[idx] * (m - rank)))
            adj[idx] = run
        d["p_holm"] = adj
    return H, p, eps2, d


# ── 부트스트랩 ───────────────────────────────────────────
def block_bootstrap(x, func=np.nanmean, block=14, n=C.N_BOOT, seed=C.RANDOM_STATE):
    """이동 블록 부트스트랩(자기상관 있는 일자료용). 반환: 반복 통계량 배열"""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < block * 2:
        return np.array([])
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block))
    starts = rng.integers(0, len(x) - block + 1, size=(n, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n, -1)[:, :len(x)]
    return np.array([func(x[i]) for i in idx])


# ── 추세 ────────────────────────────────────────────────
def seasonal_mk(monthly: pd.Series):
    """계절 Mann–Kendall(월 자료) → (p, Sen 기울기[단위/년], 방향)"""
    try:
        import pymannkendall as pmk
        r = pmk.seasonal_test(monthly.values.astype(float), period=12)
        return r.p, r.slope, r.trend
    except Exception:  # noqa: BLE001
        pass
    months = monthly.index.month
    S, varS, slopes = 0.0, 0.0, []
    for m in range(1, 13):
        y = monthly[months == m].dropna()
        n = len(y)
        if n < 2:
            continue
        v = y.values
        for i in range(n - 1):
            for j in range(i + 1, n):
                S += np.sign(v[j] - v[i])
                dy = y.index[j].year - y.index[i].year
                if dy:
                    slopes.append((v[j] - v[i]) / dy)
        varS += n * (n - 1) * (2 * n + 5) / 18
    if varS == 0:
        return np.nan, np.nan, "no trend"
    z = (S - np.sign(S)) / np.sqrt(varS)
    p = 2 * stats.norm.sf(abs(z))
    return p, (np.median(slopes) if slopes else np.nan), ("increasing" if z > 0 else "decreasing") if p < 0.05 else "no trend"


# ── 시계열 구조 ─────────────────────────────────────────
def acf(x, nlags=60):
    x = pd.Series(x, dtype=float)
    return np.array([x.autocorr(k) for k in range(nlags + 1)])


def efold_time(x, nlags=120):
    """자기상관이 1/e 아래로 처음 떨어지는 시차(일) = 기억 길이"""
    a = acf(x, nlags)
    below = np.where(a < 1 / np.e)[0]
    return float(below[0]) if len(below) else np.nan


def dfa_hurst(x, min_win=8, max_win=None):
    """Detrended Fluctuation Analysis 지수 α (0.5 무작위, >0.5 장기기억, ~1 1/f 잡음)"""
    x = pd.Series(x, dtype=float).interpolate(limit=3).dropna().values
    if len(x) < 100:
        return np.nan
    y = np.cumsum(x - x.mean())
    max_win = max_win or len(x) // 4
    wins = np.unique(np.logspace(np.log10(min_win), np.log10(max_win), 15).astype(int))
    F = []
    for w in wins:
        nseg = len(y) // w
        if nseg < 2:
            continue
        seg = y[:nseg * w].reshape(nseg, w)
        t = np.arange(w)
        res = []
        for s in seg:
            c = np.polyfit(t, s, 1)
            res.append(np.mean((s - np.polyval(c, t)) ** 2))
        F.append((w, np.sqrt(np.mean(res))))
    if len(F) < 4:
        return np.nan
    F = np.array(F)
    return float(np.polyfit(np.log(F[:, 0]), np.log(F[:, 1]), 1)[0])


def prewhiten(x):
    """AR(1) 성분 제거(교차상관의 허위 상관 방지)"""
    x = pd.Series(x, dtype=float)
    phi = x.autocorr(1)
    if np.isnan(phi):
        return x
    return x - phi * x.shift(1)


def ccf_best_lag(x, y, max_lag=5):
    """x 가 y 를 몇 일 앞서는지: corr(x_t, y_{t+lag}) 가 최대인 lag 와 r"""
    best = (np.nan, np.nan)
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        r = pd.concat([x, y.shift(-lag)], axis=1).dropna().corr().iloc[0, 1]
        rows.append((lag, r))
        if np.isnan(best[1]) or (not np.isnan(r) and r > best[1]):
            best = (lag, r)
    return best[0], best[1], rows


# ── 회귀 도우미 ─────────────────────────────────────────
def piecewise_fit(x, y, grid=None):
    """꺾인선(1개 꺾임점) 회귀: 격자 탐색 → (꺾임점, 기울기1, 기울기2, R², 단순회귀 대비 F 검정 p)"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    if len(x) < 30:
        return None
    grid = grid if grid is not None else np.quantile(x, np.linspace(0.15, 0.85, 36))
    best = None
    for k in grid:
        X = np.column_stack([np.ones_like(x), x, np.maximum(x - k, 0)])
        beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        sse = float(((y - X @ beta) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, k, beta)
    sse1, k, beta = best
    X0 = np.column_stack([np.ones_like(x), x])
    b0 = np.linalg.lstsq(X0, y, rcond=None)[0]
    sse0 = float(((y - X0 @ b0) ** 2).sum())
    n = len(x)
    F = ((sse0 - sse1) / 2) / (sse1 / (n - 4))     # 꺾임점 탐색 자유도 1 포함
    p = stats.f.sf(F, 2, n - 4)
    r2 = 1 - sse1 / ((y - y.mean()) ** 2).sum()
    return {"break": k, "slope_below": beta[1], "slope_above": beta[1] + beta[2], "r2": r2, "p_vs_linear": p, "n": n}


def circular_peak(doy, weights=None):
    """연중 최고 시기(원형 통계): 평균 방향(일), 집중도 R(0~1), Rayleigh p"""
    th = 2 * np.pi * (np.asarray(doy, float) - 1) / 365.25
    w = np.ones_like(th) if weights is None else np.asarray(weights, float)
    m = ~(np.isnan(th) | np.isnan(w))
    th, w = th[m], w[m]
    if len(th) < 5 or w.sum() <= 0:
        return np.nan, np.nan, np.nan
    Cs, Sn = (w * np.cos(th)).sum() / w.sum(), (w * np.sin(th)).sum() / w.sum()
    R = np.hypot(Cs, Sn)
    mean_doy = (np.arctan2(Sn, Cs) % (2 * np.pi)) * 365.25 / (2 * np.pi) + 1
    n_eff = w.sum() ** 2 / (w ** 2).sum()
    Z = n_eff * R ** 2
    p = np.exp(-Z) * (1 + (2 * Z - Z ** 2) / (4 * n_eff))
    return mean_doy, R, float(np.clip(p, 0, 1))
