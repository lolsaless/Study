# -*- coding: utf-8 -*-
"""
결과 저장: results/<스크립트명>/summary.md + CSV + figures/ + findings.json + meta.json

v2 대비 개선
- rep.finding("…")  : 핵심 결과 한 줄을 따로 모은다 → 90번이 전체 '핵심 결과 요약'을 자동으로 만든다
- rep.wait("…")     : 필요한 자료가 없을 때 '자료 대기' 보고서를 남기고 정상 종료(run_all 이 멈추지 않음)
- meta.json         : 실행 시각, 입력 자료 기간·크기, 주요 설정값 기록(재현성)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)
pd.set_option("display.width", 200)

BASIN_COLORS = {"한강": "#2a6fdb", "낙동강": "#d1495b", "금강": "#edae49", "영산강": "#00798c"}


def _set_font():
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ["Malgun Gothic", "AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"]:
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["savefig.dpi"] = C.FIG_DPI


_set_font()


def _fmt(v, digits=3):
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
    head = d.head(max_rows)
    lines = ["| " + " | ".join(str(c) for c in head.columns) + " |", "|" + "---|" * len(head.columns)]
    for row in head.itertuples(index=False):
        lines.append("| " + " | ".join(_fmt(v, digits) for v in row) + " |")
    if len(d) > max_rows:
        lines.append(f"\n_(상위 {max_rows}행만 표시 · 전체 {len(d):,}행은 CSV 참조)_")
    return "\n".join(lines) + "\n"


class Report:
    def __init__(self, name, title, purpose="", level=""):
        self.name, self.title = name, title
        self.dir = C.RESULTS_DIR / name
        (self.dir / "figures").mkdir(parents=True, exist_ok=True)
        for old in list((self.dir / "figures").glob("*.png")) + list(self.dir.glob("*.csv")):
            old.unlink()                                  # 지난 실행의 결과가 섞이지 않게
        self.findings, self.meta = [], {"script": f"{name}.py", "run_at": f"{pd.Timestamp.now():%Y-%m-%d %H:%M}",
                                        "level": level}
        self.lines = [f"# {title}", "", f"- 스크립트: `{name}.py`" + (f"  ·  단계: {level}" if level else ""),
                      f"- 실행 시각: {self.meta['run_at']}", ""]
        if purpose:
            self.lines += ["## 목적", "", purpose, ""]
        self._finding_pos = len(self.lines)

    # 기록 ------------------------------------------------------------
    def h(self, text):
        self.lines += [f"## {text}", ""]

    def p(self, text):
        self.lines += [text, ""]

    def kv(self, d):
        self.lines += [f"- {k}: {_fmt(v)}" for k, v in d.items()] + [""]

    def table(self, df, title=None, max_rows=C.MD_MAX_ROWS, digits=3, index=False):
        if title:
            self.lines += [f"### {title}", ""]
        self.lines.append(md_table(df, max_rows, digits, index))

    def csv(self, df, fname, index=False):
        df.to_csv(self.dir / fname, index=index, encoding="utf-8-sig")
        self.lines += [f"- 전체 표: `{fname}` ({len(df):,}행)", ""]

    def fig(self, fig, fname, caption=""):
        fig.savefig(self.dir / "figures" / fname, bbox_inches="tight")
        plt.close(fig)
        self.lines += [f"- 그림: `figures/{fname}`" + (f" — {caption}" if caption else ""), ""]

    def finding(self, text):
        """핵심 결과 한 줄(숫자 포함). summary.md 맨 위와 90번 전체 요약에 모인다"""
        self.findings.append(text)

    def data_info(self, df, label="입력 자료"):
        if df is None or not len(df):
            return
        info = {"행 수": len(df)}
        if "date" in df:
            info["기간"] = f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}"
        if "station" in df:
            info["측정소 수"] = df["station"].nunique()
        self.meta[label] = {k: str(v) for k, v in info.items()}
        self.lines += [f"**{label}**: " + " · ".join(f"{k} {_fmt(v) if not isinstance(v, str) else v}" for k, v in info.items()), ""]

    # 종료 ------------------------------------------------------------
    def wait(self, msg, need=None):
        """필요 자료가 없을 때: 무엇이 필요한지 남기고 끝낸다"""
        self.meta["status"] = "자료 대기"
        self.lines += ["## ⏳ 자료 대기", "", msg, ""]
        if need:
            self.lines += ["필요한 자료(자료요구서.md 참고):", ""] + [f"- {x}" for x in need] + [""]
        return self.save()

    def save(self):
        self.meta.setdefault("status", "완료")
        if self.findings:
            block = ["## 핵심 결과", ""] + [f"- {t}" for t in self.findings] + [""]
            self.lines[self._finding_pos:self._finding_pos] = block
        (self.dir / "summary.md").write_text("\n".join(self.lines), encoding="utf-8")
        (self.dir / "findings.json").write_text(json.dumps({"title": self.title, "status": self.meta["status"],
                                                            "findings": self.findings}, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
        cfg = {k: getattr(C, k) for k in ["MIN_HOURS", "MIN_DAYS", "ROLL_WIN", "ANOMALY_Z", "BLOOM_CHLA", "TARGET_GRADE"]}
        self.meta["config"] = cfg
        (self.dir / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"[완료] {self.dir / 'summary.md'}  (핵심 결과 {len(self.findings)}개, 상태: {self.meta['status']})")
        return self.dir / "summary.md"


def pct(x, d=1):
    return f"{x * 100:.{d}f}%" if pd.notna(x) else "-"


def fmt(x, d=3):
    return _fmt(x, d)
