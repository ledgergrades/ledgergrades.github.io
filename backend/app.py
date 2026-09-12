"""
ledger grades API — same HAC login + scraping as before, but as a pure JSON API
so it can be called from a separately hosted static frontend (e.g. one on
GitHub Pages) instead of rendering pages itself.

No server-side session is used to hold grade data: each request is
self-contained, and the frontend is responsible for keeping the fetched
courses around (e.g. in sessionStorage) between page loads. The one bit
of server-side state that remains is the per-user grade *snapshot* file,
used to compute "change since last login" — that's just a JSON file keyed
by a hash of district+username, never a password.

Routes
------
POST /api/login    { district_url, username, password } -> { courses: [...] }
GET  /api/demo                                            -> { courses: [...] } (sample data)
POST /api/whatif   { category_averages, category_weights, hypothetical } -> { average, letter }
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from hac_scraper import (
    HACClient, HACLoginError, HACParseError, letter_grade, what_if, humanize_course_name,
)

app = Flask(__name__)

# Restrict this to your actual GitHub Pages origin in production.
# Add more origins (e.g. http://127.0.0.1:5500 for local testing) as needed.
ALLOWED_ORIGINS = os.environ.get(
    "LEDGERGRADES_ALLOWED_ORIGINS",
    "https://ledgergrades.github.io"
).split(",")

CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

SNAPSHOT_DIR = Path(__file__).parent / "instance" / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_PATH = Path(__file__).parent / "instance" / "analytics.json"

DEMO_GRADES = [
    {
        "course_name": "Biology (KGT)", "teacher": "K. Wilkinson", "period": "1",
        "average": 91.4,
        "categories": [
            {"name": "Tests", "weight": 50, "average": 89.0},
            {"name": "Labs", "weight": 30, "average": 94.0},
            {"name": "Homework", "weight": 20, "average": 96.0},
        ],
        "assignments": [
            {"name": "Unit 2 Test", "category": "Tests", "score": 92, "points_possible": 100},
            {"name": "Unit 3 Test", "category": "Tests", "score": 86, "points_possible": 100},
            {"name": "Titration Lab", "category": "Labs", "score": 96, "points_possible": 100},
            {"name": "Enzyme Lab", "category": "Labs", "score": 92, "points_possible": 100},
            {"name": "Ch 5 Problem Set", "category": "Homework", "score": 98, "points_possible": 100},
            {"name": "Ch 6 Problem Set", "category": "Homework", "score": 94, "points_possible": 100},
        ],
    },
    {
        "course_name": "World Geography (KGT)", "teacher": "C. Reid", "period": "2",
        "average": 83.2,
        "categories": [
            {"name": "Essays", "weight": 40, "average": 80.0},
            {"name": "Tests", "weight": 40, "average": 85.0},
            {"name": "Participation", "weight": 20, "average": 90.0},
        ],
        "assignments": [
            {"name": "Regional Essay", "category": "Essays", "score": 82, "points_possible": 100},
            {"name": "Climate Essay", "category": "Essays", "score": 78, "points_possible": 100},
            {"name": "Unit 4 Test", "category": "Tests", "score": 88, "points_possible": 100},
            {"name": "Unit 5 Test", "category": "Tests", "score": 82, "points_possible": 100},
            {"name": "Class Discussion Wk 3", "category": "Participation", "score": 90, "points_possible": 100},
            {"name": "Map Quiz Participation", "category": "Participation", "score": 90, "points_possible": 100},
        ],
    },
    {
        "course_name": "Algebra 2 (KGT)", "teacher": "J. Hlavinka", "period": "3",
        "average": 76.8,
        "categories": [
            {"name": "Tests", "weight": 60, "average": 72.0},
            {"name": "Quizzes", "weight": 25, "average": 80.0},
            {"name": "Homework", "weight": 15, "average": 98.0},
        ],
        "assignments": [
            {"name": "Chapter 4 Test", "category": "Tests", "score": 75, "points_possible": 100},
            {"name": "Chapter 5 Test", "category": "Tests", "score": 69, "points_possible": 100},
            {"name": "Quiz 6", "category": "Quizzes", "score": 84, "points_possible": 100},
            {"name": "Quiz 7", "category": "Quizzes", "score": 76, "points_possible": 100},
            {"name": "Homework Set 8", "category": "Homework", "score": 100, "points_possible": 100},
            {"name": "Homework Set 9", "category": "Homework", "score": 96, "points_possible": 100},
        ],
    },
    {
        "course_name": "English 1 (KGT)", "teacher": "S. King", "period": "4",
        "average": 58.9,
        "categories": [
            {"name": "Essays", "weight": 50, "average": 55.0},
            {"name": "Reading Quizzes", "weight": 30, "average": 60.0},
            {"name": "Participation", "weight": 20, "average": 70.0},
        ],
        "assignments": [
            {"name": "Narrative Essay", "category": "Essays", "score": 58, "points_possible": 100},
            {"name": "Analysis Essay", "category": "Essays", "score": 52, "points_possible": 100},
            {"name": "Ch 1-3 Reading Quiz", "category": "Reading Quizzes", "score": 65, "points_possible": 100},
            {"name": "Ch 4-6 Reading Quiz", "category": "Reading Quizzes", "score": 55, "points_possible": 100},
            {"name": "Discussion Wk 2", "category": "Participation", "score": 70, "points_possible": 100},
            {"name": "Group Work", "category": "Participation", "score": 70, "points_possible": 100},
        ],
    },
]


# ---------------------------------------------------------------------- #
# Snapshot storage (for the "shift since last login" tracker)
# ---------------------------------------------------------------------- #

def _user_key(district: str, username: str) -> str:
    raw = f"{district}:{username}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def load_previous_snapshot(district: str, username: str) -> dict:
    path = SNAPSHOT_DIR / f"{_user_key(district, username)}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_snapshot(district: str, username: str, courses: list[dict]) -> None:
    path = SNAPSHOT_DIR / f"{_user_key(district, username)}.json"
    snapshot = {c["course_name"]: c["average"] for c in courses if c["average"] is not None}
    path.write_text(json.dumps(snapshot))


def attach_shifts(courses: list[dict], previous: dict) -> list[dict]:
    for c in courses:
        prev = previous.get(c["course_name"])
        if prev is not None and c["average"] is not None:
            c["shift"] = round(c["average"] - prev, 2)
        else:
            c["shift"] = None
        c["letter"] = letter_grade(c["average"])
        for cat in c.get("categories", []):
            cat["letter"] = letter_grade(cat.get("average"))
    return courses


# ---------------------------------------------------------------------- #
# Routes
# ---------------------------------------------------------------------- #

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    district_url = (data.get("district_url") or "").strip()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not (district_url and username and password):
        return jsonify({"error": "All fields are required."}), 400

    try:
        client = HACClient(base_url=district_url)
        client.login(username, password)
        courses = client.get_grades()
    except HACLoginError as e:
        return jsonify({"error": str(e)}), 401
    except HACParseError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:  # network errors, bad URL, etc.
        return jsonify({"error": f"Couldn't reach that HAC site ({e})."}), 502

    def _clean(text: str | None) -> str:
        return (text or "").replace("*", "").strip()

    courses_dicts = [
        {
            "course_name": humanize_course_name(c.course_name), "teacher": c.teacher, "period": c.period,
            "average": c.average,
            "categories": [
                {"name": _clean(cat.name), "weight": cat.weight, "average": cat.average}
                for cat in c.categories
            ],
            "assignments": [
                {
                    "name": _clean(a.name), "category": _clean(a.category),
                    "score": a.score, "points_possible": a.points_possible,
                }
                for a in c.assignments
            ],
        }
        for c in courses
    ]

    previous = load_previous_snapshot(district_url, username)
    courses_dicts = attach_shifts(courses_dicts, previous)
    save_snapshot(district_url, username, courses_dicts)

    return jsonify({"courses": courses_dicts})


@app.route("/api/demo")
def api_demo():
    previous = load_previous_snapshot("demo", "demo-student")
    courses = attach_shifts(copy.deepcopy(DEMO_GRADES), previous)
    save_snapshot("demo", "demo-student", courses)
    return jsonify({"courses": courses})


@app.route("/api/whatif", methods=["POST"])
def api_whatif():
    data = request.get_json(force=True) or {}
    category_averages = {k: float(v) for k, v in data.get("category_averages", {}).items()}
    category_weights = {k: float(v) for k, v in data.get("category_weights", {}).items()}
    hypothetical = {k: [float(x) for x in v] for k, v in data.get("hypothetical", {}).items()}

    new_average = what_if(category_averages, category_weights, hypothetical)
    return jsonify({"average": new_average, "letter": letter_grade(new_average)})


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------- #
# View counter — daily + all-time views and unique viewers
# ---------------------------------------------------------------------- #

def load_analytics() -> dict:
    if ANALYTICS_PATH.exists():
        return json.loads(ANALYTICS_PATH.read_text())
    return {"days": {}, "all_time_visitors": [], "total_views": 0}


def save_analytics(data: dict) -> None:
    ANALYTICS_PATH.write_text(json.dumps(data))


@app.route("/api/track-view", methods=["POST"])
def track_view():
    data = request.get_json(force=True) or {}
    visitor_id = (data.get("visitor_id") or "").strip()
    if not visitor_id:
        return jsonify({"error": "visitor_id is required"}), 400

    analytics = load_analytics()
    today = date.today().isoformat()

    day = analytics["days"].setdefault(today, {"views": 0, "visitors": []})
    day["views"] += 1
    if visitor_id not in day["visitors"]:
        day["visitors"].append(visitor_id)

    if visitor_id not in analytics["all_time_visitors"]:
        analytics["all_time_visitors"].append(visitor_id)
    analytics["total_views"] = analytics.get("total_views", 0) + 1

    save_analytics(analytics)
    return jsonify({"ok": True})


@app.route("/api/stats")
def stats():
    analytics = load_analytics()
    today = date.today()

    days_out = []
    for i in range(6, -1, -1):  # 6 days ago ... today = 7 days total
        d = (today - timedelta(days=i)).isoformat()
        day_data = analytics["days"].get(d, {"views": 0, "visitors": []})
        days_out.append({
            "date": d,
            "views": day_data["views"],
            "uniques": len(day_data["visitors"]),
        })

    return jsonify({
        "days": days_out,
        "total_views": analytics.get("total_views", 0),
        "total_uniques": len(analytics.get("all_time_visitors", [])),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
