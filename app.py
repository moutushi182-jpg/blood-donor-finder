
import os
import hmac
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

app = Flask(__name__)

# ---------------- CONFIGURATION ----------------

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-key-change-before-deployment"
)

DATABASE = Path(__file__).resolve().parent / "donors.db"

VALID_BLOOD_GROUPS = {
    "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"
}

VALID_URGENCY_LEVELS = {
    "Routine", "Urgent", "Emergency"
}


# ---------------- DATABASE CONNECTION ----------------

def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db_connection()

    # Donor table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS donors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            city TEXT NOT NULL,
            phone TEXT NOT NULL
        )
    """)

    # Blood request table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS blood_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_name TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            city TEXT NOT NULL,
            units INTEGER NOT NULL,
            hospital TEXT NOT NULL,
            contact TEXT NOT NULL,
            urgency TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


# ---------------- ADMIN AUTHENTICATION ----------------

def admin_required(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Please log in as an administrator.")
            return redirect(url_for("admin_login"))

        return view_function(*args, **kwargs)

    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin_username = os.environ.get("ADMIN_USERNAME")
        admin_password = os.environ.get("ADMIN_PASSWORD")

        if not admin_username or not admin_password:
            flash("Admin credentials are not configured.")
            return render_template("admin_login.html"), 503

        username_valid = hmac.compare_digest(
            username, admin_username
        )

        password_valid = hmac.compare_digest(
            password, admin_password
        )

        if username_valid and password_valid:
            session.clear()
            session["is_admin"] = True

            flash("Admin login successful!")
            return redirect(url_for("admin_dashboard"))

        flash("Invalid username or password.")

    return render_template("admin_login.html")


# ---------------- ADMIN DASHBOARD ----------------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    connection = get_db_connection()

    donors = connection.execute("""
        SELECT id, name, blood_group, city, phone
        FROM donors
        ORDER BY id DESC
    """).fetchall()

    blood_requests = connection.execute("""
        SELECT id, requester_name, blood_group, city,
               units, hospital, contact, urgency, created_at
        FROM blood_requests
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return render_template(
        "admin_dashboard.html",
        donors=donors,
        blood_requests=blood_requests
    )


# ---------------- DELETE DONOR ----------------

@app.route("/admin/delete/<int:donor_id>", methods=["POST"])
@admin_required
def delete_donor(donor_id):
    connection = get_db_connection()

    connection.execute(
        "DELETE FROM donors WHERE id = ?",
        (donor_id,)
    )

    connection.commit()
    connection.close()

    flash("Donor record deleted successfully.")
    return redirect(url_for("admin_dashboard"))


# ---------------- ADMIN LOGOUT ----------------

@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()
    flash("You have been logged out.")

    return redirect(url_for("admin_login"))


# ---------------- HOME PAGE AND DONOR SEARCH ----------------

@app.route("/")
def home():
    blood_group = request.args.get(
        "blood_group", ""
    ).strip()

    city = request.args.get("city", "").strip()

    donors = []

    if blood_group and city:
        if blood_group in VALID_BLOOD_GROUPS:
            connection = get_db_connection()

            donors = connection.execute("""
                SELECT id, name, blood_group, city
                FROM donors
                WHERE blood_group = ?
                  AND city LIKE ? COLLATE NOCASE
                ORDER BY name
            """, (
                blood_group,
                f"%{city}%"
            )).fetchall()

            connection.close()

    return render_template(
        "index.html",
        donors=donors,
        searched=bool(blood_group and city),
        blood_group=blood_group,
        city=city
    )


# ---------------- DONOR REGISTRATION ----------------

@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name", "").strip()

    blood_group = request.form.get(
        "blood_group", ""
    ).strip()

    city = request.form.get("city", "").strip()
    phone = request.form.get("phone", "").strip()
    consent = request.form.get("consent")

    if not consent:
        flash("Please provide consent before registering.")
        return redirect(
            url_for("home", _anchor="register")
        )

    if (
        not name
        or not city
        or not phone
        or blood_group not in VALID_BLOOD_GROUPS
    ):
        flash("Please fill in all fields correctly.")
        return redirect(
            url_for("home", _anchor="register")
        )

    if (
        len(name) > 100
        or len(city) > 100
        or not phone.isdigit()
        or len(phone) != 10
    ):
        flash("Please check your name, city and mobile number.")
        return redirect(
            url_for("home", _anchor="register")
        )

    connection = get_db_connection()

    connection.execute("""
        INSERT INTO donors (
            name, blood_group, city, phone
        )
        VALUES (?, ?, ?, ?)
    """, (
        name,
        blood_group,
        city,
        phone
    ))

    connection.commit()
    connection.close()

    flash(
        "Registration successful! "
        "Thank you for volunteering as a donor."
    )

    return redirect(
        url_for("home", _anchor="register")
    )


# ---------------- BLOOD REQUEST PAGE ----------------

@app.route("/blood-request")
def blood_request():
    return render_template("blood_request.html")


# ---------------- SUBMIT BLOOD REQUEST ----------------

@app.route("/blood-request/submit", methods=["POST"])
def submit_blood_request():
    requester_name = request.form.get(
        "requester_name", ""
    ).strip()

    blood_group = request.form.get(
        "blood_group", ""
    ).strip()

    city = request.form.get("city", "").strip()

    units_text = request.form.get("units", "").strip()

    hospital = request.form.get(
        "hospital", ""
    ).strip()

    contact = request.form.get(
        "contact", ""
    ).strip()

    urgency = request.form.get(
        "urgency", ""
    ).strip()

    if (
        not requester_name
        or not city
        or not hospital
        or blood_group not in VALID_BLOOD_GROUPS
        or urgency not in VALID_URGENCY_LEVELS
    ):
        flash("Please fill in all fields correctly.")
        return redirect(url_for("blood_request"))

    if (
        len(requester_name) > 100
        or len(city) > 100
        or len(hospital) > 150
    ):
        flash("Please check the length of the entered information.")
        return redirect(url_for("blood_request"))

    if not contact.isdigit() or len(contact) != 10:
        flash("Please enter a valid 10-digit contact number.")
        return redirect(url_for("blood_request"))

    try:
        units = int(units_text)
    except ValueError:
        flash("Please select a valid number of units.")
        return redirect(url_for("blood_request"))

    if units < 1 or units > 5:
        flash("Units must be between 1 and 5.")
        return redirect(url_for("blood_request"))

    connection = get_db_connection()

    connection.execute("""
        INSERT INTO blood_requests (
            requester_name,
            blood_group,
            city,
            units,
            hospital,
            contact,
            urgency
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        requester_name,
        blood_group,
        city,
        units,
        hospital,
        contact,
        urgency
    ))

    connection.commit()
    connection.close()

    flash(
        "Your blood request has been submitted successfully. "
        "For urgent medical needs, contact the hospital "
        "blood bank directly."
    )

    return redirect(url_for("blood_request"))


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
