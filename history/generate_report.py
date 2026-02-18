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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historical Burn Conditions Report — Belize</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Source+Sans+3:wght@300;400;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    font-family: 'Source Sans 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #F5F5F3;
    color: #333;
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
}}

/* ── Header ── */
.report-header {{
    background: #fff;
    padding: 40px 48px 36px;
    max-width: 1100px;
    margin: 0 auto;
    position: relative;
}}
.header-logo {{
    position: absolute;
    top: 40px;
    right: 48px;
}}
.header-logo img {{
    height: 60px;
    width: auto;
}}
.report-header h1 {{
    font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
    font-size: 2.8rem;
    font-weight: 900;
    color: #0067B1;
    line-height: 1.15;
    margin-bottom: 12px;
    max-width: 75%;
}}
.report-header .subtitle {{
    font-size: 1.15rem;
    font-weight: 300;
    color: #666;
    line-height: 1.5;
    max-width: 70%;
}}
.header-accent {{
    width: 80px;
    height: 4px;
    background: #D4982A;
    margin-top: 20px;
    border-radius: 2px;
}}
.header-meta {{
    margin-top: 16px;
    font-size: 0.85rem;
    color: #999;
    font-weight: 400;
}}

/* ── Container ── */
.container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 0;
}}

/* ── Section ── */
.section {{
    background: #fff;
    padding: 56px 48px;
    margin-top: 2px;
}}
.section h2 {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.9rem;
    font-weight: 700;
    color: #0067B1;
    margin-bottom: 4px;
    line-height: 1.2;
}}
.section-sub {{
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #999;
    margin-bottom: 8px;
}}
.section-rule {{
    width: 100%;
    height: 1px;
    background: #e0e0e0;
    margin: 12px 0 28px;
}}
.section-desc {{
    font-size: 1rem;
    color: #555;
    margin-bottom: 32px;
    line-height: 1.7;
    max-width: 800px;
}}

/* ── Executive Summary Stats ── */
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    margin-bottom: 32px;
}}
.stat-card {{
    text-align: center;
    padding: 32px 16px;
    border-radius: 8px;
    color: #fff;
}}
.stat-card.green {{ background: {COLORS["green"]}; }}
.stat-card.yellow {{ background: {COLORS["yellow"]}; }}
.stat-card.red {{ background: {COLORS["red"]}; }}
.stat-card .pct {{
    font-family: 'Playfair Display', serif;
    font-size: 3.2rem;
    font-weight: 900;
    line-height: 1;
    margin-bottom: 6px;
}}
.stat-card .label {{
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    opacity: 0.9;
}}
.stat-card .count {{
    font-size: 0.8rem;
    opacity: 0.75;
    margin-top: 4px;
}}

/* ── Key Finding (gold callout) ── */
.callout {{
    background: #D4982A;
    color: #fff;
    padding: 24px 28px;
    border-radius: 6px;
    font-size: 1rem;
    line-height: 1.7;
}}
.callout strong {{
    display: block;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 8px;
    opacity: 0.85;
}}
.callout em {{ font-style: normal; font-weight: 700; }}

/* ── Charts ── */
.chart-container {{
    position: relative;
    width: 100%;
    max-height: 400px;
}}
.chart-container canvas {{
    max-height: 400px;
}}

/* ── Two-column layout ── */
.two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 48px;
}}

/* ── Tables ── */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    margin-top: 16px;
}}
.data-table thead th {{
    text-align: left;
    padding: 12px 14px;
    background: #009966;
    color: #fff;
    font-weight: 600;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.data-table thead th:first-child {{
    border-radius: 4px 0 0 0;
}}
.data-table thead th:last-child {{
    border-radius: 0 4px 0 0;
}}
.data-table td {{
    padding: 11px 14px;
    border-bottom: 1px solid #e8e8e8;
    color: #444;
}}
.data-table tbody tr:nth-child(even) td {{
    background: #f9f9f7;
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
    font-size: 0.7rem;
    margin-top: 16px;
}}
.hm-cell {{
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 3px;
    font-weight: 600;
    font-size: 0.62rem;
    min-height: 28px;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.25);
}}
.hm-label {{
    display: flex;
    align-items: center;
    font-weight: 600;
    font-size: 0.78rem;
    color: #666;
    padding-right: 6px;
    justify-content: flex-end;
}}
.hm-hour {{
    text-align: center;
    font-weight: 600;
    color: #999;
    font-size: 0.68rem;
    padding-bottom: 4px;
}}

/* ── Insight pills ── */
.insight {{
    display: inline-block;
    background: #EBF3FA;
    border: 1px solid #C8DCF0;
    border-radius: 4px;
    padding: 8px 14px;
    font-size: 0.88rem;
    color: #0067B1;
    margin: 4px 6px 4px 0;
}}

/* ── Section sub-headings ── */
.section h3 {{
    font-family: 'Source Sans 3', sans-serif;
    font-size: 0.95rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #666;
    margin-bottom: 16px;
}}

/* ── Footer ── */
.report-footer {{
    max-width: 1100px;
    margin: 0 auto;
    background: #fff;
    margin-top: 2px;
    padding: 36px 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
.footer-text {{
    font-size: 0.82rem;
    color: #999;
    line-height: 1.8;
}}
.footer-logo img {{
    height: 40px;
    width: auto;
    opacity: 0.6;
}}

/* ── Responsive ── */
@media (max-width: 768px) {{
    .report-header {{ padding: 28px 20px 24px; }}
    .report-header h1 {{ font-size: 1.8rem; max-width: 100%; }}
    .report-header .subtitle {{ max-width: 100%; }}
    .header-logo {{ position: static; margin-bottom: 20px; }}
    .section {{ padding: 36px 20px; }}
    .summary-grid {{ grid-template-columns: 1fr; }}
    .two-col {{ grid-template-columns: 1fr; }}
    .hm-grid {{ overflow-x: auto; }}
    .report-footer {{ flex-direction: column; gap: 16px; text-align: center; padding: 24px 20px; }}
}}

@media print {{
    body {{ background: #fff; }}
    .section {{ box-shadow: none; break-inside: avoid; }}
}}
</style>
</head>
<body>

<div class="container">

<!-- Header -->
<div class="report-header">
    <div class="header-logo"><img src="rare-logo.png" alt="Rare — Center for Behavior &amp; the Environment"></div>
    <h1>Historical Burn Conditions Report</h1>
    <div class="subtitle">Making the Case for Informed Burning Practices<br>in the Belize Maya Forest Region</div>
    <div class="header-accent"></div>
    <div class="header-meta">{LAT}°N, {abs(LON)}°W &nbsp;·&nbsp; {START_DATE[:4]}–{END_DATE[:4]} &nbsp;·&nbsp; {overall["total"]:,} hourly observations &nbsp;·&nbsp; Generated {generated}</div>
</div>

<!-- Executive Summary -->
<div class="section">
    <div class="section-sub">Overview</div>
    <h2>Executive Summary</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Overall distribution of burn safety conditions across {int(END_DATE[:4]) - int(START_DATE[:4]) + 1} years of hourly weather data at the Belize study site.</p>
    <div class="summary-grid">
        <div class="stat-card green">
            <div class="pct">{overall["pcts"][0]}%</div>
            <div class="label">Safe to Burn</div>
            <div class="count">{overall["counts"][0]:,} hours</div>
        </div>
        <div class="stat-card yellow">
            <div class="pct">{overall["pcts"][1]}%</div>
            <div class="label">Use Caution</div>
            <div class="count">{overall["counts"][1]:,} hours</div>
        </div>
        <div class="stat-card red">
            <div class="pct">{overall["pcts"][2]}%</div>
            <div class="label">Do Not Burn</div>
            <div class="count">{overall["counts"][2]:,} hours</div>
        </div>
    </div>
    <div class="callout">
        <strong>Key Finding</strong>
        <em>{dominant.capitalize()}</em> is the primary driver of unsafe conditions,
        responsible for triggering caution or danger in {d[dominant]:,} of {drivers["total"]:,} non-green hours.
        The safest month is <em>{MONTH_NAMES[best_month[0]-1]}</em> ({best_month[1]}% green) and the riskiest is
        <em>{MONTH_NAMES[worst_month[0]-1]}</em> ({worst_month[1]}% green).
        Within a typical day, <em>{best_hour[0]}:00</em> is the safest hour ({best_hour[1]}% green)
        and <em>{worst_hour[0]}:00</em> is the riskiest ({worst_hour[1]}% green).
    </div>
</div>

<!-- Monthly Seasonality -->
<div class="section">
    <div class="section-sub">Seasonality</div>
    <h2>Monthly Patterns</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Percentage of hours at each safety level by month. Identifies the best and worst months for agricultural burning.</p>
    <div class="chart-container"><canvas id="monthlyChart"></canvas></div>
    <div style="margin-top:20px">
        <span class="insight">Best month: <strong>{MONTH_NAMES[best_month[0]-1]}</strong> — {best_month[1]}% safe</span>
        <span class="insight">Worst month: <strong>{MONTH_NAMES[worst_month[0]-1]}</strong> — {worst_month[1]}% safe</span>
    </div>
</div>

<!-- Time of Day -->
<div class="section">
    <div class="section-sub">Diurnal Cycle</div>
    <h2>Time-of-Day Patterns</h2>
    <div class="section-rule"></div>
    <p class="section-desc">How burn safety conditions shift throughout a 24-hour cycle, averaged across all days in the dataset.</p>
    <div class="chart-container"><canvas id="hourlyChart"></canvas></div>
    <div style="margin-top:20px">
        <span class="insight">Safest hour: <strong>{best_hour[0]}:00</strong> — {best_hour[1]}% safe</span>
        <span class="insight">Riskiest hour: <strong>{worst_hour[0]}:00</strong> — {worst_hour[1]}% safe</span>
    </div>
</div>

<!-- Typical Day Profile -->
<div class="section">
    <div class="section-sub">Weather Profile</div>
    <h2>Typical Day Weather Profile</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Average temperature, humidity, and wind speed by hour of day across all years in the dataset.</p>
    <div class="chart-container"><canvas id="profileChart"></canvas></div>
</div>

<!-- Two-column: Drivers + Duration -->
<div class="section">
    <div class="two-col">
        <div>
            <div class="section-sub">Risk Factors</div>
            <h2 style="font-size:1.5rem">What Drives Unsafe Conditions?</h2>
            <div class="section-rule"></div>
            <p class="section-desc">When conditions are yellow or red, which weather metric is responsible?</p>
            <div class="chart-container" style="max-height:300px"><canvas id="driverChart"></canvas></div>
            <div style="margin-top:12px; font-size:0.85rem; color:#888">
                Note: Multiple metrics can co-drive a single hour's status.
            </div>
        </div>
        <div>
            <div class="section-sub">Duration Analysis</div>
            <h2 style="font-size:1.5rem">How Long Do Conditions Last?</h2>
            <div class="section-rule"></div>
            <p class="section-desc">Statistics on consecutive hours at each safety level.</p>
            <table class="data-table">
                <thead><tr><th>Status</th><th>Runs</th><th>Min</th><th>Median</th><th>Mean</th><th>P90</th><th>Max</th></tr></thead>
                <tbody>{dur_rows}</tbody>
            </table>
            <div style="margin-top:24px">
                <div class="chart-container" style="max-height:250px"><canvas id="durationChart"></canvas></div>
            </div>
        </div>
    </div>
</div>

<!-- Best Burning Windows -->
<div class="section">
    <div class="section-sub">Optimal Windows</div>
    <h2>Best Burning Windows</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Average length of the longest safe (green) window by month, and the top 10 longest safe windows ever recorded.</p>
    <div class="two-col">
        <div>
            <h3>Avg. Longest Green Window by Month</h3>
            <div class="chart-container" style="max-height:300px"><canvas id="windowChart"></canvas></div>
        </div>
        <div>
            <h3>Top 10 Longest Safe Windows</h3>
            <table class="data-table">
                <thead><tr><th>#</th><th>Start</th><th>End</th><th>Duration</th></tr></thead>
                <tbody>{top_rows}</tbody>
            </table>
        </div>
    </div>
</div>

<!-- Year Trends -->
<div class="section">
    <div class="section-sub">Trends</div>
    <h2>Year-over-Year Trends</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Annual percentage of safe hours from {START_DATE[:4]} to {END_DATE[:4]}. Shows whether conditions are trending better or worse over the decade.</p>
    <div class="chart-container"><canvas id="yearlyChart"></canvas></div>
</div>

<!-- Heatmap -->
<div class="section">
    <div class="section-sub">Quick Reference</div>
    <h2>Month × Hour Heatmap</h2>
    <div class="section-rule"></div>
    <p class="section-desc">Percentage of safe (green) hours at each month/hour combination. Darker green = more often safe. This is the quick-reference guide for planning burns.</p>
    <div class="hm-grid">
        <div></div>
        {heatmap_hours_html}
        {heatmap_rows_html}
    </div>
</div>

<!-- Methodology -->
<div class="section" style="background:#F5F5F3">
    <div class="section-sub">Appendix</div>
    <h2 style="font-size:1.4rem">Methodology</h2>
    <div class="section-rule"></div>
    <p class="section-desc" style="margin-bottom:0">
        This report analyzes {overall["total"]:,} hourly weather observations from {START_DATE} to {END_DATE}
        at coordinates {LAT}°N, {abs(LON)}°W (Belize). Data sourced from the
        <a href="https://open-meteo.com" style="color:#0067B1">Open-Meteo Archive API</a> (ERA5 reanalysis).
        Scoring thresholds match the FarmWeather live app:
        <strong>Humidity</strong> (&gt;40% safe, 30–40% caution, &lt;30% danger),
        <strong>Wind</strong> (&lt;5 mph safe, 5–10 caution, &gt;10 danger),
        <strong>Temperature</strong> (&lt;80°F safe, 80–90° caution, &gt;90° danger).
        Overall status is the worst of the three metrics.
    </p>
</div>

<!-- Footer -->
<div class="report-footer">
    <div class="footer-text">
        Data: Open-Meteo Archive API (ERA5 Reanalysis) &nbsp;·&nbsp; Generated {generated}<br>
        FarmWeather Historical Analysis
    </div>
    <div class="footer-logo"><img src="rare-logo.png" alt="Rare"></div>
</div>

</div><!-- /container -->

<script>
// ── Chart Data ──
const MONTHS = {json.dumps(MONTH_NAMES)};
const GREEN = '{COLORS["green"]}';
const YELLOW = '{COLORS["yellow"]}';
const RED = '{COLORS["red"]}';
const BLUE = '#0067B1';
const GOLD = '#D4982A';
const TEAL = '#009966';

const monthlyData = {json.dumps({str(m): monthly[m] for m in range(1,13)})};
const hourlyData = {json.dumps({str(h): hourly[h] for h in range(24)})};
const profileData = {json.dumps({str(h): profile[h] for h in range(24)})};
const driverData = {json.dumps(drivers["drivers"])};
const greenBins = {json.dumps(duration["green_bins"])};
const windowData = {json.dumps({str(m): best["monthly_avg"][m] for m in range(1,13)})};
const yearlyData = {json.dumps(yearly)};

Chart.defaults.font.family = "'Source Sans 3', sans-serif";
Chart.defaults.font.size = 13;
Chart.defaults.color = '#888';

// Helper: stacked options
function stackedOpts() {{
    return {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 12 }} }} }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%'
                }}
            }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#999' }} }},
            y: {{ stacked: true, max: 100, ticks: {{ callback: v => v + '%', color: '#999' }}, grid: {{ color: '#f0f0f0' }} }}
        }}
    }};
}}

// Monthly Seasonality Chart
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
    options: {{ ...stackedOpts(), scales: {{ ...stackedOpts().scales, x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ color: '#999' }} }} }} }}
}});

// Hourly Patterns Chart
new Chart(document.getElementById('hourlyChart'), {{
    type: 'line',
    data: {{
        labels: Array.from({{length:24}}, (_,i) => i + ':00'),
        datasets: [
            {{ label: 'Safe', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['0']), backgroundColor: GREEN+'40', borderColor: GREEN, fill: true, tension: 0.3 }},
            {{ label: 'Caution', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['1']), backgroundColor: YELLOW+'40', borderColor: YELLOW, fill: true, tension: 0.3 }},
            {{ label: 'Danger', data: Array.from({{length:24}}, (_,i) => hourlyData[String(i)]['2']), backgroundColor: RED+'40', borderColor: RED, fill: true, tension: 0.3 }},
        ]
    }},
    options: stackedOpts()
}});

// Daily Profile Chart
new Chart(document.getElementById('profileChart'), {{
    type: 'line',
    data: {{
        labels: Array.from({{length:24}}, (_,i) => i + ':00'),
        datasets: [
            {{ label: 'Humidity (%)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].humid), borderColor: BLUE, backgroundColor: BLUE+'15', borderWidth: 2.5, tension: 0.3, yAxisID: 'y' }},
            {{ label: 'Temperature (°F)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].temp), borderColor: GOLD, backgroundColor: GOLD+'15', borderWidth: 2.5, tension: 0.3, yAxisID: 'y' }},
            {{ label: 'Wind (mph)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].wind), borderColor: TEAL, backgroundColor: TEAL+'15', borderWidth: 2.5, tension: 0.3, yAxisID: 'y2' }},
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 12 }} }} }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#999' }} }},
            y: {{ position: 'left', title: {{ display: true, text: 'Humidity (%) / Temp (°F)', color: '#999' }}, grid: {{ color: '#f0f0f0' }}, ticks: {{ color: '#999' }} }},
            y2: {{ position: 'right', title: {{ display: true, text: 'Wind (mph)', color: '#999' }}, grid: {{ display: false }}, min: 0, ticks: {{ color: '#999' }} }}
        }}
    }}
}});

// Driver Donut
new Chart(document.getElementById('driverChart'), {{
    type: 'doughnut',
    data: {{
        labels: ['Humidity', 'Wind', 'Temperature'],
        datasets: [{{
            data: [driverData.humidity, driverData.wind, driverData.temperature],
            backgroundColor: [BLUE, TEAL, GOLD],
            borderWidth: 0,
            hoverOffset: 8,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'bottom', labels: {{ usePointStyle: true, padding: 16, font: {{ size: 12 }} }} }},
            tooltip: {{
                callbacks: {{
                    label: ctx => {{
                        const total = ctx.dataset.data.reduce((a,b) => a+b, 0);
                        return ctx.label + ': ' + ctx.raw.toLocaleString() + ' (' + (ctx.raw/total*100).toFixed(1) + '%)';
                    }}
                }}
            }}
        }},
        cutout: '55%',
    }}
}});

// Green Duration Histogram
new Chart(document.getElementById('durationChart'), {{
    type: 'bar',
    data: {{
        labels: Object.keys(greenBins),
        datasets: [{{
            label: 'Safe windows',
            data: Object.values(greenBins),
            backgroundColor: TEAL,
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#999' }} }},
            y: {{ title: {{ display: true, text: 'Count', color: '#999' }}, grid: {{ color: '#f0f0f0' }}, ticks: {{ color: '#999' }} }}
        }}
    }}
}});

// Best Windows by Month
new Chart(document.getElementById('windowChart'), {{
    type: 'bar',
    data: {{
        labels: MONTHS,
        datasets: [{{
            label: 'Avg longest safe window (hours)',
            data: MONTHS.map((_,i) => windowData[String(i+1)]),
            backgroundColor: BLUE,
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#999' }} }},
            y: {{ title: {{ display: true, text: 'Hours', color: '#999' }}, grid: {{ color: '#f0f0f0' }}, ticks: {{ color: '#999' }} }}
        }}
    }}
}});

// Year Trends
const years = Object.keys(yearlyData).sort();
new Chart(document.getElementById('yearlyChart'), {{
    type: 'line',
    data: {{
        labels: years,
        datasets: [
            {{ label: 'Safe %', data: years.map(y => yearlyData[y]['0']), borderColor: GREEN, backgroundColor: GREEN+'15', fill: true, tension: 0.3, borderWidth: 2.5 }},
            {{ label: 'Caution %', data: years.map(y => yearlyData[y]['1']), borderColor: YELLOW, backgroundColor: YELLOW+'15', fill: true, tension: 0.3, borderWidth: 2.5 }},
            {{ label: 'Danger %', data: years.map(y => yearlyData[y]['2']), borderColor: RED, backgroundColor: RED+'15', fill: true, tension: 0.3, borderWidth: 2.5 }},
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 20, font: {{ size: 12 }} }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%' }} }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#999' }} }},
            y: {{ max: 100, ticks: {{ callback: v => v + '%', color: '#999' }}, grid: {{ color: '#f0f0f0' }} }}
        }}
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
