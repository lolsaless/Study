# -*- coding: utf-8 -*-
"""
공통 함수: 데이터 불러오기, 결과 저장(summary.md / CSV / 그림), 시계열 도우미
모든 분석 스크립트가 이 파일을 import 합니다.
"""
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config as C

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
pd.set_option("display.width", 200)


# ── 한글 글꼴 ────────────────────────────────────────────
def _set_korean_font():
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"]:
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 100
    plt.rcParams["savefig.dpi"] = C.FIG_DPI


_set_korean_font()


# ── 데이터 ───────────────────────────────────────────────
def load_clean(types="default"):
    """01_preprocess.py 가 만든 정제 데이터를 불러온다.
    types="default" → config.FOCUS_TYPES, None → 전체, 리스트 → 해당 유형만"""
    if not C.CLEAN_PKL.exists():
        raise FileNotFoundError(f"{C.CLEAN_PKL} 이 없습니다. 먼저 01_preprocess.py 를 실행하세요.")
    df = pd.read_pickle(C.CLEAN_PKL)
    if types == "default":
        types = C.FOCUS_TYPES
    if types:
        df = df[df["site_type"].isin(types)].copy()
    return df


def valid_sids(df, col="TN", min_days=C.MIN_DAYS):
    """유효일수가 min_days 이상인 방류구(sid) 목록"""
    cnt = df.dropna(subset=[col]).groupby("sid").size()
    return cnt[cnt >= min_days].index.tolist()


def daily(g, col):
    """한 방류구 그룹(g)에서 col 을 일 단위 연속 시계열로 반환(빈 날은 NaN)"""
    s = g.set_index("date")[col].sort_index()
    s = s[~s.index.duplicated()]
    return s.asfreq("D")


def wide(df, col, sids=None):
    """행=날짜, 열=sid 인 넓은 표"""
    d = df if sids is None else df[df["sid"].isin(sids)]
    return d.pivot_table(index="date", columns="sid", values=col, aggfunc="first").sort_index().asfreq("D")


def anomaly(s, win=C.ROLL_WIN, log=True):
    """계절·추세를 이동 중앙값으로 제거한 일 편차(로그 기준이면 비율 편차)"""
    x = np.log(s.where(s > 0)) if log else s
    base = x.rolling(win, center=True, min_periods=max(5, win // 3)).median()
    return x - base


def robust_z(x):
    x = pd.Series(x, dtype=float)
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    if not mad or np.isnan(mad):
        return x * np.nan
    return (x - med) / mad


def size_class(q):
    return pd.cut(q, bins=C.SIZE_BINS, labels=C.SIZE_LABELS, right=False)


def fdr(pvals):
    """Benjamini-Hochberg 보정 q-value"""
    p = np.asarray(pvals, dtype=float)
    out = np.full_like(p, np.nan)
    m = ~np.isnan(p)
    if m.sum() == 0:
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


def holiday_index():
    return pd.to_datetime(pd.Series(C.HOLIDAYS)).dt.normalize().unique()


# ── 결과 저장 ────────────────────────────────────────────
def _fmt(v, digits):
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return ""
        a = abs(v)
        if a != 0 and (a < 0.001 or a >= 1e7):
            return f"{v:.3g}"
        s = f"{v:,.{digits}f}"
        return s.rstrip("0").rstrip(".") if "." in s else s
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return str(v).replace("|", "/").replace("\n", " ")


def md_table(df, max_rows=C.MD_MAX_ROWS, digits=3, index=False):
    if df is None or len(df) == 0:
        return "_(결과 없음)_\n"
    d = df.reset_index() if index else df
    d = d.head(max_rows)
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(_fmt(v, digits) for v in row) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_(상위 {max_rows}행만 표시 · 전체 {len(df):,}행은 CSV 참조)_")
    return "\n".join(lines) + "\n"


class Report:
    """results/<name>/summary.md 를 만든다. Claude가 읽기 쉬운 고정 형식."""

    def __init__(self, name, title, purpose=""):
        self.name = name
        self.dir = C.RESULTS_DIR / name
        (self.dir / "figures").mkdir(parents=True, exist_ok=True)
        self.lines = [f"# {title}", "",
                      f"- 스크립트: `{name}.py`",
                      f"- 실행 시각: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
                      f"- 분석 대상 유형: {C.FOCUS_TYPES if C.FOCUS_TYPES else '전체'}", ""]
        if purpose:
            self.lines += ["## 목적", "", purpose, ""]

    def h(self, text):
        self.lines += [f"## {text}", ""]

    def p(self, text):
        self.lines += [text, ""]

    def kv(self, d):
        for k, v in d.items():
            self.lines.append(f"- {k}: {_fmt(v, 3)}")
        self.lines.append("")

    def table(self, df, title=None, max_rows=C.MD_MAX_ROWS, digits=3, index=False):
        if title:
            self.lines += [f"### {title}", ""]
        self.lines.append(md_table(df, max_rows, digits, index))

    def csv(self, df, fname, index=False):
        df.to_csv(self.dir / fname, index=index, encoding="utf-8-sig")
        self.lines += [f"- 전체 표 저장: `{fname}` ({len(df):,}행)", ""]

    def fig(self, fig, fname, caption=""):
        fig.savefig(self.dir / "figures" / fname, bbox_inches="tight")
        plt.close(fig)
        self.lines += [f"- 그림: `figures/{fname}`" + (f" — {caption}" if caption else ""), ""]

    def save(self):
        path = self.dir / "summary.md"
        path.write_text("\n".join(self.lines), encoding="utf-8")
        print(f"[완료] {path}")
        return path


@lru_cache(maxsize=None)
def need(pkg, pip_name=None):
    """선택 패키지 확인. 없으면 None 반환하고 안내 출력"""
    try:
        return __import__(pkg)
    except ImportError:
        print(f"[안내] '{pip_name or pkg}' 가 없어 일부 분석을 건너뜁니다. 설치: pip install {pip_name or pkg}")
        return None
