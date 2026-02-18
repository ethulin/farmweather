#!/usr/bin/env python3
"""
Historical Burn Conditions Report Generator
Fetches 10 years of hourly weather data from Open-Meteo archive API,
applies the FarmWeather scoring logic, and generates an interactive HTML report.
"""

import json
import statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import requests

# ── Configuration ──────────────────────────────────────────────────────────

LAT = 16.725
LON = -88.840
START_DATE = "2015-01-01"
END_DATE = "2024-12-31"
TIMEZONE = "America/Belize"

API_URL = "https://archive-api.open-meteo.com/v1/archive"

OUTPUT_FILE = Path(__file__).parent / "report.html"

COLORS = {"green": "#22b740", "yellow": "#e6a800", "red": "#d93030"}
LABELS = {0: "green", 1: "yellow", 2: "red"}
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ── Data Fetching ──────────────────────────────────────────────────────────

def fetch_data():
    print("Fetching 10 years of hourly weather data...")
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": TIMEZONE,
    }
    resp = requests.get(API_URL, params=params, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    n = len(data["hourly"]["time"])
    print(f"  Received {n:,} hourly records")
    return data

# ── Scoring ────────────────────────────────────────────────────────────────

def score_all(times, temps, humids, winds):
    results = []
    nulls = 0
    for i in range(len(times)):
        h, w, t = humids[i], winds[i], temps[i]
        if h is None or w is None or t is None:
            nulls += 1
            continue
        sh = 0 if h > 40 else (1 if h >= 30 else 2)
        sw = 0 if w < 5 else (1 if w <= 10 else 2)
        st = 0 if t < 80 else (1 if t <= 90 else 2)
        overall = max(sh, sw, st)
        results.append({
            "time": times[i],
            "temp": t, "humid": h, "wind": w,
            "sh": sh, "sw": sw, "st": st,
            "overall": overall,
        })
    if nulls:
        print(f"  Warning: {nulls} hours had missing data and were excluded")
    return results

# ── Analysis Functions ─────────────────────────────────────────────────────

def compute_overall(scored):
    counts = {0: 0, 1: 0, 2: 0}
    for r in scored:
        counts[r["overall"]] += 1
    total = len(scored)
    return {
        "counts": counts,
        "pcts": {k: round(v / total * 100, 1) for k, v in counts.items()},
        "total": total,
    }


def compute_monthly(scored):
    monthly = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in scored:
        month = int(r["time"][5:7])
        monthly[month][r["overall"]] += 1
    result = {}
    for m in range(1, 13):
        total = sum(monthly[m].values())
        if total == 0:
            result[m] = {0: 0, 1: 0, 2: 0}
        else:
            result[m] = {k: round(v / total * 100, 1) for k, v in monthly[m].items()}
    return result


def compute_hourly_patterns(scored):
    hourly = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in scored:
        hour = int(r["time"][11:13])
        hourly[hour][r["overall"]] += 1
    result = {}
    for h in range(24):
        total = sum(hourly[h].values())
        if total == 0:
            result[h] = {0: 0, 1: 0, 2: 0}
        else:
            result[h] = {k: round(v / total * 100, 1) for k, v in hourly[h].items()}
    return result


def compute_daily_profile(scored):
    hourly_vals = defaultdict(lambda: {"temp": [], "humid": [], "wind": []})
    for r in scored:
        hour = int(r["time"][11:13])
        hourly_vals[hour]["temp"].append(r["temp"])
        hourly_vals[hour]["humid"].append(r["humid"])
        hourly_vals[hour]["wind"].append(r["wind"])
    result = {}
    for h in range(24):
        vals = hourly_vals[h]
        result[h] = {
            "temp": round(statistics.mean(vals["temp"]), 1) if vals["temp"] else 0,
            "humid": round(statistics.mean(vals["humid"]), 1) if vals["humid"] else 0,
            "wind": round(statistics.mean(vals["wind"]), 1) if vals["wind"] else 0,
        }
    return result


def compute_drivers(scored):
    """For non-green hours, which metric drives the status?"""
    drivers = {"humidity": 0, "wind": 0, "temperature": 0}
    total_non_green = 0
    for r in scored:
        if r["overall"] == 0:
            continue
        total_non_green += 1
        o = r["overall"]
        if r["sh"] == o:
            drivers["humidity"] += 1
        if r["sw"] == o:
            drivers["wind"] += 1
        if r["st"] == o:
            drivers["temperature"] += 1
    return {"drivers": drivers, "total": total_non_green}


def compute_duration(scored):
    """Consecutive run lengths for each status."""
    runs = {0: [], 1: [], 2: []}
    if not scored:
        return runs
    current_status = scored[0]["overall"]
    current_len = 1
    for i in range(1, len(scored)):
        if scored[i]["overall"] == current_status:
            current_len += 1
        else:
            runs[current_status].append(current_len)
            current_status = scored[i]["overall"]
            current_len = 1
    runs[current_status].append(current_len)

    stats = {}
    for status in [0, 1, 2]:
        r = sorted(runs[status])
        if not r:
            stats[status] = {"min": 0, "max": 0, "median": 0, "mean": 0, "p90": 0, "count": 0}
        else:
            p90_idx = int(len(r) * 0.9)
            stats[status] = {
                "min": r[0],
                "max": r[-1],
                "median": round(statistics.median(r), 1),
                "mean": round(statistics.mean(r), 1),
                "p90": r[min(p90_idx, len(r) - 1)],
                "count": len(r),
            }
    # Green duration histogram bins
    green_runs = runs[0]
    bins = {"1-2h": 0, "3-4h": 0, "5-8h": 0, "9-12h": 0, "13-18h": 0, "19-24h": 0, "25+h": 0}
    for length in green_runs:
        if length <= 2: bins["1-2h"] += 1
        elif length <= 4: bins["3-4h"] += 1
        elif length <= 8: bins["5-8h"] += 1
        elif length <= 12: bins["9-12h"] += 1
        elif length <= 18: bins["13-18h"] += 1
        elif length <= 24: bins["19-24h"] += 1
        else: bins["25+h"] += 1

    return {"stats": stats, "green_bins": bins}


def compute_best_windows(scored):
    """Find longest consecutive green runs."""
    windows = []
    if not scored:
        return {"top": [], "monthly_avg": {}}
    start = None
    length = 0
    for i, r in enumerate(scored):
        if r["overall"] == 0:
            if start is None:
                start = i
            length += 1
        else:
            if start is not None and length > 0:
                windows.append({"start": scored[start]["time"], "end": scored[i - 1]["time"], "hours": length})
            start = None
            length = 0
    if start is not None:
        windows.append({"start": scored[start]["time"], "end": scored[-1]["time"], "hours": length})

    top = sorted(windows, key=lambda x: -x["hours"])[:10]

    # Average longest green run per month
    monthly_max = defaultdict(list)
    # Group windows by starting month
    for w in windows:
        month = int(w["start"][5:7])
        monthly_max[month].append(w["hours"])
    monthly_avg = {}
    for m in range(1, 13):
        runs = monthly_max.get(m, [])
        if runs:
            # Average of the top run per year for this month
            monthly_avg[m] = round(statistics.mean(sorted(runs, reverse=True)[:10]), 1)
        else:
            monthly_avg[m] = 0

    return {"top": top, "monthly_avg": monthly_avg}


def compute_yearly(scored):
    yearly = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in scored:
        year = int(r["time"][:4])
        yearly[year][r["overall"]] += 1
    result = {}
    for y in sorted(yearly.keys()):
        total = sum(yearly[y].values())
        result[y] = {k: round(v / total * 100, 1) for k, v in yearly[y].items()}
    return result


def compute_heatmap(scored):
    """Month x Hour heatmap of % green."""
    grid = defaultdict(lambda: {"green": 0, "total": 0})
    for r in scored:
        month = int(r["time"][5:7])
        hour = int(r["time"][11:13])
        key = (month, hour)
        grid[key]["total"] += 1
        if r["overall"] == 0:
            grid[key]["green"] += 1
    result = {}
    for m in range(1, 13):
        result[m] = {}
        for h in range(24):
            cell = grid[(m, h)]
            if cell["total"] > 0:
                result[m][h] = round(cell["green"] / cell["total"] * 100, 1)
            else:
                result[m][h] = 0
    return result


# ── HTML Report Generation ─────────────────────────────────────────────────

def generate_html(analysis):
    overall = analysis["overall"]
    monthly = analysis["monthly"]
    hourly = analysis["hourly"]
    profile = analysis["daily_profile"]
    drivers = analysis["drivers"]
    duration = analysis["duration"]
    best = analysis["best_windows"]
    yearly = analysis["yearly"]
    heatmap = analysis["heatmap"]

    # Find dominant driver
    d = drivers["drivers"]
    dominant = max(d, key=d.get)

    # Best/worst months
    month_greens = [(m, monthly[m][0]) for m in range(1, 13)]
    best_month = max(month_greens, key=lambda x: x[1])
    worst_month = min(month_greens, key=lambda x: x[1])

    # Best/worst hours
    hour_greens = [(h, hourly[h][0]) for h in range(24)]
    best_hour = max(hour_greens, key=lambda x: x[1])
    worst_hour = min(hour_greens, key=lambda x: x[1])

    # Top windows table rows
    top_rows = ""
    for i, w in enumerate(best["top"]):
        start_dt = w["start"].replace("T", " ")
        end_dt = w["end"].replace("T", " ")
        top_rows += f'<tr><td>{i+1}</td><td>{start_dt}</td><td>{end_dt}</td><td><strong>{w["hours"]}h</strong></td></tr>\n'

    # Duration stats table
    dur_rows = ""
    for status, label, color in [(0, "Safe (Green)", COLORS["green"]),
                                  (1, "Caution (Yellow)", COLORS["yellow"]),
                                  (2, "Unsafe (Red)", COLORS["red"])]:
        s = duration["stats"][status]
        dur_rows += f'''<tr>
            <td><span class="status-dot" style="background:{color}"></span>{label}</td>
            <td>{s["count"]}</td><td>{s["min"]}h</td><td>{s["median"]}h</td>
            <td>{s["mean"]}h</td><td>{s["p90"]}h</td><td>{s["max"]}h</td>
        </tr>\n'''

    # Pre-build heatmap HTML
    heatmap_hours_html = "".join(f'<div class="hm-hour">{h}</div>' for h in range(24))
    heatmap_rows_html = ""
    for m in range(1, 13):
        heatmap_rows_html += f'<div class="hm-label">{MONTH_NAMES[m-1]}</div>'
        for h in range(24):
            v = heatmap[m][h]
            c = heatmap_color(v)
            heatmap_rows_html += f'<div class="hm-cell" style="background:{c}">{v:.0f}</div>'

    generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    year_span = int(END_DATE[:4]) - int(START_DATE[:4]) + 1

    # Driver percentages for inline text
    d_total = drivers["total"]
    d_pcts = {k: round(v / d_total * 100, 1) if d_total else 0 for k, v in d.items()}

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historical Burn Conditions Report — Belize</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Source+Sans+3:ital,wght@0,300;0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    font-family: 'Source Sans 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #fff;
    color: #1a1a1a;
    line-height: 1.75;
    -webkit-font-smoothing: antialiased;
    font-size: 18px;
}}

a {{ color: #005BBB; }}

/* ── Page wrapper ── */
.page {{
    max-width: 880px;
    margin: 0 auto;
    padding: 0 40px;
}}
.page-wide {{
    max-width: 1060px;
    margin: 0 auto;
    padding: 0 40px;
}}

/* ── Cover ── */
.cover {{
    padding: 80px 0 60px;
    border-bottom: 1px solid #ddd;
    position: relative;
}}
.cover-logo {{
    position: absolute;
    top: 80px;
    right: 0;
}}
.cover-logo img {{
    height: 56px;
    width: auto;
}}
.cover h1 {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 3rem;
    font-weight: 900;
    color: #005BBB;
    line-height: 1.1;
    margin-bottom: 16px;
    max-width: 70%;
}}
.cover .lead {{
    font-size: 1.2rem;
    font-weight: 300;
    color: #5e6a71;
    line-height: 1.6;
    max-width: 65%;
    margin-bottom: 28px;
}}
.cover .accent {{
    width: 60px;
    height: 3px;
    background: #D4982A;
}}
.cover .meta {{
    margin-top: 20px;
    font-size: 0.82rem;
    color: #5e6a71;
}}
.cover-series {{
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2.5px;
    color: #D4982A;
    margin-bottom: 14px;
}}

/* ── Section headings (Rare interior style: ALL-CAPS sans-serif) ── */
.sec {{
    padding: 72px 0 0;
}}
.sec-head {{
    font-family: 'Source Sans 3', sans-serif;
    font-size: 2.25rem;
    font-weight: 900;
    color: #1a1a1a;
    margin-bottom: 12px;
    line-height: 1.2;
}}
.sec-rule {{
    width: 100%;
    height: 1px;
    background: #ddd;
    margin-bottom: 28px;
}}
.sec p {{
    color: #4a4a4a;
    margin-bottom: 20px;
    max-width: 720px;
}}
.sec p strong {{ color: #1a1a1a; }}

/* ── Figures (charts) ── */
figure {{
    margin: 32px 0 16px;
}}
figure figcaption {{
    font-size: 0.82rem;
    color: #8a9299;
    margin-top: 8px;
    font-style: italic;
}}
.chart-container {{
    position: relative;
    width: 100%;
    max-height: 380px;
}}
.chart-container canvas {{
    max-height: 380px;
}}

/* ── Stat row (replaces colored cards) ── */
.stat-row {{
    display: flex;
    gap: 48px;
    margin: 40px 0;
    padding: 40px 0 36px;
}}
.stat-item {{
    flex: 1;
}}
.stat-num {{
    font-family: 'Source Sans 3', sans-serif;
    font-size: 3.4rem;
    font-weight: 900;
    line-height: 1;
    color: #1a1a1a;
    display: flex;
    align-items: baseline;
    gap: 12px;
}}
.stat-num .dot {{
    width: 14px;
    height: 14px;
    border-radius: 50%;
    flex-shrink: 0;
    position: relative;
    top: -4px;
}}
.stat-label {{
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #5e6a71;
    margin-top: 8px;
}}
.stat-sub {{
    font-size: 0.85rem;
    color: #8a9299;
    margin-top: 2px;
}}

/* ── Pull-quote / callout ── */
.pull-quote {{
    border-left: 4px solid #D4982A;
    padding: 20px 0 20px 28px;
    margin: 36px 0;
    font-size: 1.05rem;
    line-height: 1.7;
    color: #4a4a4a;
}}
.pull-quote strong {{
    color: #1a1a1a;
}}
.pull-quote .pq-label {{
    display: block;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #D4982A;
    margin-bottom: 8px;
}}

/* ── Two-column layout ── */
.two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 56px;
    margin-top: 28px;
}}

/* ── Sub-headings within sections ── */
.sub-head {{
    font-size: 0.82rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #5e6a71;
    margin-bottom: 16px;
}}

/* ── Tables ── */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    margin-top: 12px;
}}
.data-table thead th {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid #ddd;
    font-weight: 700;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #1a1a1a;
}}
.data-table td {{
    padding: 9px 12px;
    border-bottom: 1px solid #eee;
    color: #4a4a4a;
}}
.data-table tbody tr:last-child td {{ border-bottom: none; }}

.status-dot {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
}}

/* ── Heatmap ── */
.hm-grid {{
    display: grid;
    grid-template-columns: 52px repeat(24, 1fr);
    gap: 2px;
    margin-top: 20px;
}}
.hm-cell {{
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 2px;
    font-weight: 600;
    font-size: 0.6rem;
    min-height: 26px;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.2);
}}
.hm-label {{
    display: flex;
    align-items: center;
    font-weight: 600;
    font-size: 0.78rem;
    color: #5e6a71;
    padding-right: 6px;
    justify-content: flex-end;
}}
.hm-hour {{
    text-align: center;
    font-weight: 600;
    color: #8a9299;
    font-size: 0.65rem;
    padding-bottom: 4px;
}}

/* ── Footer ── */
.report-footer {{
    margin-top: 80px;
    padding: 28px 0 60px;
    border-top: 1px solid #ddd;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
}}
.footer-text {{
    font-size: 0.78rem;
    color: #8a9299;
    line-height: 1.8;
}}
.footer-logo img {{
    height: 36px;
    width: auto;
    opacity: 1;
}}

/* ── Responsive ── */
@media (max-width: 768px) {{
    .page, .page-wide {{ padding: 0 20px; }}
    .cover h1 {{ font-size: 2rem; max-width: 100%; }}
    .cover .lead {{ max-width: 100%; }}
    .cover-logo {{ position: static; margin-bottom: 24px; }}
    .stat-row {{ flex-direction: column; gap: 24px; }}
    .two-col {{ grid-template-columns: 1fr; }}
    .hm-grid {{ overflow-x: auto; }}
}}

@media print {{
    .sec {{ break-inside: avoid; }}
    .page, .page-wide {{ max-width: 100%; }}
}}
</style>
</head>
<body>

<div class="page">

<!-- Cover -->
<div class="cover">
    <div class="cover-logo"><img src="rare-logo.png" alt="Rare — Center for Behavior &amp; the Environment"></div>
    <div class="cover-series">Research Report</div>
    <h1>Historical Burn<br>Conditions Report</h1>
    <p class="lead">Making the Case for Informed Burning Practices in the Belize Maya Forest Region</p>
    <div class="accent"></div>
    <p class="meta">{LAT}°N, {abs(LON)}°W &nbsp;&middot;&nbsp; {START_DATE[:4]}–{END_DATE[:4]} &nbsp;&middot;&nbsp; {overall["total"]:,} hourly observations</p>
</div>

<!-- Executive Summary -->
<div class="sec">
    <h2 class="sec-head">Executive Summary</h2>
    <div class="sec-rule"></div>

    <p>This report analyzes {year_span} years of hourly weather data ({overall["total"]:,} observations) to characterize burn safety conditions at the Belize study site. Each hour is classified as <strong>safe</strong> (green), <strong>caution</strong> (yellow), or <strong>unsafe</strong> (red) based on humidity, wind speed, and temperature thresholds.</p>

    <div class="stat-row">
        <div class="stat-item">
            <div class="stat-num"><span class="dot" style="background:{COLORS['green']}"></span>{overall["pcts"][0]}%</div>
            <div class="stat-label">Safe to Burn</div>
            <div class="stat-sub">{overall["counts"][0]:,} hours</div>
        </div>
        <div class="stat-item">
            <div class="stat-num"><span class="dot" style="background:{COLORS['yellow']}"></span>{overall["pcts"][1]}%</div>
            <div class="stat-label">Use Caution</div>
            <div class="stat-sub">{overall["counts"][1]:,} hours</div>
        </div>
        <div class="stat-item">
            <div class="stat-num"><span class="dot" style="background:{COLORS['red']}"></span>{overall["pcts"][2]}%</div>
            <div class="stat-label">Do Not Burn</div>
            <div class="stat-sub">{overall["counts"][2]:,} hours</div>
        </div>
    </div>

    <div class="pull-quote">
        <span class="pq-label">Key Finding</span>
        <strong>{dominant.capitalize()}</strong> is the primary driver of unsafe conditions, responsible for triggering caution or danger in {d[dominant]:,} of {drivers["total"]:,} non-green hours ({d_pcts[dominant]}%). The safest month is <strong>{MONTH_NAMES[best_month[0]-1]}</strong> ({best_month[1]}% green) and the riskiest is <strong>{MONTH_NAMES[worst_month[0]-1]}</strong> ({worst_month[1]}% green). Within a typical day, <strong>{best_hour[0]}:00</strong> is the safest hour ({best_hour[1]}% green) and <strong>{worst_hour[0]}:00</strong> the riskiest ({worst_hour[1]}% green).
    </div>
</div>

</div><!-- /page -->
<div class="page-wide">

<!-- Monthly Seasonality -->
<div class="sec">
    <h2 class="sec-head">Monthly Seasonality</h2>
    <div class="sec-rule"></div>
    <p>The distribution of burn safety conditions varies dramatically by season. The chart below shows the percentage of hours at each safety level for every month, averaged across all {year_span} years.</p>
    <figure>
        <div class="chart-container"><canvas id="monthlyChart"></canvas></div>
        <figcaption>Figure 1. Monthly distribution of burn safety conditions, {START_DATE[:4]}–{END_DATE[:4]}. Best month: {MONTH_NAMES[best_month[0]-1]} ({best_month[1]}% safe). Worst: {MONTH_NAMES[worst_month[0]-1]} ({worst_month[1]}% safe).</figcaption>
    </figure>
</div>

<!-- Time of Day -->
<div class="sec">
    <h2 class="sec-head">Time-of-Day Patterns</h2>
    <div class="sec-rule"></div>
    <p>Burn safety conditions shift substantially throughout the day. Early morning hours offer the highest likelihood of safe conditions, while midday is consistently the riskiest period.</p>
    <figure>
        <div class="chart-container"><canvas id="hourlyChart"></canvas></div>
        <figcaption>Figure 2. Hourly distribution of burn safety conditions across all days. Safest hour: {best_hour[0]}:00 ({best_hour[1]}% safe). Riskiest: {worst_hour[0]}:00 ({worst_hour[1]}% safe).</figcaption>
    </figure>
</div>

<!-- Typical Day Profile -->
<div class="sec">
    <h2 class="sec-head">Typical Day Weather Profile</h2>
    <div class="sec-rule"></div>
    <p>The chart below shows average temperature, humidity, and wind speed by hour of day, illustrating the underlying weather dynamics that drive the safety classifications.</p>
    <figure>
        <div class="chart-container"><canvas id="profileChart"></canvas></div>
        <figcaption>Figure 3. Mean hourly weather conditions across the full dataset.</figcaption>
    </figure>
</div>

<!-- Drivers + Duration side by side -->
<div class="sec">
    <h2 class="sec-head">Risk Factors &amp; Duration</h2>
    <div class="sec-rule"></div>
    <p>When conditions are classified as caution or unsafe, which weather metric is driving the classification? And how long do these conditions typically persist?</p>
    <div class="two-col">
        <div>
            <div class="sub-head">What Drives Unsafe Conditions?</div>
            <figure>
                <div class="chart-container" style="max-height:280px"><canvas id="driverChart"></canvas></div>
                <figcaption>Figure 4. Frequency of each metric as the binding constraint in non-green hours. Multiple metrics may co-drive a single hour.</figcaption>
            </figure>
        </div>
        <div>
            <div class="sub-head">Consecutive Hours at Each Level</div>
            <table class="data-table">
                <thead><tr><th>Status</th><th>Episodes</th><th>Min</th><th>Median</th><th>Mean</th><th>P90</th><th>Max</th></tr></thead>
                <tbody>{dur_rows}</tbody>
            </table>
            <figure style="margin-top:20px">
                <div class="chart-container" style="max-height:220px"><canvas id="durationChart"></canvas></div>
                <figcaption>Figure 5. Distribution of safe-window durations.</figcaption>
            </figure>
        </div>
    </div>
</div>

<!-- Best Burning Windows -->
<div class="sec">
    <h2 class="sec-head">Optimal Burning Windows</h2>
    <div class="sec-rule"></div>
    <p>To help plan extended burn operations, this section examines the length of consecutive safe-condition windows — both the seasonal averages and the all-time longest recorded periods.</p>
    <div class="two-col">
        <div>
            <div class="sub-head">Avg. Longest Safe Window by Month</div>
            <figure>
                <div class="chart-container" style="max-height:280px"><canvas id="windowChart"></canvas></div>
                <figcaption>Figure 6. Average length (hours) of the longest consecutive safe window per month.</figcaption>
            </figure>
        </div>
        <div>
            <div class="sub-head">Top 10 Longest Safe Windows on Record</div>
            <table class="data-table">
                <thead><tr><th>#</th><th>Start</th><th>End</th><th>Duration</th></tr></thead>
                <tbody>{top_rows}</tbody>
            </table>
        </div>
    </div>
</div>

<!-- Year Trends -->
<div class="sec">
    <h2 class="sec-head">Year-over-Year Trends</h2>
    <div class="sec-rule"></div>
    <p>Are conditions improving or worsening over time? The chart below shows the annual percentage of hours at each safety level from {START_DATE[:4]} to {END_DATE[:4]}.</p>
    <figure>
        <div class="chart-container"><canvas id="yearlyChart"></canvas></div>
        <figcaption>Figure 7. Annual distribution of burn safety conditions.</figcaption>
    </figure>
</div>

<!-- Heatmap -->
<div class="sec">
    <h2 class="sec-head">Month × Hour Quick Reference</h2>
    <div class="sec-rule"></div>
    <p>The heatmap below shows the percentage of safe (green) hours at each month/hour combination. This is the single most useful reference for planning: <strong>darker green means more reliably safe</strong>.</p>
    <div class="hm-grid">
        <div></div>
        {heatmap_hours_html}
        {heatmap_rows_html}
    </div>
</div>

</div><!-- /page-wide -->
<div class="page">

<!-- Methodology -->
<div class="sec" style="padding-bottom:0">
    <h2 class="sec-head">Methodology</h2>
    <div class="sec-rule"></div>
    <p>This report analyzes {overall["total"]:,} hourly weather observations from {START_DATE} to {END_DATE} at coordinates {LAT}°N, {abs(LON)}°W (Belize). Data sourced from the <a href="https://open-meteo.com">Open-Meteo Archive API</a> (ERA5 reanalysis). Scoring thresholds: <strong>Humidity</strong> (&gt;40% safe, 30–40% caution, &lt;30% danger), <strong>Wind</strong> (&lt;5 mph safe, 5–10 caution, &gt;10 danger), <strong>Temperature</strong> (&lt;80°F safe, 80–90° caution, &gt;90° danger). Overall status is the worst of the three metrics.</p>
</div>

<!-- Footer -->
<div class="report-footer">
    <div class="footer-text">
        Data: Open-Meteo Archive API (ERA5 Reanalysis)<br>
        Generated {generated}
    </div>
    <div class="footer-logo"><img src="rare-logo.png" alt="Rare"></div>
</div>

</div><!-- /page -->

<script>
const MONTHS = {json.dumps(MONTH_NAMES)};
const GREEN = '{COLORS["green"]}';
const YELLOW = '{COLORS["yellow"]}';
const RED = '{COLORS["red"]}';
const BLUE = '#005BBB';
const GOLD = '#F58233';
const TEAL = '#008542';

const monthlyData = {json.dumps({str(m): monthly[m] for m in range(1,13)})};
const hourlyData = {json.dumps({str(h): hourly[h] for h in range(24)})};
const profileData = {json.dumps({str(h): profile[h] for h in range(24)})};
const driverData = {json.dumps(drivers["drivers"])};
const greenBins = {json.dumps(duration["green_bins"])};
const windowData = {json.dumps({str(m): best["monthly_avg"][m] for m in range(1,13)})};
const yearlyData = {json.dumps(yearly)};

Chart.defaults.font.family = "'Source Sans 3', sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = '#8a9299';

function stackedOpts() {{
    return {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 11 }} }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%' }} }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ stacked: true, max: 100, ticks: {{ callback: v => v + '%' }}, grid: {{ color: '#f5f5f5' }} }}
        }}
    }};
}}

new Chart(document.getElementById('monthlyChart'), {{
    type: 'bar',
    data: {{
        labels: MONTHS,
        datasets: [
            {{ label: 'Safe', data: MONTHS.map((_,i) => monthlyData[String(i+1)]['0']), backgroundColor: GREEN }},
            {{ label: 'Caution', data: MONTHS.map((_,i) => monthlyData[String(i+1)]['1']), backgroundColor: YELLOW }},
            {{ label: 'Danger', data: MONTHS.map((_,i) => monthlyData[String(i+1)]['2']), backgroundColor: RED }},
        ]
    }},
    options: {{ ...stackedOpts(), scales: {{ ...stackedOpts().scales, x: {{ stacked: true, grid: {{ display: false }} }} }} }}
}});

new Chart(document.getElementById('hourlyChart'), {{
    type: 'line',
    data: {{
        labels: Array.from({{length:24}}, (_,i) => i + ':00'),
        datasets: [
            {{ label: 'Safe', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['0']), backgroundColor: GREEN+'30', borderColor: GREEN, fill: true, tension: 0.3, borderWidth: 2 }},
            {{ label: 'Caution', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['1']), backgroundColor: YELLOW+'30', borderColor: YELLOW, fill: true, tension: 0.3, borderWidth: 2 }},
            {{ label: 'Danger', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['2']), backgroundColor: RED+'30', borderColor: RED, fill: true, tension: 0.3, borderWidth: 2 }},
        ]
    }},
    options: stackedOpts()
}});

new Chart(document.getElementById('profileChart'), {{
    type: 'line',
    data: {{
        labels: Array.from({{length:24}}, (_,i) => i + ':00'),
        datasets: [
            {{ label: 'Humidity (%)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].humid), borderColor: BLUE, backgroundColor: BLUE+'10', borderWidth: 2, tension: 0.3, yAxisID: 'y', pointRadius: 3 }},
            {{ label: 'Temperature (°F)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].temp), borderColor: GOLD, backgroundColor: GOLD+'10', borderWidth: 2, tension: 0.3, yAxisID: 'y', pointRadius: 3 }},
            {{ label: 'Wind (mph)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].wind), borderColor: TEAL, backgroundColor: TEAL+'10', borderWidth: 2, tension: 0.3, yAxisID: 'y2', pointRadius: 3 }},
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 11 }} }} }} }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ position: 'left', title: {{ display: true, text: 'Humidity (%) / Temp (°F)', color: '#aaa', font: {{ size: 11 }} }}, grid: {{ color: '#f5f5f5' }} }},
            y2: {{ position: 'right', title: {{ display: true, text: 'Wind (mph)', color: '#aaa', font: {{ size: 11 }} }}, grid: {{ display: false }}, min: 0 }}
        }}
    }}
}});

new Chart(document.getElementById('driverChart'), {{
    type: 'doughnut',
    data: {{
        labels: ['Humidity', 'Wind', 'Temperature'],
        datasets: [{{ data: [driverData.humidity, driverData.wind, driverData.temperature], backgroundColor: [BLUE, TEAL, GOLD], borderWidth: 0, hoverOffset: 6 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'bottom', labels: {{ usePointStyle: true, padding: 14, font: {{ size: 11 }} }} }},
            tooltip: {{ callbacks: {{ label: ctx => {{ const t = ctx.dataset.data.reduce((a,b)=>a+b,0); return ctx.label+': '+ctx.raw.toLocaleString()+' ('+(ctx.raw/t*100).toFixed(1)+'%)'; }} }} }}
        }},
        cutout: '55%',
    }}
}});

new Chart(document.getElementById('durationChart'), {{
    type: 'bar',
    data: {{
        labels: Object.keys(greenBins),
        datasets: [{{ data: Object.values(greenBins), backgroundColor: TEAL, borderRadius: 3 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ title: {{ display: true, text: 'Count', color: '#aaa', font: {{ size: 11 }} }}, grid: {{ color: '#f5f5f5' }} }} }}
    }}
}});

new Chart(document.getElementById('windowChart'), {{
    type: 'bar',
    data: {{
        labels: MONTHS,
        datasets: [{{ data: MONTHS.map((_,i) => windowData[String(i+1)]), backgroundColor: BLUE, borderRadius: 3 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ title: {{ display: true, text: 'Hours', color: '#aaa', font: {{ size: 11 }} }}, grid: {{ color: '#f5f5f5' }} }} }}
    }}
}});

const years = Object.keys(yearlyData).sort();
new Chart(document.getElementById('yearlyChart'), {{
    type: 'line',
    data: {{
        labels: years,
        datasets: [
            {{ label: 'Safe %', data: years.map(y => yearlyData[y]['0']), borderColor: GREEN, backgroundColor: GREEN+'12', fill: true, tension: 0.3, borderWidth: 2 }},
            {{ label: 'Caution %', data: years.map(y => yearlyData[y]['1']), borderColor: YELLOW, backgroundColor: YELLOW+'12', fill: true, tension: 0.3, borderWidth: 2 }},
            {{ label: 'Danger %', data: years.map(y => yearlyData[y]['2']), borderColor: RED, backgroundColor: RED+'12', fill: true, tension: 0.3, borderWidth: 2 }},
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 11 }} }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%' }} }}
        }},
        scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ max: 100, ticks: {{ callback: v => v + '%' }}, grid: {{ color: '#f5f5f5' }} }} }}
    }}
}});
</script>

</body>
</html>"""
    return html


def heatmap_color(pct):
    """Return a color for heatmap cell based on % green."""
    if pct >= 80:
        return "#15712a"
    elif pct >= 60:
        return "#22b740"
    elif pct >= 40:
        return "#6abf69"
    elif pct >= 25:
        return "#e6a800"
    elif pct >= 10:
        return "#d47800"
    else:
        return "#d93030"


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    raw = fetch_data()

    print("Scoring all hours...")
    scored = score_all(
        raw["hourly"]["time"],
        raw["hourly"]["temperature_2m"],
        raw["hourly"]["relative_humidity_2m"],
        raw["hourly"]["wind_speed_10m"],
    )
    del raw

    print("Computing analysis...")
    analysis = {
        "overall": compute_overall(scored),
        "monthly": compute_monthly(scored),
        "hourly": compute_hourly_patterns(scored),
        "daily_profile": compute_daily_profile(scored),
        "drivers": compute_drivers(scored),
        "duration": compute_duration(scored),
        "best_windows": compute_best_windows(scored),
        "yearly": compute_yearly(scored),
        "heatmap": compute_heatmap(scored),
    }

    # Sanity checks
    o = analysis["overall"]
    print(f"  Overall: {o['pcts'][0]}% green, {o['pcts'][1]}% yellow, {o['pcts'][2]}% red")
    total_pct = sum(o["pcts"].values())
    assert 99.5 < total_pct < 100.5, f"Percentages sum to {total_pct}, expected ~100"

    print("Generating HTML report...")
    html = generate_html(analysis)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Report written to {OUTPUT_FILE}")
    print(f"Open: file://{OUTPUT_FILE.resolve()}")
