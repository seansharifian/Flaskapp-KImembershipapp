from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from flask import send_file
import shutil

import sys

import os

import csv
from datetime import datetime
from dotenv import load_dotenv

app = Flask(__name__)
BACKUP_FOLDER = "backups"

os.makedirs(BACKUP_FOLDER, exist_ok=True)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "change_this_in_production"
)

EMAIL = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

def get_db():
    conn = sqlite3.connect(
    "members.db",
    check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn

def validate_database(db_path):
    try:
        conn = sqlite3.connect(db_path)

        # Check integrity
        result = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        # Verify members table exists
        tables = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='members'
            """
        ).fetchone()

        conn.close()

        return result == "ok" and tables is not None

    except Exception:
        return False

def restart_app():
    os.execv(sys.executable, ['python'] + sys.argv)

def normalize_date(date_str):
    if not date_str:
        return datetime.today().strftime("%Y-%m-%d")

    date_str = date_str.strip()

    formats = [
        "%Y-%m-%d",   # 2025-01-31
        "%m/%d/%Y",   # 01/31/2025
        "%m-%d-%Y",   # 01-31-2025
        "%d/%m/%Y",   # 31/01/2025
        "%d-%m-%Y",   # 31-01-2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # fallback to today's date if invalid
    return datetime.today().strftime("%Y-%m-%d")

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            email TEXT UNIQUE,
            status TEXT,
            last_payment TEXT,
            amount_paid REAL,
            last_reminder TEXT
        )
    ''')
    conn.commit()
    conn.close()

def update_membership_status():
    conn = get_db()
    members = conn.execute("SELECT * FROM members").fetchall()
    today = datetime.today().date()

    for m in members:
        if m["last_payment"]:
            last_payment = datetime.strptime(m["last_payment"], "%Y-%m-%d").date()

            if today > last_payment + timedelta(days=365):
                status = "Lapsed"
            elif today > last_payment + timedelta(days=335):
                status = "Expiring Soon"
            else:
                status = "Active"

            conn.execute("UPDATE members SET status=? WHERE id=?", (status, m["id"]))

    conn.commit()
    conn.close()

def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL, APP_PASSWORD)
        server.send_message(msg)

def send_reminder(member):
    if not member["email"]:
        return

    today = datetime.today().date()

    if member["last_reminder"]:
        last = datetime.strptime(member["last_reminder"], "%Y-%m-%d").date()
        if today <= last + timedelta(days=30):
            return

    send_email(
        member["email"],
        "Membership Renewal Reminder",
        f"""Hello {member['first_name']},

Your membership is {member['status']}.
Please renew your membership.

Thank you!"""
    )

    conn = get_db()
    conn.execute(
        "UPDATE members SET last_reminder=? WHERE id=?",
        (today.strftime("%Y-%m-%d"), member["id"])
    )
    conn.commit()
    conn.close()

@app.route("/backup")
def backup_database():

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_name = os.path.join(
        BACKUP_FOLDER,
        f"members_backup_{timestamp}.db"
    )

    shutil.copy("members.db", backup_name)

    return send_file(
        backup_name,
        as_attachment=True
    )

@app.route("/restore", methods=["POST"])
def restore_database():

    file = request.files.get("backup_file")

    if not file:
        return "No file uploaded", 400

    temp_path = "temp_restore.db"

    try:
        # Save uploaded file temporarily
        file.save(temp_path)

        # Validate uploaded DB
        if not validate_database(temp_path):
            os.remove(temp_path)
            return "Invalid or corrupted database file", 400

        # Create auto-backup of current DB
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        auto_backup = os.path.join(
            BACKUP_FOLDER,
            f"auto_backup_before_restore_{timestamp}.db"
        )

        shutil.copy("members.db", auto_backup)

        # Replace current DB
        os.replace(temp_path, "members.db")

        # Restart app safely
        restart_app()

        return redirect("/")

    except Exception as e:

        if os.path.exists(temp_path):
            os.remove(temp_path)

        return f"Restore failed: {str(e)}", 500

@app.route("/")
def index():

    return render_template("index.html")

    if __name__ == "__main__":
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port)

    update_membership_status()

    conn = get_db()

    members = conn.execute(
        "SELECT * FROM members"
    ).fetchall()

    total_members = conn.execute(
        "SELECT COUNT(*) FROM members"
    ).fetchone()[0]

    active_members = conn.execute(
        "SELECT COUNT(*) FROM members WHERE status='Active'"
    ).fetchone()[0]

    expiring_members = conn.execute(
        """
        SELECT COUNT(*)
        FROM members
        WHERE status='Expiring Soon'
        """
    ).fetchone()[0]

    lapsed_members = conn.execute(
        """
        SELECT COUNT(*)
        FROM members
        WHERE status='Lapsed'
        """
    ).fetchone()[0]

    total_revenue = conn.execute(
        """
        SELECT SUM(amount_paid)
        FROM members
        """
    ).fetchone()[0]

    # Prevent None errors
    if total_revenue is None:
        total_revenue = 0

    conn.close()

    today = datetime.today().strftime("%Y-%m-%d")

    return render_template(
        "index.html",
        members=members,
        today=today,
        total_members=total_members,
        active_members=active_members,
        expiring_members=expiring_members,
        lapsed_members=lapsed_members,
        total_revenue=total_revenue
    )

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_member(id):
    conn = get_db()

    if request.method == "POST":

        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        status = request.form.get("status")
        amount_paid = request.form.get("amount_paid")
        last_payment = normalize_date(
            request.form.get("last_payment")
        )

        conn.execute(
            """
            UPDATE members
            SET first_name=?,
                last_name=?,
                email=?,
                status=?,
                amount_paid=?,
                last_payment=?
            WHERE id=?
            """,
            (
                first_name,
                last_name,
                email,
                status,
                amount_paid,
                last_payment,
                id
            )
        )

        conn.commit()
        conn.close()

        return redirect("/")

    member = conn.execute(
        "SELECT * FROM members WHERE id=?",
        (id,)
    ).fetchone()

    conn.close()

    return render_template("edit.html", member=member)

@app.route("/delete/<int:id>")
def delete_member(id):

    conn = get_db()

    conn.execute(
        "DELETE FROM members WHERE id=?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/add", methods=["POST"])
def add():
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    amount = request.form.get("amount")
    payment_date = request.form.get("payment_date")

    if not payment_date:
        payment_date = datetime.today().strftime("%Y-%m-%d")

    conn = get_db()
    conn.execute(
        '''INSERT INTO members 
        (first_name, last_name, email, status, last_payment, amount_paid) 
        VALUES (?, ?, ?, ?, ?, ?)''',
        (first_name, last_name, email, "Active", payment_date, amount)
    )
    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/pay/<int:id>", methods=["POST"])
def pay(id):
    payment_date = request.form.get("payment_date")

    conn = get_db()
    conn.execute(
        "UPDATE members SET last_payment=?, status='Active' WHERE id=?",
        (payment_date, id)
    )
    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/remind/<int:id>")
def remind(id):
    conn = get_db()
    member = conn.execute("SELECT * FROM members WHERE id=?", (id,)).fetchone()
    conn.close()

    send_reminder(member)
    return redirect("/")

@app.route("/remind-all")
def remind_all():
    conn = get_db()
    members = conn.execute("SELECT * FROM members WHERE status != 'Active'").fetchall()
    conn.close()

    for m in members:
        send_reminder(m)

    return redirect("/")

init_db()

@app.route("/import-csv", methods=["POST"])
def import_csv():
    file = request.files.get("csv_file")

    if not file:
        return redirect("/")

    stream = file.stream.read().decode("UTF8").splitlines()
    csv_reader = csv.DictReader(stream)

    conn = get_db()

    for row in csv_reader:

        first_name = row.get("first_name", "").strip()
        last_name = row.get("last_name", "").strip()
        email = row.get("email", "").strip().lower()
        amount_paid = row.get("amount_paid", "").strip()

        last_payment_raw = row.get("last_payment", "")
        last_payment = normalize_date(last_payment_raw)

        # Skip completely empty rows
        if not first_name and not last_name and not email:
            continue

        # Convert amount safely
        try:
            amount_paid = float(amount_paid)
        except:
            amount_paid = 0

        # Check for existing email
        existing = None

        if email:
            existing = conn.execute(
                "SELECT * FROM members WHERE email=?",
                (email,)
            ).fetchone()

        if existing:
            # UPDATE existing member
            conn.execute(
                """
                UPDATE members
                SET first_name=?,
                    last_name=?,
                    amount_paid=?,
                    last_payment=?,
                    status='Active'
                WHERE email=?
                """,
                (
                    first_name,
                    last_name,
                    amount_paid,
                    last_payment,
                    email
                )
            )
        else:
            # INSERT new member
            conn.execute(
                """
                INSERT INTO members
                (first_name, last_name, email, status, last_payment, amount_paid)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    first_name,
                    last_name,
                    email,
                    "Active",
                    last_payment,
                    amount_paid
                )
            )

    conn.commit()
    conn.close()

    return redirect("/")
load_dotenv()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
