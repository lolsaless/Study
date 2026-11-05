# -*- coding: utf-8 -*-
"""
결과 대시보드(HTML 1개 파일) 생성기
- results/ 아래의 summary.md·CSV·그림을 모아, 인터넷 없이 열리는 단일 HTML(dashboard.html)을 만든다.
- 구성: 핵심 지표 카드 · 주요 차트 · 처리장 탐색표(검색·정렬·시군 필터) · 분석별 결과(요약+그림) · 분석 신뢰도 표
- 분석을 다시 돌린 뒤 이 파일만 다시 실행하면 대시보드가 갱신된다.

사용:
  python build_dashboard.py
  python build_dashboard.py --results results --out dashboard.html --no-images
"""
import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

try:
    import config as C
    DEFAULT_RESULTS = C.RESULTS_DIR
    DEFAULT_OUT = C.BASE_DIR / "dashboard.html"
except Exception:  # config 없이 단독 실행
    DEFAULT_RESULTS = Path("results")
    DEFAULT_OUT = Path("dashboard.html")

# ── 분석별 신뢰도(해석 문서와 맞춰 수동 관리. 재분석 후 여기만 고치면 된다) ──
STATUS = {
    "01_preprocess": ("사용", "중복 22행 모두 동일값, 하수 유량 역산률 99.7%"),
    "02_data_quality": ("사용", "pH·SS 고정값 구간이 많음(정보량 적음)"),
    "03_descriptive_stats": ("사용", ""),
    "04_flow_analysis": ("사용", "광역 고유량일이 10·12번과 일치"),
    "05_compliance_margin": ("재실행 필요", "지역표(site_region.csv) 없이 I지역 기준 일괄 적용 → TP·TOC 허상"),
    "06_seasonality_stl": ("부분 사용", "월별 프로파일·겨울/여름 검정 사용, STL 강도는 과대"),
    "07_weekday_holiday": ("사용", "명절은 강우일 제외 후 재확인(22번)"),
    "08_trend_mannkendall": ("v2 재실행", "Sen 기울기 12배 과대 → v2에서 수정"),
    "09_changepoint": ("v2 재실행", "계절 전환을 변화점으로 잡음 → v2에서 계절 제거"),
    "10_anomaly_detection": ("v2 재실행", "해상도 때문에 과검출 → v2에서 하한 적용"),
    "11_param_correlation_cq": ("제한적", "일 단위 상관 약함 → 22번 강우 이벤트 분석으로 대체"),
    "12_cross_site_sync": ("사용", "유량 21%·TN 9%·TP 3% 공통 신호"),
    "13_typology_clustering": ("제한적", "실루엣 0.1 — 군집 대신 PCA 축 사용"),
    "14_shape_clustering": ("사용", ""),
    "15_autocorr_spectral": ("사용", ""),
    "16_load_contribution": ("사용", "고양난지는 서울시 시설(서울 하수 처리)"),
    "17_multi_outlet": ("사용", ""),
    "18_extreme_value": ("v2 재실행", "SS 발산·TP 지역기준 문제 → v2에서 보정"),
    "19_lead_lag_granger": ("v2 재실행", "그랜저 검정 실패 → v2에서 호환 수정"),
    "21_merge_weather": ("자료 대기", "기상청 일자료 필요"),
    "22_rain_response": ("자료 대기", "21번 이후"),
    "23_temperature_threshold": ("자료 대기", "21번 이후"),
}


# ── 작은 도우미 ─────────────────────────────────────────
def rd(path, **kw):
    try:
        return pd.read_csv(path, encoding="utf-8-sig", **kw) if Path(path).exists() else None
    except Exception:
        return None


def num(v, d=2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if not np.isfinite(v):
        return "–"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.{d}f}".rstrip("0").rstrip(".")


def b64img(path):
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


INLINE = [(re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
          (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
          (re.compile(r"(?<![\w*])_\((.+?)\)_"), r"<i>(\1)</i>")]


def inline(s):
    s = html.escape(s, quote=False)
    for pat, rep in INLINE:
        s = pat.sub(rep, s)
    return s


def md_to_html(md, base_dir, embed_images=True):
    """summary.md 전용 간이 변환기(제목, 표, 목록, 문단, 그림 줄)"""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("# "):
            i += 1
            continue  # 제목은 카드 머리글로 대체
        m = re.match(r"^(#{2,4})\s+(.*)", ln)
        if m:
            lvl = min(len(m.group(1)) + 1, 5)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if len(cells) >= 2 and all(set(c) <= set("-: ") for c in cells[1]):
                head, body = cells[0], cells[2:]
            else:
                head, body = None, cells
            t = ["<div class='tbl'><table>"]
            if head:
                t.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>")
            t.append("<tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")
            out.append("".join(t))
            continue
        fm = re.match(r"^- 그림: `([^`]+)`(?:\s*—\s*(.*))?", ln)
        if fm:
            p = base_dir / fm.group(1)
            cap = inline(fm.group(2) or Path(fm.group(1)).stem)
            if embed_images and p.exists():
                out.append(f"<figure><img loading='lazy' src='{b64img(p)}' alt='{cap}' onclick='zoom(this)'><figcaption>{cap}</figcaption></figure>")
            else:
                out.append(f"<p class='muted'>그림: {html.escape(fm.group(1))} {cap}</p>")
            i += 1
            continue
        if re.match(r"^(- |\d+\. )", ln):
            items, ordered = [], bool(re.match(r"^\d+\. ", ln))
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i]):
                items.append(re.sub(r"^(- |\d+\. )", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if ln.strip():
            para = [ln]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||- |\d+\. )", lines[i]):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
            continue
        i += 1
    return "\n".join(out)


def kv_from_md(md):
    """'- 키: 값' 줄을 사전으로(같은 키는 순서대로 리스트)"""
    d = {}
    for m in re.finditer(r"^- ([^:\n]+):\s*(.+)$", md, re.M):
        d.setdefault(m.group(1).strip(), []).append(m.group(2).strip())
    return d


# ── 데이터 모으기 ───────────────────────────────────────
def collect(R):
    data = {"kpi": [], "charts": {}, "sites": [], "siteCols": []}

    cov = rd(R / "01_preprocess" / "coverage_by_sid.csv", parse_dates=["시작", "끝"])
    q2 = rd(R / "02_data_quality" / "quality_by_sid.csv")
    if cov is not None:
        sw = cov[cov["유형"] == "하수"]
        data["kpi"].append(["하수처리장 / 방류구", f"{sw['사업장'].nunique()} / {len(sw)}", f"전체 사업장 {cov['사업장'].nunique()}곳"])
        data["kpi"].append(["자료 기간", f"{cov['시작'].min():%Y.%m} ~ {cov['끝'].max():%Y.%m}", "일 단위"])
    if q2 is not None:
        sq = q2[q2["유형"] == "하수"]
        data["kpi"].append(["품질 A등급(하수)", f"{(sq['등급'] == 'A').mean() * 100:.0f}%", f"{(sq['등급'] == 'A').sum()} / {len(sq)} 방류구"])
    md12 = (R / "12_cross_site_sync" / "summary.md")
    if md12.exists():
        pcs = kv_from_md(md12.read_text(encoding="utf-8")).get("PC1 설명분산(%)", [])
        if len(pcs) >= 3:
            data["kpi"].append(["공통 신호 설명비율", f"유량 {num(pcs[0], 0)}% · TN {num(pcs[1], 0)}% · TP {num(pcs[2], 0)}%", "도 전체가 함께 움직이는 몫"])
    prof = rd(R / "06_seasonality_stl" / "monthly_profile_long.csv")
    if prof is not None:
        pm = prof.groupby(["var", "month"])["norm"].median().unstack("var")
        data["charts"]["monthly"] = {"months": [int(m) for m in pm.index],
                                     "series": {v: [round(float(x), 3) for x in pm[v]] for v in ["Q", "TN", "TP", "TOC", "SS"] if v in pm}}
        if "TN" in pm and "TP" in pm:
            data["kpi"].append(["계절 정점", f"TN {int(pm['TN'].idxmax())}월 · TP {int(pm['TP'].idxmax())}월", "월평균/연평균 기준"])
    reg = rd(R / "04_flow_analysis" / "regional_flow_signal_by_date.csv")
    if reg is not None:
        data["charts"]["regional"] = {"dates": reg["date"].astype(str).tolist(),
                                      "share": [round(float(x) * 100, 2) if pd.notna(x) else None for x in reg["고유량방류구비율"]]}
    hol = rd(R / "07_weekday_holiday" / "holiday_effect_long.csv")
    if hol is not None and hol["시군"].notna().any():
        hs = hol.groupby("시군")["Q변화_pct"].median().sort_values()
        data["charts"]["holiday"] = {"labels": hs.index.tolist(), "values": [round(float(x), 1) for x in hs.values]}
    load = rd(R / "16_load_contribution" / "annual_load_by_site.csv")
    if load is not None:
        y = int(load["year"].max())
        v = load.loc[load["year"] == y, "TN_연간톤"].dropna().sort_values(ascending=False)
        cs = v.cumsum() / v.sum()
        data["kpi"].append([f"TN 부하 50%를 내는 시설({y})", f"{int((cs < 0.5).sum() + 1)}곳", f"전체 {len(v)}곳 중"])

    # 처리장 탐색표(있는 결과만 합침)
    base = None
    if cov is not None:
        base = cov[["sid", "사업장", "유형", "시군", "Q중앙", "보유율_pct"]].copy()
    pieces = [
        (q2, ["sid", "품질점수", "등급"]),
        (rd(R / "03_descriptive_stats" / "stats_by_sid.csv"), ["sid", "TN_중앙", "TP_중앙", "TOC_중앙", "TN_CV"]),
        (rd(R / "04_flow_analysis" / "flow_stats_by_sid.csv"), ["sid", "첨두_max/p50", "초과유량_상위5%평균_pct", "상위5%내_평탄비율_pct"]),
        (rd(R / "06_seasonality_stl" / "seasonality_by_sid.csv"), ["sid", "TN_진폭", "TN_최고월", "TP_최고월"]),
        (rd(R / "12_cross_site_sync" / "Q_pca_r2.csv"), ["sid", "PC1_R2"]),
        (rd(R / "22_rain_response" / "rain_response_by_sid.csv"), ["sid", "3일누적10mm당_증가pct", "큰비일_천장근접비율_pct", "TP_여름/겨울_건기만"]),
        (rd(R / "23_temperature_threshold" / "temperature_by_sid.csv"), ["sid", "TN_임계기온", "TN_임계이하_기울기pct/℃"]),
    ]
    if base is not None:
        for d, cols in pieces:
            if d is not None and set(cols) <= set(d.columns):
                base = base.merge(d[cols], on="sid", how="left")
        if hol is not None:
            base = base.merge(hol.groupby("sid")["Q변화_pct"].mean().rename("명절_유량변화pct"), on="sid", how="left")
        ren = {"Q중앙": "유량중앙(m3/일)", "보유율_pct": "보유율%", "PC1_R2": "유량공통신호R2",
               "초과유량_상위5%평균_pct": "고유량초과%", "상위5%내_평탄비율_pct": "천장평탄%", "첨두_max/p50": "최대/중앙"}
        base = base.rename(columns=ren)
        data["siteCols"] = list(base.columns)
        data["sites"] = [[(None if (isinstance(x, float) and not np.isfinite(x)) else (round(x, 4) if isinstance(x, float) else x))
                          for x in row] for row in base.astype(object).where(base.notna(), None).itertuples(index=False)]
    return data


# ── HTML ────────────────────────────────────────────────
CSS = """
:root{--ink:#1d2433;--muted:#5d6678;--line:#e3e7ee;--bg:#f6f7f9;--card:#fff;--accent:#2563eb;--accent2:#e8622c;--grey:#9aa3b2;--ok:#1a7f4b;--warn:#b26b00;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;font-family:Pretendard,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;color:var(--ink);background:var(--bg);font-size:14px;line-height:1.55}
.wrap{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
nav{position:sticky;top:0;height:100vh;overflow:auto;background:#101827;color:#cfd6e4;padding:18px 14px}
nav h1{font-size:15px;color:#fff;margin:0 0 4px}nav .sub{font-size:11px;color:#8b95a7;margin-bottom:14px}
nav a{display:block;color:#cfd6e4;text-decoration:none;padding:5px 8px;border-radius:6px;font-size:12.5px}
nav a:hover{background:#1f2a3d;color:#fff}nav .grp{margin:12px 0 4px;font-size:11px;color:#8b95a7;text-transform:uppercase;letter-spacing:.04em}
main{padding:26px 34px;max-width:1280px;min-width:0}
.chart{max-width:760px}
h2.sec{font-size:19px;margin:30px 0 12px;padding-top:8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .k{font-size:12px;color:var(--muted)}.kpi .v{font-size:19px;font-weight:700;margin:4px 0}.kpi .n{font-size:11.5px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}
.card h3{margin:0 0 6px;font-size:16px}.card h4{font-size:14px;margin:16px 0 6px}.card h5{font-size:13px;margin:12px 0 4px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:1100px){.grid2{grid-template-columns:1fr}.wrap{grid-template-columns:1fr}nav{position:static;height:auto}}
.tbl{overflow:auto;max-height:420px;border:1px solid var(--line);border-radius:8px;margin:6px 0 10px}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{background:#f1f3f7;position:sticky;top:0;z-index:1;cursor:pointer}td.num{text-align:right;font-variant-numeric:tabular-nums}
figure{margin:10px 0}figure img{max-width:100%;border:1px solid var(--line);border-radius:6px;cursor:zoom-in;background:#fff}figcaption{font-size:12px;color:var(--muted)}
.muted{color:var(--muted)}code{background:#eef1f6;padding:1px 5px;border-radius:4px;font-size:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11.5px;font-weight:600}
.b-ok{background:#e7f6ee;color:var(--ok)}.b-warn{background:#fff4e0;color:var(--warn)}.b-bad{background:#fdecea;color:var(--bad)}.b-wait{background:#eef1f6;color:var(--muted)}
details>summary{cursor:pointer;font-weight:600;font-size:15px;padding:4px 0}details[open]>summary{margin-bottom:8px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}.controls input,.controls select{padding:6px 10px;border:1px solid var(--line);border-radius:6px;font-size:13px}
#zoom{position:fixed;inset:0;background:rgba(10,15,25,.85);display:none;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}#zoom img{max-width:95vw;max-height:92vh;background:#fff;border-radius:6px}
svg text{font-family:inherit}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
function zoom(img){const z=document.getElementById('zoom');z.querySelector('img').src=img.src;z.style.display='flex';}
document.getElementById('zoom').onclick=()=>{document.getElementById('zoom').style.display='none'};
function el(t,a={},h=''){const e=document.createElementNS('http://www.w3.org/2000/svg',t);for(const k in a)e.setAttribute(k,a[k]);if(h)e.textContent=h;return e;}
// KPI
const K=document.getElementById('kpis');
D.kpi.forEach(([k,v,n])=>{K.insertAdjacentHTML('beforeend',`<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="n">${n}</div></div>`)});
// 월별 프로파일
(function(){const c=D.charts.monthly;if(!c)return;const W=620,H=300,L=46,R=70,T=20,B=34;
 const s=document.getElementById('ch-monthly');const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});
 const all=Object.values(c.series).flat();const lo=Math.min(0.8,...all),hi=Math.max(1.2,...all);
 const x=m=>L+(m-1)/11*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
 for(let v=Math.ceil(lo*10)/10;v<=hi+1e-9;v+=0.1){svg.append(el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:Math.abs(v-1)<1e-6?'#9aa3b2':'#e3e7ee','stroke-dasharray':Math.abs(v-1)<1e-6?'4 3':''}));svg.append(el('text',{x:L-6,y:y(v)+4,'text-anchor':'end','font-size':11,fill:'#5d6678'},v.toFixed(1)));}
 c.months.forEach(m=>svg.append(el('text',{x:x(m),y:H-12,'text-anchor':'middle','font-size':11,fill:'#5d6678'},m+'월')));
 const col={TN:'#2563eb',TP:'#e8622c',Q:'#9aa3b2',TOC:'#c7ccd6',SS:'#dfe3ea'};const wid={TN:2.5,TP:2.5};
 ['Q','TP','TN'].forEach(k=>{const v=c.series[k];if(!v)return;const d=v.map((y0,i)=>(i?'L':'M')+x(c.months[i])+' '+y(y0)).join(' ');
  svg.append(el('path',{d,fill:'none',stroke:col[k],'stroke-width':wid[k]||1.5}));
  v.forEach((y0,i)=>{const p=el('circle',{cx:x(c.months[i]),cy:y(y0),r:2.5,fill:col[k]});p.append(el('title',{},`${k} ${c.months[i]}월: ${y0}`));svg.append(p)});
  svg.append(el('text',{x:x(12)+8,y:y(v[v.length-1])+4,'font-size':12,'font-weight':700,fill:col[k]},k==='Q'?'유량':k));});
 s.append(svg);})();
// 광역 고유량
(function(){const c=D.charts.regional;if(!c)return;const W=620,H=240,L=40,R=10,T=14,B=30;const s=document.getElementById('ch-regional');
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});const n=c.dates.length;const mx=Math.max(...c.share.filter(v=>v!=null),5);
 const x=i=>L+i/(n-1)*(W-L-R),y=v=>T+(mx-v)/mx*(H-T-B);
 [0,5,10,15,20,25].filter(v=>v<=mx).forEach(v=>{svg.append(el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:'#e3e7ee'}));svg.append(el('text',{x:L-6,y:y(v)+4,'text-anchor':'end','font-size':11,fill:'#5d6678'},v+'%'))});
 let d='';c.share.forEach((v,i)=>{if(v==null)return;d+=(d?'L':'M')+x(i)+' '+y(v)});svg.append(el('path',{d,fill:'none',stroke:'#2563eb','stroke-width':1}));
 c.dates.forEach((t,i)=>{if(t.endsWith('-01-01')||t.endsWith('-07-01'))svg.append(el('text',{x:x(i),y:H-10,'text-anchor':'middle','font-size':11,fill:'#5d6678'},t.slice(0,7)))});
 const top=[];c.share.map((v,i)=>[v,i]).filter(a=>a[0]!=null).sort((a,b)=>b[0]-a[0]).forEach(a=>{if(top.length<5&&top.every(t=>Math.abs(t[1]-a[1])>5))top.push(a)});
 top.forEach(([v,i])=>{const p=el('circle',{cx:x(i),cy:y(v),r:3.5,fill:'#e8622c'});p.append(el('title',{},`${c.dates[i]}: ${v}%`));svg.append(p);const nr=x(i)>W-70;svg.append(el('text',{x:nr?x(i)-5:x(i)+5,y:y(v)-4,'text-anchor':nr?'end':'start','font-size':10.5,fill:'#1d2433'},c.dates[i].slice(2)))});
 s.append(svg);})();
// 명절 시군
(function(){const c=D.charts.holiday;if(!c)return;const n=c.labels.length,W=620,rowH=17,H=n*rowH+30,L=80,R=50;const s=document.getElementById('ch-holiday');
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});const mx=Math.max(...c.values.map(Math.abs),5);const x0=L+(W-L-R)/2,sc=(W-L-R)/2/mx;
 svg.append(el('line',{x1:x0,x2:x0,y1:6,y2:H-20,stroke:'#9aa3b2'}));
 c.labels.forEach((lab,i)=>{const v=c.values[i],y=8+i*rowH;const r=el('rect',{x:v<0?x0+v*sc:x0,y:y,width:Math.abs(v)*sc,height:rowH-5,fill:v<0?'#9aa3b2':'#2563eb'});r.append(el('title',{},`${lab}: ${v}%`));svg.append(r);
  svg.append(el('text',{x:L-6,y:y+10,'text-anchor':'end','font-size':11,fill:'#1d2433'},lab));
  svg.append(el('text',{x:v<0?x0+4:x0-4,y:y+10,'text-anchor':v<0?'start':'end','font-size':10.5,fill:'#5d6678'},(v>0?'+':'')+v+'%'))});
 s.append(svg);})();
// 처리장 탐색표
(function(){const cols=D.siteCols,rows=D.sites;if(!cols.length)return;const tb=document.getElementById('site-tbl');const q=document.getElementById('site-q'),sg=document.getElementById('site-sigun'),ty=document.getElementById('site-type');
 const iS=cols.indexOf('시군'),iT=cols.indexOf('유형');
 [...new Set(rows.map(r=>r[iS]).filter(Boolean))].sort().forEach(v=>sg.insertAdjacentHTML('beforeend',`<option>${v}</option>`));
 [...new Set(rows.map(r=>r[iT]).filter(Boolean))].sort().forEach(v=>ty.insertAdjacentHTML('beforeend',`<option ${v==='하수'?'selected':''}>${v}</option>`));
 let sortI=-1,asc=true;
 function fmt(v){if(v==null)return'';if(typeof v==='number'){const a=Math.abs(v);return a>=1000?v.toLocaleString('ko-KR',{maximumFractionDigits:0}):(+v.toFixed(a<1?3:2)).toString()}return v}
 function draw(){let r=rows.filter(x=>(!q.value||x.join(' ').includes(q.value))&&(!sg.value||x[iS]===sg.value)&&(!ty.value||x[iT]===ty.value));
  if(sortI>=0)r=[...r].sort((a,b)=>{const A=a[sortI],B=b[sortI];if(A==null)return 1;if(B==null)return -1;return (A>B?1:A<B?-1:0)*(asc?1:-1)});
  tb.innerHTML='<thead><tr>'+cols.map((c,i)=>`<th data-i="${i}">${c}${i===sortI?(asc?' ▲':' ▼'):''}</th>`).join('')+'</tr></thead><tbody>'+
   r.map(x=>'<tr>'+x.map(v=>`<td class="${typeof v==='number'?'num':''}">${fmt(v)}</td>`).join('')+'</tr>').join('')+'</tbody>';
  document.getElementById('site-n').textContent=r.length+'개 방류구';
  tb.querySelectorAll('th').forEach(th=>th.onclick=()=>{const i=+th.dataset.i;asc=sortI===i?!asc:false;sortI=i;draw()});}
 [q,sg,ty].forEach(e=>e.oninput=draw);draw();})();
"""


def build(R, out, embed_images=True):
    R = Path(R)
    data = collect(R)
    reports = sorted(p for p in R.glob("*/summary.md"))
    nav, secs = [], []
    for p in reports:
        name = p.parent.name
        md = p.read_text(encoding="utf-8")
        title = next((l[2:] for l in md.splitlines() if l.startswith("# ")), name)
        st, note = STATUS.get(name, ("", ""))
        cls = {"사용": "b-ok", "부분 사용": "b-warn", "제한적": "b-warn", "재실행 필요": "b-bad",
               "v2 재실행": "b-bad", "자료 대기": "b-wait"}.get(st, "b-wait")
        badge = f"<span class='badge {cls}'>{st}</span>" if st else ""
        nav.append(f"<a href='#{name}'>{html.escape(title[:28])}</a>")
        body = md_to_html(md, p.parent, embed_images)
        secs.append(f"<div class='card' id='{name}'><details><summary>{html.escape(title)} {badge}</summary>"
                    f"{'<p class=muted>' + html.escape(note) + '</p>' if note else ''}{body}</details></div>")
    status_rows = "".join(
        f"<tr><td>{k}</td><td><span class='badge {({'사용': 'b-ok', '부분 사용': 'b-warn', '제한적': 'b-warn', '자료 대기': 'b-wait'}).get(v[0], 'b-bad')}'>{v[0]}</span></td><td>{html.escape(v[1])}</td></tr>"
        for k, v in STATUS.items())
    gen = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    js_data = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>경기도 하수처리장 TMS 분석 대시보드</title><style>{CSS}</style></head><body>
<div class="wrap"><nav><h1>TMS 분석 대시보드</h1><div class="sub">생성 {gen}</div>
<a href="#top">핵심 지표</a><a href="#charts">주요 차트</a><a href="#sites">처리장 탐색</a><a href="#status">분석 신뢰도</a>
<div class="grp">분석별 결과</div>{''.join(nav)}</nav>
<main><h2 class="sec" id="top" style="margin-top:0">경기도 하수처리장 TMS 일자료 분석</h2>
<p class="muted">TMS 일자료(배출량·농도)와 역산 유량으로 본 처리장 변동. 표의 열 머리를 누르면 정렬, 그림을 누르면 확대됩니다.</p>
<div class="kpis" id="kpis"></div>
<h2 class="sec" id="charts">주요 차트</h2>
<div class="grid2"><div class="card"><h3>TN은 겨울, TP는 여름에 오른다</h3><p class="muted">월평균 ÷ 연평균, 하수 방류구 중앙값</p><div id="ch-monthly"></div></div>
<div class="card"><h3>도 전체 고유량일(광역 강우 후보)</h3><p class="muted">평소의 1.3배 이상 유량을 보인 방류구 비율, 상위 5일 표시</p><div id="ch-regional"></div></div></div>
<div class="card"><h3>명절 연휴 유량 변화(시군 중앙값)</h3><p class="muted">앞뒤 2주 같은 기간 대비. 회색=감소, 파랑=증가</p><div id="ch-holiday" class="chart"></div></div>
<h2 class="sec" id="sites">처리장 탐색</h2>
<div class="card"><div class="controls"><input id="site-q" placeholder="처리장 이름 검색"><select id="site-sigun"><option value="">시군 전체</option></select>
<select id="site-type"><option value="">유형 전체</option></select><span class="muted" id="site-n"></span></div>
<div class="tbl" style="max-height:560px"><table id="site-tbl"></table></div>
<p class="muted">고유량초과% = 상위 5% 날의 기저유량 대비 초과율 · 천장평탄% = 고유량일이 최대치 2% 안에 몰린 비율 · 유량공통신호R2 = 도 전체 공통 변동으로 설명되는 몫</p></div>
<h2 class="sec" id="status">분석 신뢰도</h2>
<div class="card"><div class="tbl"><table><thead><tr><th>분석</th><th>판정</th><th>메모</th></tr></thead><tbody>{status_rows}</tbody></table></div></div>
<h2 class="sec">분석별 결과</h2>{''.join(secs)}
</main></div><div id="zoom"><img alt=""></div>
<script type="application/json" id="data">{js_data}</script><script>{JS}</script></body></html>"""
    Path(out).write_text(page, encoding="utf-8")
    print(f"[완료] {out}  ({Path(out).stat().st_size / 1024 / 1024:.1f} MB, 보고서 {len(reports)}개)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args()
    build(a.results, a.out, not a.no_images)
