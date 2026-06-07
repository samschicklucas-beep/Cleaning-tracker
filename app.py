from flask import Flask, jsonify, request
import requests
import base64
import os

app = Flask(__name__)

API_KEY = os.environ.get("UPLISTING_API_KEY", "a399e4af-ae52-48c3-8893-1cc8f11c881e")
BASE64_KEY = base64.b64encode(API_KEY.encode()).decode()
AUTH = f"Basic {BASE64_KEY}"
BASE_URL = "https://connect.uplisting.io"

@app.route("/")
def index():
    return jsonify({"status": "Cleaning Tracker API running"})

@app.route("/api/properties")
def get_properties():
    r = requests.get(f"{BASE_URL}/properties", headers={"Authorization": AUTH, "Content-Type": "application/json"})
    response = jsonify(r.json())
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.route("/api/bookings")
def get_bookings():
    property_id = request.args.get("property_id")
    start = request.args.get("start_date", "2026-04-01")
    end = request.args.get("end_date", "2026-12-31")
    r = requests.get(
        f"{BASE_URL}/bookings?property_id={property_id}&start_date={start}&end_date={end}",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    response = jsonify(r.json())
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
