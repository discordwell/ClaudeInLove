"""
Beacon callback server - receives and logs hits from tracking links/tokens.

Run with: python -m src.beacons.callback_server
Or behind nginx/caddy for production use.
"""

import json
import logging
from datetime import datetime
from flask import Flask, request, redirect, send_file, Response
from io import BytesIO
import requests

from .database import BeaconDatabase
from .models import BeaconHit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
db = BeaconDatabase()

# 1x1 transparent PNG for tracking pixels
TRACKING_PIXEL = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
        0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
        0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)


def get_real_ip() -> str:
    """Extract real IP, accounting for proxies."""
    # Check common proxy headers
    if request.headers.get("X-Forwarded-For"):
        # Take first IP in chain (original client)
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"]
    return request.remote_addr


def geolocate_ip(ip: str) -> dict | None:
    """Look up IP geolocation using free API."""
    if ip in ("127.0.0.1", "localhost", "::1"):
        return {"note": "localhost"}

    try:
        # ip-api.com - free, no key needed, 45 req/min limit
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return {
                    "country": data.get("country"),
                    "region": data.get("regionName"),
                    "city": data.get("city"),
                    "isp": data.get("isp"),
                    "org": data.get("org"),
                    "as": data.get("as"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "timezone": data.get("timezone"),
                }
    except Exception as e:
        logger.warning(f"Geolocation failed for {ip}: {e}")

    return None


def record_beacon_hit(token_id: int, extra_data: dict = None):
    """Record a hit on a beacon token."""
    ip = get_real_ip()
    geo = geolocate_ip(ip)

    hit = BeaconHit(
        id=None,
        token_id=token_id,
        hit_at=datetime.utcnow(),
        source_ip=ip,
        ip_geolocation=json.dumps(geo) if geo else None,
        user_agent=request.headers.get("User-Agent"),
        referer=request.headers.get("Referer"),
        hostname=extra_data.get("hostname") if extra_data else None,
        os_version=extra_data.get("os") if extra_data else None,
        username=extra_data.get("username") if extra_data else None,
        raw_headers=json.dumps(dict(request.headers)),
    )

    hit_id = db.record_hit(hit)
    logger.info(f"Beacon hit recorded: token={token_id}, ip={ip}, hit_id={hit_id}")

    # Log geolocation if available
    if geo:
        location = f"{geo.get('city', '?')}, {geo.get('region', '?')}, {geo.get('country', '?')}"
        logger.info(f"  Location: {location}")
        logger.info(f"  ISP: {geo.get('isp', 'unknown')}")

    return hit_id


# ============================================================
# Tracking endpoints
# ============================================================


@app.route("/t/<token_id>")
def track_link(token_id: str):
    """
    Simple tracking link. Logs hit and redirects to target URL.

    Usage: Create token with token_url pointing here, include redirect target
    in database or as query param.

    Example: /t/abc123?r=https://google.com
    """
    try:
        tid = int(token_id)
        record_beacon_hit(tid)
    except (ValueError, TypeError):
        logger.warning(f"Invalid token_id: {token_id}")

    # Redirect to target if provided
    redirect_url = request.args.get("r", "https://google.com")
    return redirect(redirect_url)


@app.route("/p/<token_id>.png")
def tracking_pixel(token_id: str):
    """
    1x1 transparent tracking pixel.

    Embed in emails or HTML: <img src="https://yourserver/p/123.png">
    """
    try:
        tid = int(token_id)
        record_beacon_hit(tid)
    except (ValueError, TypeError):
        logger.warning(f"Invalid token_id: {token_id}")

    return Response(TRACKING_PIXEL, mimetype="image/png")


@app.route("/b/<token_id>", methods=["GET", "POST"])
def beacon_callback(token_id: str):
    """
    Callback endpoint for executable/document beacons.

    Beacons can POST system info:
    {
        "hostname": "DESKTOP-ABC123",
        "username": "john",
        "os": "Windows 10 Pro 19045"
    }
    """
    extra_data = {}

    if request.method == "POST":
        try:
            extra_data = request.get_json() or {}
        except Exception:
            pass

    # Also check query params for GET requests
    if request.method == "GET":
        extra_data = {
            "hostname": request.args.get("h"),
            "username": request.args.get("u"),
            "os": request.args.get("o"),
        }
        extra_data = {k: v for k, v in extra_data.items() if v}

    try:
        tid = int(token_id)
        record_beacon_hit(tid, extra_data)
    except (ValueError, TypeError):
        logger.warning(f"Invalid token_id: {token_id}")

    # Return minimal response
    return "", 204


@app.route("/gift-card-checker")
def fake_gift_card_checker():
    """
    Fake gift card balance checker page.

    When scammer tries to "check" the gift card balance, we capture their info.
    Token ID passed via query param: /gift-card-checker?t=123
    """
    token_id = request.args.get("t")

    if token_id:
        try:
            tid = int(token_id)
            record_beacon_hit(tid)
        except (ValueError, TypeError):
            pass

    # Return a believable "checking" page that eventually shows an error
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gift Card Balance Checker</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
            .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%;
                       width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            .error { color: #c00; margin-top: 20px; }
            #result { display: none; }
        </style>
    </head>
    <body>
        <h1>Gift Card Balance Checker</h1>
        <div id="checking">
            <p>Checking card balance, please wait...</p>
            <div class="spinner"></div>
        </div>
        <div id="result">
            <p class="error">Unable to retrieve balance. The card may have already been redeemed
            or the code is invalid. Please try again later or contact customer support.</p>
        </div>
        <script>
            setTimeout(function() {
                document.getElementById('checking').style.display = 'none';
                document.getElementById('result').style.display = 'block';
            }, 4000);
        </script>
    </body>
    </html>
    """


# ============================================================
# Dashboard / monitoring
# ============================================================


@app.route("/")
def dashboard():
    """Simple dashboard showing recent hits."""
    recent = db.get_recent_hits(limit=50)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Beacon Dashboard</title>
        <style>
            body { font-family: monospace; padding: 20px; background: #1a1a1a; color: #0f0; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #333; padding: 8px; text-align: left; }
            th { background: #333; }
            tr:hover { background: #222; }
            .ip { color: #f90; }
            .location { color: #0ff; }
        </style>
        <meta http-equiv="refresh" content="30">
    </head>
    <body>
        <h1>Beacon Hits</h1>
        <table>
            <tr>
                <th>Time</th>
                <th>Token</th>
                <th>IP</th>
                <th>Location</th>
                <th>User Agent</th>
                <th>System Info</th>
            </tr>
    """

    for hit, token in recent:
        geo = json.loads(hit.ip_geolocation) if hit.ip_geolocation else {}
        location = f"{geo.get('city', '?')}, {geo.get('country', '?')}" if geo else "?"
        system_info = ""
        if hit.hostname or hit.username:
            system_info = f"{hit.username or '?'}@{hit.hostname or '?'}"

        html += f"""
            <tr>
                <td>{hit.hit_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                <td>{token.bait_description if token else '?'} ({token.token_type if token else '?'})</td>
                <td class="ip">{hit.source_ip}</td>
                <td class="location">{location}</td>
                <td>{(hit.user_agent or '')[:50]}...</td>
                <td>{system_info}</td>
            </tr>
        """

    html += """
        </table>
        <p><small>Auto-refreshes every 30 seconds</small></p>
    </body>
    </html>
    """

    return html


# ============================================================
# API for programmatic access
# ============================================================


@app.route("/api/hits/<conversation_id>")
def api_get_intel(conversation_id: str):
    """Get aggregated intel for a conversation."""
    intel = db.get_intel_for_conversation(conversation_id)

    if not intel:
        return {"error": "No intel found"}, 404

    return {
        "conversation_id": intel.conversation_id,
        "known_ips": intel.known_ips,
        "known_locations": intel.known_locations,
        "known_hostnames": intel.known_hostnames,
        "known_usernames": intel.known_usernames,
        "user_agents": intel.user_agents,
        "first_seen": intel.first_seen.isoformat(),
        "last_seen": intel.last_seen.isoformat(),
        "total_hits": intel.total_hits,
    }


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """Run the beacon callback server."""
    logger.info(f"Starting beacon callback server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server(debug=True)
