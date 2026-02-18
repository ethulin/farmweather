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

    # Heatmap data as flat array for Chart.js matrix
    heatmap_data = []
    for m in range(1, 13):
        for h in range(24):
            heatmap_data.append({"x": h, "y": m - 1, "v": heatmap[m][h]})

    # Pre-build heatmap HTML
    heatmap_hours_html = "".join(f'<div class="heatmap-hour">{h}</div>' for h in range(24))
    heatmap_rows_html = ""
    for m in range(1, 13):
        heatmap_rows_html += f'<div class="heatmap-label">{MONTH_NAMES[m-1]}</div>'
        for h in range(24):
            v = heatmap[m][h]
            c = heatmap_color(v)
            heatmap_rows_html += f'<div class="heatmap-cell" style="background:{c}">{v:.0f}</div>'

    generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historical Burn Conditions Report — Belize</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}}

/* Header */
.report-header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #fff;
    padding: 48px 24px 40px;
    text-align: center;
}}
.report-header h1 {{
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
}}
.report-header .meta {{
    font-size: 0.95rem;
    opacity: 0.7;
    font-weight: 300;
}}

/* Container */
.container {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 32px 24px 64px;
}}

/* Section Cards */
.card {{
    background: #fff;
    border-radius: 16px;
    padding: 32px;
    margin-bottom: 28px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.04);
    border: 1px solid rgba(0,0,0,0.04);
}}
.card h2 {{
    font-size: 1.3rem;
    font-weight: 700;
    margin-bottom: 6px;
    color: #1a1a2e;
}}
.card .section-desc {{
    font-size: 0.9rem;
    color: #666;
    margin-bottom: 24px;
    line-height: 1.5;
}}

/* Executive Summary */
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    margin-bottom: 20px;
}}
.stat-card {{
    text-align: center;
    padding: 28px 16px;
    border-radius: 14px;
    color: #fff;
}}
.stat-card.green {{ background: linear-gradient(135deg, #1e9e38, #22b740); }}
.stat-card.yellow {{ background: linear-gradient(135deg, #d49500, #e6a800); }}
.stat-card.red {{ background: linear-gradient(135deg, #c62828, #d93030); }}
.stat-card .pct {{
    font-size: 3rem;
    font-weight: 800;
    line-height: 1;
    margin-bottom: 4px;
}}
.stat-card .label {{
    font-size: 0.85rem;
    font-weight: 500;
    opacity: 0.9;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
.stat-card .count {{
    font-size: 0.8rem;
    opacity: 0.7;
    margin-top: 4px;
}}
.takeaway {{
    background: #f8f9fa;
    border-left: 4px solid #0f3460;
    padding: 16px 20px;
    border-radius: 0 10px 10px 0;
    font-size: 0.95rem;
    color: #444;
}}

/* Charts */
.chart-container {{
    position: relative;
    width: 100%;
    max-height: 400px;
}}
.chart-container canvas {{
    max-height: 400px;
}}

/* Two-column layout */
.two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 28px;
}}

/* Tables */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    margin-top: 16px;
}}
.data-table th {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid #e9ecef;
    font-weight: 600;
    color: #555;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.data-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid #f0f0f0;
}}
.data-table tr:last-child td {{ border-bottom: none; }}
.data-table tr:hover td {{ background: #f8f9fa; }}

.status-dot {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
}}

/* Heatmap */
.heatmap-grid {{
    display: grid;
    grid-template-columns: 60px repeat(24, 1fr);
    gap: 2px;
    font-size: 0.7rem;
    margin-top: 16px;
}}
.heatmap-cell {{
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.65rem;
    min-height: 28px;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.3);
}}
.heatmap-label {{
    display: flex;
    align-items: center;
    font-weight: 600;
    font-size: 0.78rem;
    color: #555;
    padding-right: 8px;
    justify-content: flex-end;
}}
.heatmap-hour {{
    text-align: center;
    font-weight: 600;
    color: #888;
    font-size: 0.72rem;
    padding-bottom: 4px;
}}

/* Insights */
.insight {{
    display: inline-block;
    background: #f0f7ff;
    border: 1px solid #d0e3ff;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 0.85rem;
    color: #1a5276;
    margin: 4px 4px 4px 0;
}}

/* Footer */
.report-footer {{
    text-align: center;
    padding: 32px 24px;
    color: #999;
    font-size: 0.82rem;
    line-height: 1.8;
}}

/* Responsive */
@media (max-width: 768px) {{
    .summary-grid {{ grid-template-columns: 1fr; }}
    .two-col {{ grid-template-columns: 1fr; }}
    .card {{ padding: 20px; }}
    .report-header h1 {{ font-size: 1.6rem; }}
    .heatmap-grid {{ overflow-x: auto; }}
}}

@media print {{
    body {{ background: #fff; }}
    .card {{ box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }}
    .report-header {{ background: #1a1a2e; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
</style>
</head>
<body>

<div class="report-header">
    <h1>Historical Burn Conditions Report</h1>
    <div class="meta">Belize &nbsp;·&nbsp; {LAT}°N, {abs(LON)}°W &nbsp;·&nbsp; {START_DATE[:4]}–{END_DATE[:4]} &nbsp;·&nbsp; {overall["total"]:,} hourly observations</div>
    <div class="meta" style="margin-top:4px; opacity:0.5">Generated {generated}</div>
</div>

<div class="container">

<!-- Executive Summary -->
<div class="card">
    <h2>Executive Summary</h2>
    <p class="section-desc">Overall distribution of burn safety conditions across {int(END_DATE[:4]) - int(START_DATE[:4]) + 1} years of hourly weather data.</p>
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
    <div class="takeaway">
        <strong>Key finding:</strong> <em>{dominant.capitalize()}</em> is the primary driver of unsafe conditions,
        responsible for triggering caution or danger in {d[dominant]:,} of {drivers["total"]:,} non-green hours.
        The safest month is <strong>{MONTH_NAMES[best_month[0]-1]}</strong> ({best_month[1]}% green) and the riskiest is
        <strong>{MONTH_NAMES[worst_month[0]-1]}</strong> ({worst_month[1]}% green).
        Within a typical day, <strong>{best_hour[0]}:00</strong> is the safest hour ({best_hour[1]}% green)
        and <strong>{worst_hour[0]}:00</strong> is the riskiest ({worst_hour[1]}% green).
    </div>
</div>

<!-- Monthly Seasonality -->
<div class="card">
    <h2>Monthly Seasonality</h2>
    <p class="section-desc">Percentage of hours at each safety level by month. Identifies the best and worst months for agricultural burning.</p>
    <div class="chart-container"><canvas id="monthlyChart"></canvas></div>
    <div style="margin-top:16px">
        <span class="insight">Best month: <strong>{MONTH_NAMES[best_month[0]-1]}</strong> — {best_month[1]}% safe</span>
        <span class="insight">Worst month: <strong>{MONTH_NAMES[worst_month[0]-1]}</strong> — {worst_month[1]}% safe</span>
    </div>
</div>

<!-- Time of Day -->
<div class="card">
    <h2>Time-of-Day Patterns</h2>
    <p class="section-desc">How burn safety conditions shift throughout a 24-hour cycle, averaged across all days in the dataset.</p>
    <div class="chart-container"><canvas id="hourlyChart"></canvas></div>
    <div style="margin-top:16px">
        <span class="insight">Safest hour: <strong>{best_hour[0]}:00</strong> — {best_hour[1]}% safe</span>
        <span class="insight">Riskiest hour: <strong>{worst_hour[0]}:00</strong> — {worst_hour[1]}% safe</span>
    </div>
</div>

<!-- Typical Day Profile -->
<div class="card">
    <h2>Typical Day Weather Profile</h2>
    <p class="section-desc">Average temperature, humidity, and wind speed by hour of day. Dashed lines show the scoring thresholds.</p>
    <div class="chart-container"><canvas id="profileChart"></canvas></div>
</div>

<!-- Two-column: Drivers + Duration -->
<div class="two-col">
    <div class="card">
        <h2>What Drives Unsafe Conditions?</h2>
        <p class="section-desc">When conditions are yellow or red, which weather metric is responsible?</p>
        <div class="chart-container" style="max-height:300px"><canvas id="driverChart"></canvas></div>
        <div style="margin-top:12px; font-size:0.85rem; color:#666">
            Note: Multiple metrics can co-drive a single hour's status.
        </div>
    </div>
    <div class="card">
        <h2>How Long Do Conditions Last?</h2>
        <p class="section-desc">Statistics on consecutive hours at each safety level.</p>
        <table class="data-table">
            <thead><tr><th>Status</th><th>Runs</th><th>Min</th><th>Median</th><th>Mean</th><th>P90</th><th>Max</th></tr></thead>
            <tbody>{dur_rows}</tbody>
        </table>
        <div style="margin-top:20px">
            <div class="chart-container" style="max-height:250px"><canvas id="durationChart"></canvas></div>
        </div>
    </div>
</div>

<!-- Best Burning Windows -->
<div class="card">
    <h2>Best Burning Windows</h2>
    <p class="section-desc">Average length of the longest safe (green) window by month, and the top 10 longest safe windows ever recorded.</p>
    <div class="two-col">
        <div>
            <h3 style="font-size:1rem;font-weight:600;margin-bottom:12px">Avg. Longest Green Window by Month</h3>
            <div class="chart-container" style="max-height:300px"><canvas id="windowChart"></canvas></div>
        </div>
        <div>
            <h3 style="font-size:1rem;font-weight:600;margin-bottom:12px">Top 10 Longest Safe Windows</h3>
            <table class="data-table">
                <thead><tr><th>#</th><th>Start</th><th>End</th><th>Duration</th></tr></thead>
                <tbody>{top_rows}</tbody>
            </table>
        </div>
    </div>
</div>

<!-- Year Trends -->
<div class="card">
    <h2>Year-over-Year Trends</h2>
    <p class="section-desc">Annual percentage of safe hours from {START_DATE[:4]} to {END_DATE[:4]}. Shows whether conditions are trending better or worse.</p>
    <div class="chart-container"><canvas id="yearlyChart"></canvas></div>
</div>

<!-- Heatmap -->
<div class="card">
    <h2>Month × Hour Heatmap</h2>
    <p class="section-desc">Percentage of safe (green) hours at each month/hour combination. Darker green = more often safe. This is the quick-reference guide for planning burns.</p>
    <div class="heatmap-grid">
        <div></div>
        {heatmap_hours_html}
        {heatmap_rows_html}
    </div>
</div>

<!-- Methodology -->
<div class="card" style="background:#f8f9fa">
    <h2 style="font-size:1.1rem">Methodology</h2>
    <p class="section-desc" style="margin-bottom:0">
        This report analyzes {overall["total"]:,} hourly weather observations from {START_DATE} to {END_DATE}
        at coordinates {LAT}°N, {abs(LON)}°W (Belize). Data sourced from the
        <a href="https://open-meteo.com" style="color:#0f3460">Open-Meteo Archive API</a> (ERA5 reanalysis).
        Scoring thresholds match the FarmWeather live app:
        <strong>Humidity</strong> (>40% safe, 30–40% caution, <30% danger),
        <strong>Wind</strong> (<5 mph safe, 5–10 caution, >10 danger),
        <strong>Temperature</strong> (<80°F safe, 80–90° caution, >90° danger).
        Overall status is the worst of the three metrics.
    </p>
</div>

</div>

<div class="report-footer">
    Data: Open-Meteo Archive API (ERA5 Reanalysis) &nbsp;·&nbsp; Generated {generated}<br>
    Belize Maya Forest Trust — FarmWeather Historical Analysis
</div>

<script>
// ── Chart Data ──
const MONTHS = {json.dumps(MONTH_NAMES)};
const GREEN = '{COLORS["green"]}';
const YELLOW = '{COLORS["yellow"]}';
const RED = '{COLORS["red"]}';

const monthlyData = {json.dumps({str(m): monthly[m] for m in range(1,13)})};
const hourlyData = {json.dumps({str(h): hourly[h] for h in range(24)})};
const profileData = {json.dumps({str(h): profile[h] for h in range(24)})};
const driverData = {json.dumps(drivers["drivers"])};
const greenBins = {json.dumps(duration["green_bins"])};
const windowData = {json.dumps({str(m): best["monthly_avg"][m] for m in range(1,13)})};
const yearlyData = {json.dumps(yearly)};

Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size = 13;
Chart.defaults.color = '#666';

// Helper: stacked options
function stackedOpts(title) {{
    return {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 16 }} }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%'
                }}
            }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ stacked: true, max: 100, ticks: {{ callback: v => v + '%' }}, grid: {{ color: '#f0f0f0' }} }}
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
    options: {{ ...stackedOpts(), scales: {{ ...stackedOpts().scales, x: {{ stacked: true, grid: {{ display: false }} }} }} }}
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
            {{ label: 'Humidity (%)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].humid), borderColor: '#3498db', backgroundColor: '#3498db20', borderWidth: 2.5, tension: 0.3, yAxisID: 'y' }},
            {{ label: 'Temperature (°F)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].temp), borderColor: '#e74c3c', backgroundColor: '#e74c3c20', borderWidth: 2.5, tension: 0.3, yAxisID: 'y' }},
            {{ label: 'Wind (mph)', data: Array.from({{length:24}}, (_,i) => profileData[String(i)].wind), borderColor: '#9b59b6', backgroundColor: '#9b59b620', borderWidth: 2.5, tension: 0.3, yAxisID: 'y2' }},
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 16 }} }},
            annotation: undefined
        }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ position: 'left', title: {{ display: true, text: 'Humidity (%) / Temp (°F)' }}, grid: {{ color: '#f0f0f0' }} }},
            y2: {{ position: 'right', title: {{ display: true, text: 'Wind (mph)' }}, grid: {{ display: false }}, min: 0 }}
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
            backgroundColor: ['#3498db', '#9b59b6', '#e74c3c'],
            borderWidth: 0,
            hoverOffset: 8,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'bottom', labels: {{ usePointStyle: true, padding: 16 }} }},
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
            backgroundColor: GREEN,
            borderRadius: 6,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ title: {{ display: true, text: 'Count' }}, grid: {{ color: '#f0f0f0' }} }}
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
            backgroundColor: GREEN,
            borderRadius: 6,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ title: {{ display: true, text: 'Hours' }}, grid: {{ color: '#f0f0f0' }} }}
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
            {{ label: 'Safe %', data: years.map(y => yearlyData[y]['0']), borderColor: GREEN, backgroundColor: GREEN+'20', fill: true, tension: 0.3, borderWidth: 2.5 }},
            {{ label: 'Caution %', data: years.map(y => yearlyData[y]['1']), borderColor: YELLOW, backgroundColor: YELLOW+'20', fill: true, tension: 0.3, borderWidth: 2.5 }},
            {{ label: 'Danger %', data: years.map(y => yearlyData[y]['2']), borderColor: RED, backgroundColor: RED+'20', fill: true, tension: 0.3, borderWidth: 2.5 }},
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, padding: 16 }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%' }} }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ max: 100, ticks: {{ callback: v => v + '%' }}, grid: {{ color: '#f0f0f0' }} }}
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
