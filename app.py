from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import csv
from flask import send_file


app = Flask(__name__)

app.secret_key = "supersecretkey"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///members.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "members.db")

# -------------------------------------------------
# LOGIN MANAGER
# -------------------------------------------------

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# -------------------------------------------------
# USER MODEL
# -------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

# -------------------------------------------------
# MEMBER MODEL
# -------------------------------------------------

class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    first = db.Column(db.String(100))
    last = db.Column(db.String(100))

    email = db.Column(db.String(120))

    amount = db.Column(db.Float)

    payment_date = db.Column(db.Date)

    expiry_date = db.Column(db.Date)

    status = db.Column(db.String(20), default="Active")

# -------------------------------------------------
# CREATE DATABASE
# -------------------------------------------------

with app.app_context():
    db.create_all()

    # Create default admin account
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", password="admin123")
        db.session.add(admin)
        db.session.commit()

# -------------------------------------------------
# DOWNLOAD DATABASE BACKUP
# -------------------------------------------------

import os
from flask import send_file, abort

@app.route("/backup-db")
@login_required
def backup_db():

    # Always build absolute path from current file location
    db_path = os.path.join(os.path.dirname(__file__), "members.db")

    # Debug safety check
    if not os.path.exists(db_path):
        return abort(404, description=f"DB not found at {db_path}")

    return send_file(
        db_path,
        as_attachment=True,
        download_name="members_backup.db",
        mimetype="application/octet-stream"
    )

# -------------------------------------------------
# RESTORE DATABASE
# -------------------------------------------------

@app.route("/restore-db", methods=["POST"])
@login_required
def restore_db():
    file = request.files.get("dbfile")

    if file:
        backup_path = os.path.join(BASE_DIR, "members_restore.db")
        file.save(backup_path)

    return redirect(url_for("index"))

# -------------------------------------------------
# LOGIN LOADER
# -------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------------------------------------------------
# AUTO STATUS CHECK
# -------------------------------------------------

def update_member_statuses():

    today = datetime.today().date()

    members = Member.query.all()

    for m in members:

        if m.expiry_date:

            days_left = (m.expiry_date - today).days

            if days_left < 0:
                m.status = "Lapsed"

            elif days_left <= 30:
                m.status = "Expiring"

            else:
                m.status = "Active"

    db.session.commit()

# -------------------------------------------------
# LOGIN
# -------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(
            username=username,
            password=password
        ).first()

        if user:
            login_user(user)
            return redirect(url_for("index"))

        flash("Invalid credentials")

    return render_template("login.html")

# -------------------------------------------------
# LOGOUT
# -------------------------------------------------

@app.route("/logout")
@login_required
def logout():

    logout_user()
    return redirect(url_for("login"))

# -------------------------------------------------
# DASHBOARD
# -------------------------------------------------

@app.route("/")
@login_required
def index():

    update_member_statuses()

    members = Member.query.all()

    total_members = len(members)

    active = len([m for m in members if m.status == "Active"])

    expiring = len([m for m in members if m.status == "Expiring"])

    lapsed = len([m for m in members if m.status == "Lapsed"])

    total_revenue = sum([m.amount or 0 for m in members])

    return render_template(
        "index.html",
        members=members,
        total_members=total_members,
        active=active,
        expiring=expiring,
        lapsed=lapsed,
        total_revenue=round(total_revenue, 2)
    )

# -------------------------------------------------
# ADD MEMBER
# -------------------------------------------------

@app.route("/add", methods=["POST"])
@login_required
def add():

    payment_date = datetime.strptime(
        request.form["payment_date"],
        "%Y-%m-%d"
    ).date()

    expiry_date = payment_date + timedelta(days=365)

    member = Member(
        first=request.form["first"],
        last=request.form["last"],
        email=request.form["email"],
        amount=float(request.form["amount"]),
        payment_date=payment_date,
        expiry_date=expiry_date
    )

    db.session.add(member)
    db.session.commit()

    return redirect(url_for("index"))

# -------------------------------------------------
# DELETE MEMBER
# -------------------------------------------------

@app.route("/delete/<int:id>")
@login_required
def delete(id):

    Member.query.filter_by(id=id).delete()

    db.session.commit()

    return redirect(url_for("index"))

# -------------------------------------------------
# CSV IMPORT
# -------------------------------------------------

@app.route("/import", methods=["POST"])
@login_required
def import_csv():

    file = request.files["file"]

    if file:

        stream = csv.reader(
            file.stream.read().decode("utf-8").splitlines()
        )

        next(stream)

        for row in stream:

            payment_date = datetime.strptime(
                row[4],
                "%Y-%m-%d"
            ).date()

            expiry_date = payment_date + timedelta(days=365)

            member = Member(
                first=row[0],
                last=row[1],
                email=row[2],
                amount=float(row[3]),
                payment_date=payment_date,
                expiry_date=expiry_date
            )

            db.session.add(member)

        db.session.commit()

    return redirect(url_for("index"))

# -------------------------------------------------
# EMAIL REMINDERS
# -------------------------------------------------

@app.route("/send-reminders")
@login_required
def reminders():

    expiring_members = Member.query.filter_by(
        status="Expiring"
    ).all()

    for m in expiring_members:

        print(f"Reminder sent to {m.email}")

    flash("Renewal reminders sent!")

    return redirect(url_for("index"))

# -------------------------------------------------
# BACKUP
# -------------------------------------------------

@app.route("/backup")
@login_required
def backup():

    members = Member.query.all()

    csv_data = "first,last,email,amount,payment_date\n"

    for m in members:

        csv_data += (
            f"{m.first},"
            f"{m.last},"
            f"{m.email},"
            f"{m.amount},"
            f"{m.payment_date}\n"
        )

    return csv_data

# -------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
