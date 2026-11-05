# -*- coding: utf-8 -*-
"""
21. 기상자료 결합(기상청 ASOS·AWS 일자료 → 처리장별 일 강수·기온)
- data/weather/ 폴더의 기상청 CSV 를 '내려받은 그대로' 읽는다(여러 파일, cp949/utf-8 모두).
- 처리장 좌표(site_coords.csv)가 있으면 반경 WEATHER_MAX_KM 안의 가까운 WEATHER_K 개 지점 거리가중 평균,
  없으면 처리장 시군과 같은 시군에 있는 지점들의 평균(지점정보의 주소로 판별).
- 파생 변수: 3일 누적강수, 선행강우지수(API), 강수일/건기일 표시, 7·14·30일 이동평균기온
- 검증: 04번 '광역 고유량일'과 도 평균 강수의 일치도
산출: work/weather_by_site.pkl (22·23번이 사용)
자료가 아직 없으면 '자료 대기' 보고서만 만들고 정상 종료합니다.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean

RAIN_BLANK_AS_ZERO = True   # 기상청 일자료는 비가 안 온 날 일강수량이 빈칸 → 0으로 처리


def read_any(path):
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없음: {path}")


def pick(cols, *keys, exclude=()):
    """열 이름 중 keys 중 하나를 포함하고 exclude 를 포함하지 않는 첫 열"""
    for k in keys:
        for c in cols:
            cs = str(c).strip()
            if (cs == k or k in cs) and not any(e in cs for e in exclude):
                return c
    return None


def load_weather():
    files = sorted(list(C.WEATHER_DIR.glob("*.csv")) + list(C.WEATHER_DIR.glob("*.CSV")))
    frames, info = [], []
    for f in files:
        d = read_any(f)
        cols = list(d.columns)
        c_id = pick(cols, "지점", "stn_id", "STN", "stn", exclude=("지점명", "주소"))
        c_nm = pick(cols, "지점명", "stn_nm")
        c_dt = pick(cols, "일시", "date", "tm", "TM")
        c_rn = pick(cols, "일강수량", "강수량", "rn_day", "rain")
        c_ta = pick(cols, "평균기온", "ta_avg", "tavg", "avgTa")
        c_tn = pick(cols, "최저기온", "ta_min", "tmin", "minTa", exclude=("시각",))
        c_tx = pick(cols, "최고기온", "ta_max", "tmax", "maxTa", exclude=("시각",))
        if c_id is None or c_dt is None:
            info.append({"파일": f.name, "상태": "지점/일시 열을 찾지 못함", "열": ", ".join(map(str, cols[:8]))})
            continue
        out = pd.DataFrame({"stn": d[c_id].astype(str).str.strip(),
                            "date": pd.to_datetime(d[c_dt].astype(str).str[:10], errors="coerce")})
        out["stn_name"] = d[c_nm].astype(str).str.strip() if c_nm else ""
        out["rain_mm"] = pd.to_numeric(d[c_rn], errors="coerce") if c_rn else np.nan
        if c_rn and RAIN_BLANK_AS_ZERO:
            out["rain_mm"] = out["rain_mm"].fillna(0.0)
        for nm, c in [("ta_mean", c_ta), ("ta_min", c_tn), ("ta_max", c_tx)]:
            out[nm] = pd.to_numeric(d[c], errors="coerce") if c else np.nan
        out["src"] = f.name
        frames.append(out.dropna(subset=["date"]))
        info.append({"파일": f.name, "상태": "OK", "행수": len(out), "지점수": out["stn"].nunique(),
                     "강수열": c_rn, "기온열": c_ta})
    if not frames:
        return None, pd.DataFrame(info)
    w = pd.concat(frames, ignore_index=True)
    # 같은 지점·날짜가 ASOS/AWS 양쪽에 있으면 첫 값 사용
    w = w.sort_values(["stn", "date", "src"]).drop_duplicates(["stn", "date"])
    return w, pd.DataFrame(info)


def load_stations():
    if not C.WEATHER_STATIONS_CSV.exists():
        return None
    s = read_any(C.WEATHER_STATIONS_CSV)
    cols = list(s.columns)
    c_id = pick(cols, "지점", "stn_id", "STN", exclude=("지점명", "주소"))
    c_lat = pick(cols, "위도", "lat", "LAT")
    c_lon = pick(cols, "경도", "lon", "LON")
    c_addr = pick(cols, "지점주소", "주소", "addr")
    c_nm = pick(cols, "지점명", "stn_nm")
    st = pd.DataFrame({"stn": s[c_id].astype(str).str.strip()})
    st["lat"] = pd.to_numeric(s[c_lat], errors="coerce") if c_lat else np.nan
    st["lon"] = pd.to_numeric(s[c_lon], errors="coerce") if c_lon else np.nan
    st["addr"] = s[c_addr].astype(str) if c_addr else ""
    st["stn_name"] = s[c_nm].astype(str) if c_nm else ""
    # 지점이 이전되면 행이 여러 개 → 마지막(최근) 행 사용
    return st.drop_duplicates("stn", keep="last")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def build_weights(sites, st, avail):
    """처리장별 {지점: 가중치}와 매칭 방법"""
    coords = None
    if C.SITE_COORDS_CSV.exists():
        coords = pd.read_csv(C.SITE_COORDS_CSV, encoding="utf-8-sig")
        coords.columns = [c.strip().lower() for c in coords.columns]
        coords = coords.set_index("site")
    st = st[st["stn"].isin(avail)] if st is not None else None
    W, meta = {}, []
    for site, sigun in sites.items():
        w, method, detail = {}, "", ""
        if coords is not None and site in coords.index and st is not None and st["lat"].notna().any():
            la, lo = coords.loc[site, "lat"], coords.loc[site, "lon"]
            d = haversine(la, lo, st["lat"].values, st["lon"].values)
            order = np.argsort(d)
            near = [i for i in order[:C.WEATHER_K] if d[i] <= C.WEATHER_MAX_KM]
            if not near:
                near = [order[0]]
                method = "좌표-최근접(반경 밖)"
            else:
                method = "좌표-거리가중"
            for i in near:
                w[st["stn"].iloc[i]] = 1 / max(d[i], 0.5) ** 2
            detail = ", ".join(f"{st['stn_name'].iloc[i] or st['stn'].iloc[i]}({d[i]:.1f}km)" for i in near)
        elif st is not None and isinstance(sigun, str) and sigun:
            key = sigun[:-1] if len(sigun) > 2 else sigun        # '가평군' → '가평'
            m = st[st["addr"].str.contains(key, na=False) | st["stn_name"].str.contains(key, na=False)]
            if len(m):
                w = {s: 1.0 for s in m["stn"]}
                method = "시군-평균"
                detail = ", ".join((m["stn_name"].replace("", np.nan).fillna(m["stn"])).tolist()[:6])
        if not w:
            w = {s: 1.0 for s in avail}
            method = "도-전체평균(매칭 실패)"
        tot = sum(w.values())
        W[site] = {k: v / tot for k, v in w.items()}
        meta.append({"site": site, "시군": sigun, "매칭방법": method, "지점수": len(w), "지점": detail})
    return W, pd.DataFrame(meta)


def weighted(wide, weights):
    cols = [c for c in weights if c in wide.columns]
    if not cols:
        return pd.Series(np.nan, index=wide.index)
    X = wide[cols]
    wv = np.array([weights[c] for c in cols])
    mask = X.notna().values
    num = np.nansum(X.values * wv, axis=1)
    den = (mask * wv).sum(axis=1)
    return pd.Series(np.where(den > 0, num / np.where(den > 0, den, 1), np.nan), index=wide.index)


def main():
    rep = Report("21_merge_weather", "21. 기상자료 결합",
                 "기상청 일 강수·기온을 처리장별로 붙이고, TMS에서 찾은 광역 고유량일과 맞는지 확인한다.")
    w, info = load_weather()
    if w is None:
        rep.p(f"⏳ 자료 대기: `{C.WEATHER_DIR}` 에 기상청 일자료 CSV 가 없습니다. DATA_SPEC.md 의 B-1을 참고해 넣어 주세요.")
        if len(info):
            rep.table(info, "읽기 시도 결과")
        rep.save()
        return
    rep.table(info, "읽은 기상 파일")
    st = load_stations()
    if st is None:
        rep.p("⚠ 지점정보(weather_stations.csv)가 없어 모든 처리장에 도 전체 평균을 씁니다. DATA_SPEC.md B-2 참고.")

    df = load_clean(types=None)
    sites = df.groupby("site")["sigun"].first()
    avail = sorted(w["stn"].unique())
    W, meta = build_weights(sites, st, avail)
    rep.h("1. 처리장-기상지점 매칭")
    rep.table(meta["매칭방법"].value_counts().rename_axis("방법").reset_index(name="사업장 수"))
    rep.csv(meta, "site_station_matching.csv")
    rep.table(meta[meta["매칭방법"].str.contains("실패|반경 밖")], "확인이 필요한 매칭")

    piv = {v: w.pivot_table(index="date", columns="stn", values=v, aggfunc="first") for v in
           ["rain_mm", "ta_mean", "ta_min", "ta_max"]}
    out = []
    for site in sites.index:
        d = pd.DataFrame({v: weighted(piv[v], W[site]) for v in piv})
        d = d.asfreq("D")
        d["rain_3d"] = d["rain_mm"].rolling(3, min_periods=1).sum()
        api = np.zeros(len(d))
        r = d["rain_mm"].fillna(0).values
        for i in range(len(d)):
            api[i] = r[i] + (C.API_K * api[i - 1] if i else 0)
        d["api"] = api
        d["wet"] = d["rain_mm"] >= C.WET_DAY_MM
        d["dry"] = d["rain_mm"].fillna(0).rolling(C.DRY_PRIOR_DAYS + 1, min_periods=1).max() < C.WET_DAY_MM
        for k in (7, 14, 30):
            d[f"ta_ma{k}"] = d["ta_mean"].rolling(k, min_periods=max(3, k // 2)).mean()
        d["site"] = site
        out.append(d.reset_index().rename(columns={"index": "date"}))
    wx = pd.concat(out, ignore_index=True)
    C.WORK_DIR.mkdir(parents=True, exist_ok=True)
    wx.to_pickle(C.WEATHER_PKL)
    rep.kv({"기상 기간": f"{w['date'].min():%Y-%m-%d} ~ {w['date'].max():%Y-%m-%d}",
            "기상 지점 수": len(avail), "처리장 수": len(sites), "저장": str(C.WEATHER_PKL)})

    rep.h("2. 검증: TMS 광역 고유량일 vs 도 평균 강수")
    reg = wx.groupby("date")[["rain_mm", "ta_mean"]].mean()
    f04 = C.RESULTS_DIR / "04_flow_analysis" / "regional_flow_signal_by_date.csv"
    if f04.exists():
        r4 = pd.read_csv(f04, parse_dates=["date"]).set_index("date")
        j = r4.join(reg, how="inner")
        j["rain_2d"] = j["rain_mm"].rolling(2, min_periods=1).sum()
        rep.kv({"상관(고유량방류구비율 vs 당일 강수)": j["고유량방류구비율"].corr(j["rain_mm"], method="spearman"),
                "상관(vs 2일 누적 강수)": j["고유량방류구비율"].corr(j["rain_2d"], method="spearman")})
        top = j.sort_values("고유량방류구비율", ascending=False).head(20).reset_index()[["date", "고유량방류구비율", "rain_mm", "rain_2d"]]
        rep.table(top, "TMS 고유량 상위 20일의 도 평균 강수(mm)")
        dry_high = j[(j["고유량방류구비율"] > 0.05) & (j["rain_2d"] < 1)]
        rep.table(dry_high.reset_index()[["date", "고유량방류구비율", "rain_2d"]], "비가 없는데 고유량인 날(다른 원인 후보)")
        fig, ax = plt.subplots(figsize=(13, 3.5))
        ax.bar(j.index, j["rain_mm"], width=1, color="lightsteelblue", label="도 평균 강수(mm)")
        ax2 = ax.twinx()
        ax2.plot(j.index, j["고유량방류구비율"] * 100, lw=0.8, color="crimson", label="고유량 방류구(%)")
        ax.set_ylabel("mm")
        ax2.set_ylabel("%")
        ax.set_title("도 평균 강수와 TMS 고유량 방류구 비율")
        rep.fig(fig, "rain_vs_regional_flow.png")
    else:
        rep.p("04번 결과가 없어 검증을 건너뜀.")

    m = reg.resample("MS").agg({"rain_mm": "sum", "ta_mean": "mean"}).reset_index()
    m["date"] = m["date"].dt.strftime("%Y-%m")
    rep.table(m.rename(columns={"date": "월", "rain_mm": "도평균 월강수(mm)", "ta_mean": "평균기온(℃)"}), "월별 기상 요약", max_rows=40)
    rep.save()


if __name__ == "__main__":
    main()
