import os
import secrets
import smtplib
import sqlite3
from datetime import datetime
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "pearlshore.db"


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-this-secret"),
    DATABASE=str(DATABASE),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

DEFAULT_SERVICES = [
    (
        "Product Development & Engineering",
        "product",
        "We design and build scalable, high-performance digital products tailored to business goals.",
        "Mobile apps, websites, e-commerce, custom web applications, web scraping, chatbots, automation testing",
        "Python, Flask, React, JavaScript, REST APIs, PostgreSQL, MongoDB, Docker",
        1,
    ),
    (
        "UI/UX & Brand Experience",
        "design",
        "We create intuitive digital experiences that strengthen brand identity and improve engagement.",
        "UX research, wireframing, prototyping, product redesign, design systems, brand positioning",
        "Figma, FigJam, Adobe Creative Cloud, usability testing, analytics",
        2,
    ),
    (
        "Digital Growth & Marketing",
        "growth",
        "We help businesses grow through data-driven strategy and measurable digital campaigns.",
        "Digital strategy, social media, content marketing, SEO, video and digital content production",
        "Google Analytics, Search Console, Meta Business Suite, SEO platforms, CRM tools",
        3,
    ),
]

DEFAULT_CONTENT = {
    "hero_eyebrow": "Technology with purpose",
    "hero_title": "We build digital products that move businesses forward.",
    "hero_text": (
        "Pearlshore Technologies blends product engineering, thoughtful design, "
        "and growth strategy to turn ambitious ideas into dependable digital experiences."
    ),
    "about_intro": (
        "We are a Chennai-based technology studio helping organizations launch, "
        "modernize, and scale products with clarity and confidence."
    ),
    "phone": "+91 00000 00000",
    "location": "Chennai, India",
}


def get_db():
    if "db" not in g:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT 'product',
            description TEXT NOT NULL,
            benefits TEXT NOT NULL,
            technologies TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            service TEXT,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            email_status TEXT NOT NULL DEFAULT 'pending',
            email_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS site_content (
            content_key TEXT PRIMARY KEY,
            content_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    inquiry_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    if "email_status" not in inquiry_columns:
        db.execute(
            "ALTER TABLE inquiries ADD COLUMN email_status TEXT NOT NULL DEFAULT 'pending'"
        )
    if "email_error" not in inquiry_columns:
        db.execute("ALTER TABLE inquiries ADD COLUMN email_error TEXT")

    if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
        db.executemany(
            """
            INSERT INTO services
            (title, icon, description, benefits, technologies, display_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            DEFAULT_SERVICES,
        )

    for key, value in DEFAULT_CONTENT.items():
        db.execute(
            "INSERT OR IGNORE INTO site_content (content_key, content_value) VALUES (?, ?)",
            (key, value),
        )

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@pearlshore.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    if not db.execute("SELECT id FROM admins WHERE email = ?", (admin_email,)).fetchone():
        db.execute(
            "INSERT INTO admins (email, password_hash) VALUES (?, ?)",
            (admin_email, generate_password_hash(admin_password)),
        )
    db.commit()


def get_content():
    rows = get_db().execute(
        "SELECT content_key, content_value FROM site_content"
    ).fetchall()
    return {row["content_key"]: row["content_value"] for row in rows}


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(24)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["current_year"] = datetime.now().year


def validate_csrf():
    supplied = request.form.get("_csrf_token", "")
    expected = session.get("_csrf_token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "Invalid form token.")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def send_inquiry_email(inquiry):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not all([smtp_host, smtp_user, smtp_password]):
        return False, "SMTP is not configured."

    message = EmailMessage()
    message["Subject"] = f"New Pearlshore inquiry from {inquiry['name']}"
    message["From"] = smtp_user
    message["To"] = os.environ.get("CONTACT_EMAIL", "kamalasruthi03@gmail.com")
    message["Reply-To"] = inquiry["email"]
    message.set_content(
        "\n".join(
            [
                f"Name: {inquiry['name']}",
                f"Email: {inquiry['email']}",
                f"Phone: {inquiry['phone']}",
                f"Service: {inquiry['service']}",
                "",
                inquiry["message"],
            ]
        )
    )
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_class(smtp_host, port, timeout=12) as smtp:
            if not use_ssl:
                smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
        return True, ""
    except (OSError, smtplib.SMTPException) as error:
        app.logger.exception("Could not send inquiry email")
        return False, str(error)[:500]


@app.context_processor
def inject_globals():
    return {"site_content": get_content()}


@app.route("/")
def home():
    services = get_db().execute(
        "SELECT * FROM services WHERE is_active = 1 ORDER BY display_order, id LIMIT 3"
    ).fetchall()
    return render_template("home.html", services=services)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/services")
def services():
    rows = get_db().execute(
        "SELECT * FROM services WHERE is_active = 1 ORDER BY display_order, id"
    ).fetchall()
    return render_template("services.html", services=rows)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    service_rows = get_db().execute(
        "SELECT title FROM services WHERE is_active = 1 ORDER BY display_order, id"
    ).fetchall()
    if request.method == "POST":
        validate_csrf()
        fields = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "phone": request.form.get("phone", "").strip(),
            "service": request.form.get("service", "").strip(),
            "message": request.form.get("message", "").strip(),
        }
        if not fields["name"] or "@" not in fields["email"] or not fields["message"]:
            flash("Please provide your name, a valid email, and a message.", "error")
            return render_template(
                "contact.html", services=service_rows, form_data=fields
            ), 400

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO inquiries (name, email, phone, service, message)
            VALUES (:name, :email, :phone, :service, :message)
            """,
            fields,
        )
        db.commit()
        sent, email_error = send_inquiry_email(fields)
        db.execute(
            """
            UPDATE inquiries
            SET email_status = ?, email_error = ?
            WHERE id = ?
            """,
            ("sent" if sent else "failed", email_error or None, cursor.lastrowid),
        )
        db.commit()
        flash("Thank you. Your message has been received.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", services=service_rows, form_data={})


@app.post("/subscribe")
def subscribe():
    validate_csrf()
    email = request.form.get("email", "").strip().lower()
    if "@" not in email:
        flash("Enter a valid email address.", "error")
    else:
        try:
            get_db().execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
            get_db().commit()
            flash("You are on the list. Welcome.", "success")
        except sqlite3.IntegrityError:
            flash("That email is already subscribed.", "info")
    return redirect(request.referrer or url_for("home"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        validate_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = get_db().execute(
            "SELECT * FROM admins WHERE email = ?", (email,)
        ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_email"] = admin["email"]
            session["_csrf_token"] = secrets.token_hex(24)
            return redirect(url_for("admin_dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("admin/login.html")


@app.post("/admin/logout")
@admin_required
def admin_logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "services": db.execute("SELECT COUNT(*) FROM services").fetchone()[0],
        "inquiries": db.execute("SELECT COUNT(*) FROM inquiries").fetchone()[0],
        "new_inquiries": db.execute(
            "SELECT COUNT(*) FROM inquiries WHERE status = 'new'"
        ).fetchone()[0],
        "subscribers": db.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0],
    }
    inquiries = db.execute(
        "SELECT * FROM inquiries ORDER BY created_at DESC LIMIT 8"
    ).fetchall()
    return render_template(
        "admin/dashboard.html", stats=stats, inquiries=inquiries
    )


@app.route("/admin/services")
@admin_required
def admin_services():
    rows = get_db().execute(
        "SELECT * FROM services ORDER BY display_order, id"
    ).fetchall()
    return render_template("admin/services.html", services=rows)


@app.route("/admin/services/new", methods=["GET", "POST"])
@admin_required
def admin_service_new():
    if request.method == "POST":
        validate_csrf()
        values = service_form_values()
        if not values["title"] or not values["description"]:
            flash("Title and description are required.", "error")
        else:
            get_db().execute(
                """
                INSERT INTO services
                (title, icon, description, benefits, technologies, display_order, is_active)
                VALUES (:title, :icon, :description, :benefits, :technologies,
                        :display_order, :is_active)
                """,
                values,
            )
            get_db().commit()
            flash("Service created.", "success")
            return redirect(url_for("admin_services"))
    return render_template("admin/service_form.html", service=None)


@app.route("/admin/services/<int:service_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_service_edit(service_id):
    service = get_db().execute(
        "SELECT * FROM services WHERE id = ?", (service_id,)
    ).fetchone()
    if service is None:
        abort(404)
    if request.method == "POST":
        validate_csrf()
        values = service_form_values()
        values["id"] = service_id
        get_db().execute(
            """
            UPDATE services SET
                title = :title, icon = :icon, description = :description,
                benefits = :benefits, technologies = :technologies,
                display_order = :display_order, is_active = :is_active,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """,
            values,
        )
        get_db().commit()
        flash("Service updated.", "success")
        return redirect(url_for("admin_services"))
    return render_template("admin/service_form.html", service=service)


@app.post("/admin/services/<int:service_id>/delete")
@admin_required
def admin_service_delete(service_id):
    validate_csrf()
    get_db().execute("DELETE FROM services WHERE id = ?", (service_id,))
    get_db().commit()
    flash("Service deleted.", "success")
    return redirect(url_for("admin_services"))


def service_form_values():
    try:
        display_order = int(request.form.get("display_order", "0"))
    except ValueError:
        display_order = 0
    return {
        "title": request.form.get("title", "").strip(),
        "icon": request.form.get("icon", "product").strip(),
        "description": request.form.get("description", "").strip(),
        "benefits": request.form.get("benefits", "").strip(),
        "technologies": request.form.get("technologies", "").strip(),
        "display_order": display_order,
        "is_active": 1 if request.form.get("is_active") else 0,
    }


@app.route("/admin/content", methods=["GET", "POST"])
@admin_required
def admin_content():
    if request.method == "POST":
        validate_csrf()
        db = get_db()
        for key in DEFAULT_CONTENT:
            value = request.form.get(key, "").strip()
            db.execute(
                """
                INSERT INTO site_content (content_key, content_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(content_key) DO UPDATE SET
                    content_value = excluded.content_value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
        db.commit()
        flash("Website content updated.", "success")
        return redirect(url_for("admin_content"))
    return render_template("admin/content.html", content=get_content())


@app.route("/admin/inquiries")
@admin_required
def admin_inquiries():
    rows = get_db().execute(
        "SELECT * FROM inquiries ORDER BY created_at DESC"
    ).fetchall()
    return render_template("admin/inquiries.html", inquiries=rows)


@app.post("/admin/inquiries/<int:inquiry_id>/status")
@admin_required
def admin_inquiry_status(inquiry_id):
    validate_csrf()
    status = request.form.get("status", "new")
    if status not in {"new", "contacted", "closed"}:
        abort(400)
    get_db().execute(
        "UPDATE inquiries SET status = ? WHERE id = ?", (status, inquiry_id)
    )
    get_db().commit()
    flash("Inquiry status updated.", "success")
    return redirect(request.referrer or url_for("admin_inquiries"))


@app.post("/admin/inquiries/<int:inquiry_id>/delete")
@admin_required
def admin_inquiry_delete(inquiry_id):
    validate_csrf()
    get_db().execute("DELETE FROM inquiries WHERE id = ?", (inquiry_id,))
    get_db().commit()
    flash("Inquiry deleted.", "success")
    return redirect(url_for("admin_inquiries"))


@app.errorhandler(404)
def page_not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template("400.html", message=error.description), 400


with app.app_context():
    init_db()


if __name__ == "__main__":
    # Render requires the application to listen on 0.0.0.0.
    # Render provides PORT automatically; 10000 is a local fallback.
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
