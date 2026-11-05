# -*- coding: utf-8 -*-
"""
01. 전처리 및 데이터셋 개요
- 원자료(tms_all_raw.csv) → 정제 데이터(work/tms_clean.pkl)
- 날짜 변환, 숫자 변환, 중복 제거, 0값·이상 pH 결측 처리, 유량 역산, 사업장 유형·시군 부여
- 이후 모든 스크립트는 이 파일의 산출물을 사용합니다. 가장 먼저 1회 실행하세요.
"""
import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import config as C
from common import Report


def site_type(name: str) -> str:
    if "하수" in name:
        return "하수"
    if "폐수" in name:
        return "폐수"
    if "정수" in name:
        return "정수"
    return "산업·기타"


def clean_name(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"^\s*\[폐쇄\]\s*", "", regex=True).str.strip()


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def extract_sigun(addr: str):
    if not isinstance(addr, str):
        return np.nan
    toks = re.split(r"\s+", addr.strip())
    for t in toks[1:4]:
        if re.search(r"(시|군)$", t) and not t.startswith("경기"):
            return "여주시" if t == "여주군" else t
    return np.nan


def main():
    rep = Report("01_preprocess", "01. 전처리 및 데이터셋 개요",
                 "원자료를 분석 가능한 형태로 정리하고, 자료 범위·결측·중복·유량 역산 가능성을 요약한다.")

    raw = pd.read_csv(C.RAW_CSV, encoding="utf-8-sig", dtype=str)
    n_raw = len(raw)

    ren = {"사업장명": "site", "방류구": "outlet", "연도": "year", "분기": "quarter",
           "일자": "mmdd", "pH_측정값": "pH"}
    for p in C.PARAMS:
        ren[f"{p}_측정값"] = p
        ren[f"{p}_배출량"] = f"{p}_load"
    df = raw.rename(columns=ren)
    df = df[[c for c in ren.values() if c in df.columns]].copy()

    # ── 기본 변환 ──
    df["site"] = clean_name(df["site"])
    df["outlet"] = to_num(df["outlet"]).astype("Int64")
    df["year"] = to_num(df["year"]).astype("Int64")
    md = df["mmdd"].astype(str).str.extract(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
    date_str = df["year"].astype(str) + "-" + md[0].str.zfill(2) + "-" + md[1].str.zfill(2)
    df["date"] = pd.to_datetime(date_str, format="%Y-%m-%d", errors="coerce")
    n_bad_date = int(df["date"].isna().sum())
    df = df.dropna(subset=["date", "outlet"])

    num_cols = ["pH"] + C.PARAMS + [f"{p}_load" for p in C.PARAMS]
    for c in num_cols:
        df[c] = to_num(df[c])

    # ── 중복 ──
    key = ["site", "outlet", "date"]
    dup_any = df.duplicated(key, keep=False)
    dup_rows = df[dup_any]
    conflict = (dup_rows.groupby(key)[num_cols].nunique(dropna=False) > 1).any(axis=1)
    n_dup_extra = int(df.duplicated(key).sum())
    n_dup_conflict = int(conflict.sum())
    dup_by_site = (df[df.duplicated(key)].groupby("site").size()
                   .sort_values(ascending=False).rename("중복행수").reset_index())
    df = df.drop_duplicates(key, keep="first").copy()

    # ── 0값·음수·pH ──
    conc0 = pd.DataFrame({p: df[p] == 0 for p in C.PARAMS})
    df["all_zero"] = conc0.all(axis=1)
    for p in C.PARAMS:
        df[f"zero_{p}"] = (df[p] == 0)
        if C.ZERO_AS_MISSING:
            m = (df[p] == 0)
            df.loc[m, [p, f"{p}_load"]] = np.nan
        df.loc[df[p] < 0, p] = np.nan
        df.loc[df[f"{p}_load"] < 0, f"{p}_load"] = np.nan
    df.loc[df["all_zero"], "pH"] = np.nan
    lo, hi = C.PH_VALID_RANGE
    n_bad_ph = int(((df["pH"] < lo) | (df["pH"] > hi)).sum())
    df.loc[(df["pH"] < lo) | (df["pH"] > hi), "pH"] = np.nan

    # ── 유량 역산 ──
    for p in C.PARAMS:
        ok = (df[p] >= C.MIN_CONC_FOR_FLOW[p]) & (df[f"{p}_load"] > 0)
        df[f"Q_{p}"] = np.where(ok, df[f"{p}_load"] / df[p] * 1000.0, np.nan)
    df["Q"] = np.nan
    df["Q_src"] = ""
    for p in C.FLOW_PRIORITY:
        m = df["Q"].isna() & df[f"Q_{p}"].notna()
        df.loc[m, "Q"] = df.loc[m, f"Q_{p}"]
        df.loc[m, "Q_src"] = p
    df["Q_gap_TN_TOC"] = (df["Q_TN"] - df["Q_TOC"]).abs() / df[["Q_TN", "Q_TOC"]].mean(axis=1)

    # ── 파생 변수 ──
    df["site_type"] = df["site"].map(site_type)
    df["sid"] = df["site"] + "#" + df["outlet"].astype(str)
    df["month"] = df["date"].dt.month
    df["dow"] = df["date"].dt.dayofweek          # 0=월 … 6=일
    df["doy"] = df["date"].dt.dayofyear
    df["ym"] = df["date"].dt.to_period("M").astype(str)
    hol = set(pd.to_datetime(C.HOLIDAYS))
    df["is_holiday"] = df["date"].isin(hol)
    df["is_offday"] = df["is_holiday"] | (df["dow"] >= 5)

    # ── 사업장 코드·시군 ──
    if C.SITE_LIST_CSV.exists():
        sl = pd.read_csv(C.SITE_LIST_CSV, encoding="utf-8-sig", dtype=str)
        sl["site"] = clean_name(sl["site_name"])
        code = sl.drop_duplicates("site").set_index("site")["value"]
        df["code"] = df["site"].map(code)
        df["code_group"] = df["code"].str[2]
    if C.LOCATION_CSV.exists():
        loc = pd.read_csv(C.LOCATION_CSV, encoding="utf-8-sig", dtype=str)
        loc.columns = [c.strip() for c in loc.columns]
        loc["site"] = clean_name(loc.iloc[:, 0])
        loc["sigun"] = loc.iloc[:, 1].map(extract_sigun)
        df["sigun"] = df["site"].map(loc.drop_duplicates("site").set_index("site")["sigun"])
        df["address"] = df["site"].map(loc.drop_duplicates("site").set_index("site").iloc[:, 1])
    else:
        df["sigun"] = np.nan

    # ── 방류구 지역(방류수 기준) ──
    if C.REGION_MAP_CSV.exists():
        rg = pd.read_csv(C.REGION_MAP_CSV, encoding="utf-8-sig", dtype=str)
        df["region"] = df["site"].map(rg.set_index(rg.columns[0])[rg.columns[1]])
    else:
        df["region"] = np.nan

    df = df.sort_values(["site", "outlet", "date"]).reset_index(drop=True)
    C.WORK_DIR.mkdir(parents=True, exist_ok=True)
    df.to_pickle(C.CLEAN_PKL)

    # ───────────────── 보고서 ─────────────────
    rep.h("1. 자료 범위")
    rep.kv({
        "원자료 행수": n_raw,
        "정제 후 행수": len(df),
        "날짜 변환 실패 행": n_bad_date,
        "사업장 수": df["site"].nunique(),
        "방류구(sid) 수": df["sid"].nunique(),
        "기간": f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}",
        "중복 제거 행(같은 사업장·방류구·날짜)": n_dup_extra,
        "그중 값이 서로 다른 중복": n_dup_conflict,
        "전 항목 0인 행(결측 처리)": int(df["all_zero"].sum()),
        "pH 범위 밖 행(결측 처리)": n_bad_ph,
    })

    t = (df.groupby("site_type")
           .agg(사업장수=("site", "nunique"), 방류구수=("sid", "nunique"), 행수=("sid", "size"))
           .reset_index().sort_values("행수", ascending=False))
    rep.table(t, "사업장 유형별 규모")

    ob = df.groupby("site")["outlet"].nunique().value_counts().sort_index().rename_axis("방류구 개수").reset_index(name="사업장 수")
    rep.table(ob, "사업장당 방류구 개수 분포")

    rep.h("2. 결측과 중복")
    miss = pd.DataFrame({
        "항목": ["pH"] + C.PARAMS + ["Q(역산)"],
        "결측률(%)": [df["pH"].isna().mean() * 100] + [df[p].isna().mean() * 100 for p in C.PARAMS] + [df["Q"].isna().mean() * 100],
        "0값 비율(%)": [np.nan] + [df[f"zero_{p}"].mean() * 100 for p in C.PARAMS] + [np.nan],
    })
    rep.table(miss, "항목별 결측률(정제 후)")
    rep.table(dup_by_site, "중복행이 많은 사업장", max_rows=20)

    # 분기별 행수(수집 완결성)
    df["yq"] = df["date"].dt.to_period("Q").astype(str)
    yq = df.groupby(["yq", "site_type"])["sid"].nunique().unstack(fill_value=0).reset_index()
    rep.table(yq, "분기별 자료가 있는 방류구 수")

    if C.FAILED_LOG.exists():
        rows = []
        for line in C.FAILED_LOG.read_text(encoding="utf-8").splitlines():
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 3:
                rows.append(parts[:3])
        fl = pd.DataFrame(rows, columns=["분기", "사업장", "사유"])
        fl_sum = fl.groupby("사업장").agg(실패분기수=("분기", "size"),
                                         분기목록=("분기", lambda x: ",".join(x))).reset_index()
        rep.table(fl_sum.sort_values("실패분기수", ascending=False), "수집 실패(빈 결과) 사업장")

    rep.h("3. 유량 역산 점검")
    rep.p("Q = 배출량 ÷ 농도 × 1000 (m3/일). TN 우선, 없으면 TOC→SS→TP 순으로 사용. "
          "TN과 TOC로 구한 유량의 상대차이가 작을수록 배출량이 '유량×농도'로 계산된 값임을 뜻한다.")
    qs = df.groupby("site_type").agg(
        Q유효비율_pct=("Q", lambda x: x.notna().mean() * 100),
        TN_TOC_상대차_중앙=("Q_gap_TN_TOC", "median"),
        TN_TOC_상대차_p95=("Q_gap_TN_TOC", lambda x: x.quantile(0.95)),
    ).reset_index()
    rep.table(qs, "유형별 유량 역산 가능성")
    src = df["Q_src"].replace("", "역산불가").value_counts().rename_axis("역산 기준 항목").reset_index(name="행수")
    rep.table(src, "유량 역산에 쓰인 항목")

    gap_site = (df.groupby("sid").agg(유형=("site_type", "first"), 상대차_중앙=("Q_gap_TN_TOC", "median"),
                                      Q중앙=("Q", "median"), 유효일=("Q", "count"))
                  .reset_index().sort_values("상대차_중앙", ascending=False))
    rep.table(gap_site.head(25), "TN·TOC 역산 유량이 크게 어긋나는 방류구(상위 25)")
    rep.csv(gap_site, "flow_consistency_by_sid.csv")

    rep.h("4. 방류구별 자료 보유 현황")
    cov = (df.groupby("sid").agg(사업장=("site", "first"), 방류구=("outlet", "first"), 유형=("site_type", "first"),
                                시군=("sigun", "first"), 시작=("date", "min"), 끝=("date", "max"),
                                행수=("date", "size"), TN유효=("TN", "count"), Q유효=("Q", "count"),
                                Q중앙=("Q", "median"))
             .reset_index())
    span = (cov["끝"] - cov["시작"]).dt.days + 1
    cov["보유율_pct"] = cov["TN유효"] / span * 100
    cov["규모"] = pd.cut(cov["Q중앙"], bins=C.SIZE_BINS, labels=C.SIZE_LABELS, right=False).astype(str)
    rep.table(cov.groupby(["유형", "규모"]).size().unstack(fill_value=0).reset_index(), "유형 × 규모(역산 유량 중앙값) 방류구 수")
    rep.table(cov.sort_values("보유율_pct").head(30), "보유율이 낮은 방류구(하위 30)")
    rep.csv(cov, "coverage_by_sid.csv")
    rep.kv({f"시계열 분석 가능 방류구(TN 유효 {C.MIN_DAYS}일 이상)": int((cov["TN유효"] >= C.MIN_DAYS).sum()),
            "그중 하수": int(((cov["TN유효"] >= C.MIN_DAYS) & (cov["유형"] == "하수")).sum())})
    if df["sigun"].notna().any():
        sg = df.groupby("sigun").agg(사업장수=("site", "nunique"), 방류구수=("sid", "nunique")).reset_index()
        rep.table(sg.sort_values("방류구수", ascending=False), "시군별 사업장 수")
    else:
        rep.p("시군 정보 없음: data/tms_location.csv(사업소,소재지)를 넣으면 시군이 붙습니다.")

    rep.save()


if __name__ == "__main__":
    main()
