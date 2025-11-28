from flask import (
    Flask,
    render_template,
    request,
    make_response,
    redirect,
    url_for,
    session,
)
import sqlite3
from datetime import datetime
import csv
import io
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DB_NAME = "health_reports.db"
app.secret_key = "change_this_in_real_project"  # for sessions


# ---------- DB helpers ----------
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create users and reports tables, and ensure user_id column exists."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Users table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
        """
    )

    # Reports table (base definition)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            hb REAL,
            sugar REAL,
            bp_sys INTEGER,
            bp_dia INTEGER,
            chol REAL,
            height_cm REAL,
            weight_kg REAL,
            bmi REAL
        )
        """
    )

    # Ensure user_id column exists
    try:
        cur.execute("ALTER TABLE reports ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        # Column already exists, ignore
        pass

    conn.commit()
    conn.close()


def save_report(hb, sugar, bp_sys, bp_dia, chol, height_cm, weight_kg, bmi, user_id):
    """Insert one health report row."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reports (
            created_at, hb, sugar, bp_sys, bp_dia,
            chol, height_cm, weight_kg, bmi, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            hb,
            sugar,
            bp_sys,
            bp_dia,
            chol,
            height_cm,
            weight_kg,
            bmi,
            user_id,
        ),
    )
    conn.commit()
    conn.close()


def get_current_user():
    """Return (user_id, user_name) if logged in, else (None, None)."""
    return session.get("user_id"), session.get("user_name")


# ---------- Auth Routes ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    user_id, _ = get_current_user()
    if user_id:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not name or not email or not password:
            error = "All fields are required."
        else:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
            existing = cur.fetchone()
            if existing:
                error = "Email is already registered. Please login."
            else:
                password_hash = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO users (name, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        password_hash,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                user_id = cur.lastrowid
                conn.close()

                session["user_id"] = user_id
                session["user_name"] = name
                return redirect(url_for("index"))

            conn.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    user_id, _ = get_current_user()
    if user_id:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))
        else:
            error = "Invalid email or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- Analyzer Route ----------
@app.route("/", methods=["GET", "POST"])
def index():
    result = {}
    overall_summary = None
    bmi_value = None

    user_id, user_name = get_current_user()

    if request.method == "POST":
        hb_raw = request.form.get("hb") or None
        sugar_raw = request.form.get("sugar") or None
        bp_sys_raw = request.form.get("bp_sys") or None
        bp_dia_raw = request.form.get("bp_dia") or None
        chol_raw = request.form.get("chol") or None
        height_raw = request.form.get("height") or None
        weight_raw = request.form.get("weight") or None

        # 1) Hemoglobin
        try:
            hb = float(hb_raw)
            if hb < 12:
                result["Hemoglobin"] = (
                    "Low",
                    "Hemoglobin appears lower than the normal range. Consult a doctor if symptoms persist.",
                )
            elif hb > 16:
                result["Hemoglobin"] = (
                    "High",
                    "Hemoglobin appears higher than the normal range. A medical check-up is recommended.",
                )
            else:
                result["Hemoglobin"] = (
                    "Normal",
                    "Hemoglobin is within the normal range.",
                )
        except Exception:
            hb = None
            result["Hemoglobin"] = (
                "Error",
                "Please enter a valid Hemoglobin value.",
            )

        # 2) Fasting Sugar
        try:
            sugar = float(sugar_raw)
            if sugar < 70:
                result["Fasting Sugar"] = (
                    "Low",
                    "Low fasting sugar may cause dizziness or weakness.",
                )
            elif sugar > 125:
                result["Fasting Sugar"] = (
                    "High",
                    "Fasting sugar appears high and may indicate diabetes. Consult a doctor.",
                )
            else:
                result["Fasting Sugar"] = (
                    "Normal",
                    "Fasting sugar is within the normal range.",
                )
        except Exception:
            sugar = None
            result["Fasting Sugar"] = (
                "Error",
                "Please enter a valid sugar value.",
            )

        # 3) Blood Pressure
        try:
            bp_sys = int(bp_sys_raw)
            bp_dia = int(bp_dia_raw)
            if bp_sys < 90 or bp_dia < 60:
                result["Blood Pressure"] = (
                    "Low",
                    "Blood pressure is low. Hydration and rest may help.",
                )
            elif bp_sys > 140 or bp_dia > 90:
                result["Blood Pressure"] = (
                    "High",
                    "Blood pressure is high and may pose risks. A medical consultation is recommended.",
                )
            else:
                result["Blood Pressure"] = (
                    "Normal",
                    "Blood pressure is within the normal range.",
                )
        except Exception:
            bp_sys = bp_dia = None
            result["Blood Pressure"] = (
                "Error",
                "Please enter valid BP values.",
            )

        # 4) Cholesterol
        try:
            chol = float(chol_raw)
            if chol > 240:
                result["Cholesterol"] = (
                    "High",
                    "Cholesterol is high and may increase heart disease risk.",
                )
            elif chol > 200:
                result["Cholesterol"] = (
                    "Borderline",
                    "Cholesterol is borderline high. Healthy diet and lifestyle changes may help.",
                )
            else:
                result["Cholesterol"] = (
                    "Normal",
                    "Cholesterol is within a healthy range.",
                )
        except Exception:
            chol = None
            result["Cholesterol"] = (
                "Error",
                "Please enter a valid cholesterol value.",
            )

        # 5) BMI
        try:
            height_cm = float(height_raw)
            weight_kg = float(weight_raw)
            height_m = height_cm / 100.0
            bmi_value = weight_kg / (height_m * height_m)

            if bmi_value < 18.5:
                result["BMI"] = (
                    f"{bmi_value:.1f} (Underweight)",
                    "BMI indicates underweight. A balanced nutritious diet is recommended.",
                )
            elif bmi_value > 24.9:
                result["BMI"] = (
                    f"{bmi_value:.1f} (Overweight)",
                    "BMI indicates overweight. Regular exercise and diet control are advised.",
                )
            else:
                result["BMI"] = (
                    f"{bmi_value:.1f} (Normal)",
                    "BMI is within normal limits.",
                )
        except Exception:
            height_cm = weight_kg = None
            result["BMI"] = (
                "Error",
                "Please enter valid height and weight.",
            )

        # --------- Overall summary based on all statuses ----------
        if result:
            statuses = [v[0] for v in result.values()]

            if any(s == "Error" or s.startswith("Error") for s in statuses):
                overall_summary = (
                    "Data Issue",
                    "Some inputs were invalid. Please correct the highlighted fields and try again.",
                )
            else:
                abnormal_count = 0
                for s in statuses:
                    if (
                        s.startswith("High")
                        or s.startswith("Low")
                        or "Underweight" in s
                        or "Overweight" in s
                        or s == "Borderline"
                    ):
                        abnormal_count += 1

                if abnormal_count == 0:
                    overall_summary = (
                        "Stable / Normal",
                        "All tracked parameters appear within normal ranges. Maintain your current lifestyle and regular check-ups.",
                    )
                elif abnormal_count == 1:
                    overall_summary = (
                        "Mild Concern",
                        "One parameter needs attention. Monitor your health and consider lifestyle adjustments.",
                    )
                elif 2 <= abnormal_count <= 3:
                    overall_summary = (
                        "Needs Attention",
                        "Multiple parameters are outside the normal range. A detailed check-up and lifestyle review are recommended.",
                    )
                else:
                    overall_summary = (
                        "High Risk",
                        "Several parameters are abnormal. Please consult a doctor for a complete evaluation.",
                    )

        # Save only if all values are valid
        if all(
            v is not None
            for v in [hb, sugar, bp_sys, bp_dia, chol, height_cm, weight_kg, bmi_value]
        ):
            # if not logged in, user_id will be None (treated as guest)
            save_report(
                hb,
                sugar,
                bp_sys,
                bp_dia,
                chol,
                height_cm,
                weight_kg,
                bmi_value,
                user_id,
            )

    return render_template(
        "index.html",
        result=result,
        overall_summary=overall_summary,
        user_name=user_name,
        user_id=user_id,
    )


# ---------- History + Chart Data ----------
@app.route("/history")
def history():
    user_id, user_name = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()

    if user_id:
        cur.execute(
            """
            SELECT id, created_at, hb, sugar, bp_sys, bp_dia, chol,
                   height_cm, weight_kg, bmi, user_id
            FROM reports
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        )
    else:
        # Not logged in: show all reports (guest mode)
        cur.execute(
            """
            SELECT id, created_at, hb, sugar, bp_sys, bp_dia, chol,
                   height_cm, weight_kg, bmi, user_id
            FROM reports
            ORDER BY id ASC
            """
        )

    rows = cur.fetchall()
    conn.close()

    labels = [row[1] for row in rows]       # created_at timestamps
    sugar_values = [row[3] for row in rows] # fasting sugar
    bmi_values = [row[9] for row in rows]   # BMI

    return render_template(
        "history.html",
        reports=rows,
        labels=labels,
        sugar_values=sugar_values,
        bmi_values=bmi_values,
        user_name=user_name,
        user_id=user_id,
    )


# ---------- CSV Export ----------
@app.route("/export_csv")
def export_csv():
    user_id, _ = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()

    if user_id:
        cur.execute(
            """
            SELECT id, created_at, hb, sugar, bp_sys, bp_dia, chol,
                   height_cm, weight_kg, bmi
            FROM reports
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        )
    else:
        cur.execute(
            """
            SELECT id, created_at, hb, sugar, bp_sys, bp_dia, chol,
                   height_cm, weight_kg, bmi
            FROM reports
            ORDER BY id ASC
            """
        )

    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "Created At",
            "Hemoglobin",
            "Fasting Sugar",
            "BP Systolic",
            "BP Diastolic",
            "Cholesterol",
            "Height (cm)",
            "Weight (kg)",
            "BMI",
        ]
    )
    writer.writerows(rows)

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=health_reports.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


# ---------- Clear ALL History (for that user) ----------
@app.route("/clear_history")
def clear_history():
    user_id, _ = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()

    if user_id:
        cur.execute("DELETE FROM reports WHERE user_id = ?", (user_id,))
    else:
        # guest mode: clear everything
        cur.execute("DELETE FROM reports")

    conn.commit()
    conn.close()
    return redirect(url_for("history"))


# ---------- Delete SINGLE Report ----------
@app.route("/delete/<int:report_id>")
def delete_report(report_id):
    user_id, _ = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()

    if user_id:
        cur.execute(
            "DELETE FROM reports WHERE id = ? AND user_id = ?",
            (report_id, user_id),
        )
    else:
        cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    conn.commit()
    conn.close()
    return redirect(url_for("history"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
