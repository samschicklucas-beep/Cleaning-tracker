from flask import Flask, jsonify, request, render_template_string
import requests
import base64
import os
import sqlite3
import hmac
import hashlib
import json
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)

API_KEY      = os.environ.get("UPLISTING_API_KEY",    "a399e4af-ae52-48c3-8893-1cc8f11c881e")
WEBHOOK_KEY  = os.environ.get("UPLISTING_WEBHOOK_KEY","3e766b5c-4775-49e0-8aeb-91320bf57841")
BASE64_KEY   = base64.b64encode(API_KEY.encode()).decode()
AUTH         = f"Basic {BASE64_KEY}"
BASE_URL     = "https://connect.uplisting.io"

# ---------------------------------------------------------------------------
# SQLite — stores cleans received via webhook or entered manually
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "/tmp/cleans.db")

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS cleans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT    NOT NULL DEFAULT 'webhook',  -- 'webhook' | 'manual'
            property_id TEXT,
            address     TEXT    NOT NULL,
            unit        TEXT    NOT NULL DEFAULT '',
            type        TEXT    NOT NULL,
            rate        INTEGER NOT NULL,
            guest       TEXT    NOT NULL DEFAULT '-',
            checkout    TEXT    NOT NULL,   -- YYYY-MM-DD
            booking_id  TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()

init_db()

def get_webhook_cleans():
    """Return all rows from the local DB as a list of dicts."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM cleans WHERE checkout >= ? ORDER BY checkout",
        (TRACKER_START,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def insert_clean(source, property_id, address, unit, utype, rate, guest, checkout, booking_id=None):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT INTO cleans (source, property_id, address, unit, type, rate, guest, checkout, booking_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (source, property_id, address, unit, utype, rate, guest, checkout, booking_id))
    con.commit()
    con.close()

def already_stored(address, unit, checkout):
    """Prevent duplicate rows for the same checkout event."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT id FROM cleans WHERE address=? AND unit=? AND checkout=?",
        (address, unit, checkout)
    ).fetchone()
    con.close()
    return row is not None

# ---------------------------------------------------------------------------
# Property map (unchanged)
# ---------------------------------------------------------------------------
PROPERTY_MAP = {
    # 117 Chestnut St
    "253449": {"address": "117 Chestnut St",        "unit": "500B",  "type": "1BR",    "rate": 70},
    "256684": {"address": "117 Chestnut St",        "unit": "302A",  "type": "Studio", "rate": 70},
    # 1203 Germantown Ave (Liberty A-xxx)
    "254094": {"address": "1203 Germantown Ave",    "unit": "A-217", "type": "1BR",    "rate": 70},
    "256943": {"address": "1203 Germantown Ave",    "unit": "A-320", "type": "Studio", "rate": 70},
    "256944": {"address": "1203 Germantown Ave",    "unit": "A-419", "type": "Studio", "rate": 70},
    "256945": {"address": "1203 Germantown Ave",    "unit": "A-221", "type": "Studio", "rate": 70},
    "256946": {"address": "1203 Germantown Ave",    "unit": "A-407", "type": "1BR",    "rate": 70},
    "256947": {"address": "1203 Germantown Ave",    "unit": "A-319", "type": "2BR",    "rate": 80},
    "257472": {"address": "1203 Germantown Ave",    "unit": "A-205", "type": "1BR",    "rate": 70},
    # 1214 N American St (Liberty C-xxx)
    "256949": {"address": "1214 N American St",     "unit": "C-208", "type": "1BR",    "rate": 70},
    "256952": {"address": "1214 N American St",     "unit": "C-307", "type": "1BR",    "rate": 70},
    # 1401 N 5th St (Umbrella)
    "256476": {"address": "1401 N 5th St",          "unit": "421",   "type": "1BR",    "rate": 70},
    "256492": {"address": "1401 N 5th St",          "unit": "610",   "type": "1BR",    "rate": 70},
    "256582": {"address": "1401 N 5th St",          "unit": "1001",  "type": "Studio", "rate": 70},
    "256583": {"address": "1401 N 5th St",          "unit": "211",   "type": "Studio", "rate": 70},
    "256587": {"address": "1401 N 5th St",          "unit": "1006",  "type": "Studio", "rate": 70},
    "256588": {"address": "1401 N 5th St",          "unit": "322",   "type": "Studio", "rate": 70},
    "256589": {"address": "1401 N 5th St",          "unit": "814",   "type": "Studio", "rate": 70},
    "256590": {"address": "1401 N 5th St",          "unit": "714",   "type": "Studio", "rate": 70},
    "256591": {"address": "1401 N 5th St",          "unit": "513",   "type": "Studio", "rate": 70},
    "256592": {"address": "1401 N 5th St",          "unit": "706",   "type": "Studio", "rate": 70},
    "256593": {"address": "1401 N 5th St",          "unit": "208",   "type": "1BR",    "rate": 70},
    "256595": {"address": "1401 N 5th St",          "unit": "308",   "type": "1BR",    "rate": 70},
    "256597": {"address": "1401 N 5th St",          "unit": "316",   "type": "1BR",    "rate": 70},
    "256667": {"address": "1401 N 5th St",          "unit": "209",   "type": "1BR",    "rate": 70},
    "256670": {"address": "1401 N 5th St",          "unit": "216",   "type": "1BR",    "rate": 70},
    "256671": {"address": "1401 N 5th St",          "unit": "412",   "type": "1BR",    "rate": 70},
    "256675": {"address": "1401 N 5th St",          "unit": "521",   "type": "1BR",    "rate": 70},
    "256677": {"address": "1401 N 5th St",          "unit": "807",   "type": "1BR",    "rate": 70},
    "256678": {"address": "1401 N 5th St",          "unit": "718",   "type": "1BR",    "rate": 70},
    "256679": {"address": "1401 N 5th St",          "unit": "715",   "type": "1BR",    "rate": 70},
    "256680": {"address": "1401 N 5th St",          "unit": "703",   "type": "2BR",    "rate": 80},
    # 119 E Allen St
    "256683": {"address": "119 E Allen St",         "unit": "",      "type": "3BR",    "rate": 90},
    # 1149 N 3rd St
    "256686": {"address": "1149 N 3rd St",          "unit": "149A",  "type": "Studio", "rate": 70},
    # 117 South St
    "256697": {"address": "117 South St",           "unit": "2",     "type": "2BR",    "rate": 80},
    # 220 South St
    "256702": {"address": "220 South St",           "unit": "2F",    "type": "2BR",    "rate": 80},
    "256703": {"address": "220 South St",           "unit": "2R",    "type": "2BR",    "rate": 80},
    # 701 S 4th St
    "256705": {"address": "701 S 4th St",           "unit": "3F",    "type": "2BR",    "rate": 80},
    # 715 Belgrade St
    "256706": {"address": "715 Belgrade St",        "unit": "2F",    "type": "1BR",    "rate": 70},
    "256708": {"address": "715 Belgrade St",        "unit": "2R",    "type": "Studio", "rate": 70},
    # 2400 E Huntingdon St (Views)
    "256709": {"address": "2400 E Huntingdon St",   "unit": "302",   "type": "1BR",    "rate": 70},
    "256710": {"address": "2400 E Huntingdon St",   "unit": "402",   "type": "1BR",    "rate": 70},
    "256711": {"address": "2400 E Huntingdon St",   "unit": "202",   "type": "1BR",    "rate": 70},
    "257303": {"address": "2400 E Huntingdon St",   "unit": "621",   "type": "2BR",    "rate": 80},
    "256713": {"address": "2400 E Huntingdon St",   "unit": "325",   "type": "2BR",    "rate": 80},
    "256715": {"address": "2400 E Huntingdon St",   "unit": "601",   "type": "2BR",    "rate": 80},
    "256717": {"address": "2400 E Huntingdon St",   "unit": "501",   "type": "2BR",    "rate": 80},
    "256718": {"address": "2400 E Huntingdon St",   "unit": "525",   "type": "2BR",    "rate": 80},
    "256720": {"address": "2400 E Huntingdon St",   "unit": "217",   "type": "2BR",    "rate": 80},
    "257171": {"address": "2400 E Huntingdon St",   "unit": "210",   "type": "2BR",    "rate": 80},
    "260137": {"address": "2400 E Huntingdon St",   "unit": "425",   "type": "2BR",    "rate": 80},
    "260138": {"address": "2400 E Huntingdon St",   "unit": "624",   "type": "2BR",    "rate": 80},
    # 1222 N 2nd St (Corner 2nd)
    "256773": {"address": "1222 N 2nd St",          "unit": "217",   "type": "1BR",    "rate": 70},
    "256774": {"address": "1222 N 2nd St",          "unit": "218",   "type": "1BR",    "rate": 70},
    "256775": {"address": "1222 N 2nd St",          "unit": "307",   "type": "1BR",    "rate": 70},
    "256777": {"address": "1222 N 2nd St",          "unit": "311",   "type": "1BR",    "rate": 70},
    "256778": {"address": "1222 N 2nd St",          "unit": "302",   "type": "2BR",    "rate": 80},
    "256779": {"address": "1222 N 2nd St",          "unit": "303",   "type": "2BR",    "rate": 80},
    # Dash listings
    "261508": {"address": "1401 N 5th St",          "unit": "521",   "type": "1BR",    "rate": 70},
    "261509": {"address": "1401 N 5th St",          "unit": "513",   "type": "Studio", "rate": 70},
    "261510": {"address": "1401 N 5th St",          "unit": "308",   "type": "1BR",    "rate": 70},
    "261511": {"address": "1401 N 5th St",          "unit": "1001",  "type": "Studio", "rate": 70},
    "261512": {"address": "1203 Germantown Ave",    "unit": "A-217", "type": "1BR",    "rate": 70},
    "261513": {"address": "1203 Germantown Ave",    "unit": "A-407", "type": "1BR",    "rate": 70},
    "261514": {"address": "1149 N 3rd St",          "unit": "149A",  "type": "Studio", "rate": 70},
    "261565": {"address": "2400 E Huntingdon St",   "unit": "302",   "type": "1BR",    "rate": 70},
    "261586": {"address": "2400 E Huntingdon St",   "unit": "202",   "type": "1BR",    "rate": 70},
    "261596": {"address": "2400 E Huntingdon St",   "unit": "402",   "type": "1BR",    "rate": 70},
    "261598": {"address": "2400 E Huntingdon St",   "unit": "601",   "type": "2BR",    "rate": 80},
    "261600": {"address": "715 Belgrade St",        "unit": "2F",    "type": "1BR",    "rate": 70},
    "261601": {"address": "715 Belgrade St",        "unit": "2R",    "type": "Studio", "rate": 70},
    "261603": {"address": "1203 Germantown Ave",    "unit": "A-221", "type": "Studio", "rate": 70},
    "256712": {"address": "2400 E Huntingdon St",   "unit": "621",   "type": "2BR",    "rate": 80},
}

LAUNDRY_FEE   = 500
TRACKER_START = "2026-05-01"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_week_start(date_str):
    d   = datetime.strptime(date_str[:10], "%Y-%m-%d")
    mon = d - timedelta(days=d.weekday())
    return mon.strftime("%Y-%m-%d")

def get_week_label(week_start):
    mon = datetime.strptime(week_start, "%Y-%m-%d")
    sun = mon + timedelta(days=6)
    return f"{mon.strftime('%b %d')} - {sun.strftime('%b %d')}"

def verify_uplisting_signature(request_obj):
    """
    Uplisting signs webhook payloads with HMAC-SHA256 using the webhook key.
    Header: X-Uplisting-Signature  (hex digest)
    If the header is absent we still accept the request in dev mode —
    remove the `return True` line once you confirm real payloads are arriving.
    """
    sig_header = request_obj.headers.get("X-Uplisting-Signature", "")
    if not sig_header:
        return True  # TODO: set to False once Uplisting confirms header format

    body    = request_obj.get_data()
    expected = hmac.new(
        WEBHOOK_KEY.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)

# ---------------------------------------------------------------------------
# Data aggregation  (API cleans  +  DB cleans, deduped together)
# ---------------------------------------------------------------------------
def fetch_all_data():
    # --- 1. Pull from Uplisting API ---
    cleaning_events = []
    seen_checkouts  = set()   # (address, unit, date)

    try:
        prop_res   = requests.get(f"{BASE_URL}/properties", headers={"Authorization": AUTH}, timeout=15)
        properties = prop_res.json().get("data", [])
    except Exception:
        properties = []

    for prop in properties:
        prop_id   = str(prop.get("id", ""))
        unit_info = PROPERTY_MAP.get(prop_id)
        if not unit_info:
            continue
        try:
            b_res    = requests.get(
                f"{BASE_URL}/bookings",
                params={"property_id": prop_id, "start_date": "2026-04-01", "end_date": "2026-12-31"},
                headers={"Authorization": AUTH},
                timeout=15,
            )
            bookings = b_res.json().get("data", [])
            for b in bookings:
                attrs    = b.get("attributes", {})
                if attrs.get("status") == "cancelled":
                    continue
                checkout = attrs.get("check_out") or attrs.get("end_date", "")
                if not checkout or checkout[:10] < TRACKER_START:
                    continue
                dedup_key = (unit_info["address"], unit_info["unit"], checkout[:10])
                if dedup_key in seen_checkouts:
                    continue
                seen_checkouts.add(dedup_key)
                cleaning_events.append({
                    "date":    checkout[:10],
                    "address": unit_info["address"],
                    "unit":    unit_info["unit"],
                    "type":    unit_info["type"],
                    "rate":    unit_info["rate"],
                    "guest":   attrs.get("guest_name", "-"),
                    "week":    get_week_start(checkout),
                    "source":  "api",
                })
        except Exception:
            continue

    # --- 2. Merge webhook / manual cleans from DB ---
    for row in get_webhook_cleans():
        dedup_key = (row["address"], row["unit"], row["checkout"])
        if dedup_key in seen_checkouts:
            continue
        seen_checkouts.add(dedup_key)
        cleaning_events.append({
            "date":    row["checkout"],
            "address": row["address"],
            "unit":    row["unit"],
            "type":    row["type"],
            "rate":    row["rate"],
            "guest":   row["guest"],
            "week":    get_week_start(row["checkout"]),
            "source":  row["source"],
        })

    # --- 3. Sort & bucket by week ---
    cleaning_events.sort(key=lambda x: x["date"])
    weeks = defaultdict(list)
    for e in cleaning_events:
        weeks[e["week"]].append(e)

    week_summaries = []
    running_total  = 0
    for week_key in sorted(weeks.keys()):
        events      = weeks[week_key]
        clean_total = sum(e["rate"] for e in events)
        week_total  = clean_total + LAUNDRY_FEE
        running_total += week_total
        week_summaries.append({
            "week_key":     week_key,
            "week_label":   get_week_label(week_key),
            "events":       events,
            "clean_total":  clean_total,
            "laundry":      LAUNDRY_FEE,
            "week_total":   week_total,
            "running_total": running_total,
        })

    return {
        "weeks":        week_summaries,
        "grand_total":  running_total,
        "total_cleans": len(cleaning_events),
        "total_weeks":  len(week_summaries),
        "total_laundry": len(week_summaries) * LAUNDRY_FEE,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------
@app.route("/webhook/uplisting", methods=["POST"])
def uplisting_webhook():
    # 1. Verify signature
    if not verify_uplisting_signature(request):
        return jsonify({"error": "invalid signature"}), 401

    # 2. Parse payload
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "bad JSON"}), 400

    if not payload:
        return jsonify({"error": "empty payload"}), 400

    event_type = payload.get("event") or payload.get("type", "")
    # Uplisting may wrap data under "data" or "booking"
    booking    = payload.get("data") or payload.get("booking") or {}
    attrs      = booking.get("attributes", booking)   # flat or nested

    # 3. Only act on checkout-triggering events
    HANDLED_EVENTS = {
        "booking.confirmed",
        "booking.checkout",
        "checkout.completed",
        "booking.updated",
    }
    if event_type not in HANDLED_EVENTS:
        return jsonify({"status": "ignored", "event": event_type}), 200

    # 4. Extract fields
    prop_id    = str(attrs.get("property_id") or booking.get("property_id", ""))
    checkout   = (attrs.get("check_out") or attrs.get("end_date", ""))[:10]
    guest      = attrs.get("guest_name") or attrs.get("guest", {}).get("name", "-")
    booking_id = str(booking.get("id", ""))
    status     = attrs.get("status", "")

    if status == "cancelled":
        return jsonify({"status": "ignored", "reason": "cancelled"}), 200

    if not checkout or checkout < TRACKER_START:
        return jsonify({"status": "ignored", "reason": "before tracker start"}), 200

    # 5. Resolve unit info
    unit_info = PROPERTY_MAP.get(prop_id)
    if not unit_info:
        return jsonify({"status": "ignored", "reason": f"unknown property_id {prop_id}"}), 200

    address = unit_info["address"]
    unit    = unit_info["unit"]

    # 6. Skip if already stored
    if already_stored(address, unit, checkout):
        return jsonify({"status": "duplicate", "checkout": checkout}), 200

    # 7. Persist
    insert_clean(
        source      = "webhook",
        property_id = prop_id,
        address     = address,
        unit        = unit,
        utype       = unit_info["type"],
        rate        = unit_info["rate"],
        guest       = guest,
        checkout    = checkout,
        booking_id  = booking_id,
    )

    return jsonify({
        "status":   "stored",
        "address":  address,
        "unit":     unit,
        "checkout": checkout,
        "rate":     unit_info["rate"],
    }), 201

# ---------------------------------------------------------------------------
# Inspect / debug stored webhook cleans
# ---------------------------------------------------------------------------
@app.route("/api/webhook-cleans")
def api_webhook_cleans():
    rows = get_webhook_cleans()
    return jsonify({"count": len(rows), "cleans": rows})

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cleaner Invoice Tracker</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Georgia, serif; background: #0f0f0f; color: #e8e0d0; min-height: 100vh; }
.header { background: #141414; border-bottom: 1px solid #2a2a2a; padding: 28px 32px 24px; }
.header h1 { font-size: 26px; font-weight: normal; color: #f0e8d8; letter-spacing: 1px; }
.subtitle { font-size: 11px; letter-spacing: 4px; color: #888; text-transform: uppercase; margin-bottom: 8px; }
.sync-time { font-size: 12px; color: #555; margin-top: 4px; }
.kpi-row { display: flex; gap: 16px; margin-top: 24px; flex-wrap: wrap; }
.kpi { background: #181818; border: 1px solid #252525; border-radius: 6px; padding: 12px 20px; min-width: 110px; }
.kpi.highlight { background: #c8a96e11; border-color: #c8a96e55; }
.kpi-label { font-size: 10px; letter-spacing: 3px; color: #777; text-transform: uppercase; margin-bottom: 4px; }
.kpi-value { font-size: 18px; color: #e8e0d0; }
.kpi.highlight .kpi-value { font-size: 24px; color: #c8a96e; font-weight: bold; }
.refresh-btn { background: #c8a96e; color: #0f0f0f; border: none; border-radius: 4px; padding: 10px 20px; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; cursor: pointer; font-family: inherit; text-decoration: none; display: inline-block; }
.header-top { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; }
.content { padding: 24px 32px; }
.week-block { background: #161616; border: 1px solid #252525; border-radius: 8px; margin-bottom: 10px; overflow: hidden; }
.week-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; cursor: pointer; }
.week-header:hover { background: #1a1a1a; }
.week-label { font-size: 13px; color: #e8e0d0; }
.week-count { font-size: 11px; color: #555; margin-left: 12px; }
.week-right { display: flex; align-items: center; gap: 20px; }
.week-breakdown { font-size: 11px; color: #666; text-align: right; line-height: 1.6; }
.week-breakdown span { color: #aaa; }
.week-total { font-size: 18px; color: #c8a96e; min-width: 80px; text-align: right; }
.toggle { color: #444; font-size: 12px; margin-left: 8px; }
.week-detail { border-top: 1px solid #222; display: none; }
.week-detail.open { display: block; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { padding: 10px 16px; text-align: left; color: #555; font-weight: normal; letter-spacing: 2px; font-size: 10px; text-transform: uppercase; background: #111; }
td { padding: 10px 16px; border-top: 1px solid #1e1e1e; }
.badge { background: #1e2a1e; color: #6ab06a; border-radius: 3px; padding: 2px 8px; font-size: 10px; }
.badge-wh { background: #1e1e2a; color: #6a80b0; border-radius: 3px; padding: 2px 6px; font-size: 9px; letter-spacing: 1px; }
.gold { color: #c8a96e; }
.muted { color: #666; }
.dim { color: #aaa; }
.laundry-row td { background: #111; color: #555; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; }
.total-row td { background: #1a1a12; }
.grand-total-bar { background: #1a1a0f; border: 1px solid #c8a96e44; border-radius: 8px; padding: 20px 24px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center; }
.grand-total-label { font-size: 11px; letter-spacing: 3px; color: #888; text-transform: uppercase; }
.grand-total-sub { font-size: 11px; color: #555; margin-top: 4px; }
.grand-total-value { font-size: 32px; color: #c8a96e; font-weight: bold; }
.empty { text-align: center; padding: 48px 0; color: #555; font-size: 14px; }
</style>
</head>
<body>
<div class="header">
  <div class="header-top">
    <div>
      <div class="subtitle">Bridge One Management · Live</div>
      <h1>Cleaner Invoice Tracker</h1>
      <div class="sync-time">Last updated: {{ data.last_updated }} · {{ data.total_cleans }} cleans · {{ data.total_weeks }} weeks</div>
    </div>
    <a href="/" class="refresh-btn">&#8635; Refresh</a>
  </div>
  <div class="kpi-row">
    <div class="kpi highlight">
      <div class="kpi-label">Total Owed</div>
      <div class="kpi-value">${{ "{:,}".format(data.grand_total) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Cleaning Events</div>
      <div class="kpi-value">{{ data.total_cleans }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Weeks Tracked</div>
      <div class="kpi-value">{{ data.total_weeks }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Laundry Fees</div>
      <div class="kpi-value">${{ "{:,}".format(data.total_laundry) }}</div>
    </div>
  </div>
</div>
<div class="content">
  {% if not data.weeks %}
  <div class="empty">No checkout events found from May 1st onward.</div>
  {% endif %}
  {% for week in data.weeks %}
  <div class="week-block">
    <div class="week-header" onclick="toggle('week-{{ loop.index }}')">
      <div>
        <span class="week-label">{{ week.week_label }}</span>
        <span class="week-count">{{ week.events|length }} clean{{ 's' if week.events|length != 1 else '' }}</span>
      </div>
      <div class="week-right">
        <div class="week-breakdown">
          Cleaning: <span>${{ week.clean_total }}</span><br>
          Laundry: <span>${{ week.laundry }}</span>
        </div>
        <div class="week-total">${{ "{:,}".format(week.week_total) }}</div>
        <div class="toggle" id="toggle-week-{{ loop.index }}">&#9660;</div>
      </div>
    </div>
    <div class="week-detail" id="week-{{ loop.index }}">
      <table>
        <thead>
          <tr><th>Date</th><th>Property</th><th>Unit</th><th>Type</th><th>Guest</th><th>Source</th><th>Rate</th></tr>
        </thead>
        <tbody>
          {% for e in week.events %}
          <tr>
            <td class="dim">{{ e.date }}</td>
            <td>{{ e.address }}</td>
            <td class="dim">{{ e.unit }}</td>
            <td><span class="badge">{{ e.type }}</span></td>
            <td class="muted">{{ e.guest }}</td>
            <td>{% if e.source == 'webhook' %}<span class="badge-wh">WH</span>{% elif e.source == 'manual' %}<span class="badge-wh">MAN</span>{% endif %}</td>
            <td class="gold">${{ e.rate }}</td>
          </tr>
          {% endfor %}
          <tr class="laundry-row">
            <td colspan="6">Laundry Fee</td>
            <td class="gold">${{ week.laundry }}</td>
          </tr>
          <tr class="total-row">
            <td colspan="6" class="dim" style="font-size:10px;letter-spacing:2px;text-transform:uppercase;">Week Total</td>
            <td class="gold" style="font-size:15px;">${{ "{:,}".format(week.week_total) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  {% endfor %}
  {% if data.weeks %}
  <div class="grand-total-bar">
    <div>
      <div class="grand-total-label">Total Balance Owed to Cleaner</div>
      <div class="grand-total-sub">Since May 1, 2026 · {{ data.total_cleans }} cleans · {{ data.total_weeks }} weeks x $500 laundry</div>
    </div>
    <div class="grand-total-value">${{ "{:,}".format(data.grand_total) }}</div>
  </div>
  {% endif %}
</div>
<script>
function toggle(id) {
  var el  = document.getElementById(id);
  var tog = document.getElementById('toggle-' + id);
  if (el.classList.contains('open')) {
    el.classList.remove('open');
    tog.innerHTML = '&#9660;';
  } else {
    el.classList.add('open');
    tog.innerHTML = '&#9650;';
  }
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Existing routes (unchanged)
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    try:
        data = fetch_all_data()
    except Exception as e:
        data = {
            "weeks": [], "grand_total": 0, "total_cleans": 0,
            "total_weeks": 0, "total_laundry": 0,
            "last_updated": f"Error: {str(e)}"
        }
    return render_template_string(DASHBOARD_HTML, data=data)

@app.route("/api/properties")
def get_properties():
    r = requests.get(f"{BASE_URL}/properties", headers={"Authorization": AUTH})
    response = jsonify(r.json())
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.route("/api/bookings")
def get_bookings():
    property_id = request.args.get("property_id")
    start       = request.args.get("start_date", "2026-04-01")
    end         = request.args.get("end_date",   "2026-12-31")
    r = requests.get(
        f"{BASE_URL}/bookings",
        params={"property_id": property_id, "start_date": start, "end_date": end},
        headers={"Authorization": AUTH},
    )
    response = jsonify(r.json())
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.route("/api/debug")
def debug():
    new_key  = WEBHOOK_KEY
    new_auth = f"Basic {base64.b64encode(new_key.encode()).decode()}"
    results  = {}
    paths    = [
        "/bookings?property_id=253449",
        "/bookings?filter%5Bproperty_id%5D=253449",
        "/properties/253449/bookings",
        "/v1/properties/253449/bookings",
        "/multi_units/253449/bookings",
    ]
    for path in paths:
        try:
            r = requests.get(
                f"{BASE_URL}{path}",
                headers={"Authorization": new_auth, "Accept-Encoding": "identity"},
                timeout=10,
            )
            results[path] = {"status": r.status_code, "text": r.text[:200]}
        except Exception as e:
            results[path] = {"error": str(e)}
    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
