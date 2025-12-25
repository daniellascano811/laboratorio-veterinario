import os
import sqlite3
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render Postgres
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")  # Local fallback

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "1")  # "1" o "0"


# =========================
# DB helpers (Postgres o SQLite)
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def get_pg_conn():
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        join_char = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{join_char}sslmode=require"
    return psycopg.connect(dsn, row_factory=dict_row)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    # Retorna (conn, engine)
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"


def fetchone_dict(row, engine):
    if row is None:
        return None
    if engine == "pg":
        return row
    return dict(row)


def fetchall_list(rows, engine):
    if engine == "pg":
        return rows
    return [dict(r) for r in rows]


def sql_placeholder(engine):
    return "%s" if engine == "pg" else "?"


# =========================
# INIT DB
# =========================
def init_db():
    conn, engine = get_db()
    cur = conn.cursor()

    if engine == "pg":
        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            password TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id SERIAL PRIMARY KEY,
            zona TEXT,
            dueno TEXT,
            tel TEXT,
            mascota TEXT,
            muestra TEXT,
            direccion TEXT,
            fecha DATE NULL,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            password TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zona TEXT,
            dueno TEXT,
            tel TEXT,
            mascota TEXT,
            muestra TEXT,
            direccion TEXT,
            fecha TEXT NULL,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

    # Admin
    ph = sql_placeholder(engine)
    cur.execute(f"SELECT * FROM usuarios WHERE usuario={ph}", (ADMIN_USER,))
    row = cur.fetchone()
    user = fetchone_dict(row, engine)

    if user is None:
        cur.execute(
            f"INSERT INTO usuarios (usuario, nombre, password) VALUES ({ph},{ph},{ph})",
            (ADMIN_USER, "Administrador", ADMIN_PASSWORD)
        )
    else:
        if FORCE_ADMIN_SYNC == "1":
            cur.execute(
                f"UPDATE usuarios SET password={ph} WHERE usuario={ph}",
                (ADMIN_PASSWORD, ADMIN_USER)
            )

    conn.commit()
    cur.close()
    conn.close()
    print(f"DB inicializada OK ({'Postgres' if engine=='pg' else 'SQLite'})")


try:
    init_db()
except Exception as e:
    print("init_db() error:", e)


# =========================
# AUTH
# =========================
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("formulario.html", active="form")


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    # Compat: si en algún template viejo venían otros nombres, los aceptamos también.
    zona = request.form.get("zona") or ""
    dueno = request.form.get("dueno") or request.form.get("dueno_nombre") or ""
    tel = request.form.get("tel") or request.form.get("dueno_telefono") or ""
    mascota = request.form.get("mascota") or request.form.get("mascota_nombre") or ""
    direccion = request.form.get("direccion") or ""

    muestra_tipo = request.form.get("muestra_tipo") or request.form.get("muestra") or ""
    muestra_otro = (request.form.get("muestra_otro") or "").strip()
    if muestra_tipo.lower() == "otro" and muestra_otro:
        muestra = f"Otro: {muestra_otro}"
    else:
        muestra = muestra_tipo

    fecha_str = (request.form.get("fecha") or "").strip()
    fecha = fecha_str if fecha_str else None

    horario = (request.form.get("horario") or "").strip() or None

    conn, engine = get_db()
    cur = conn.cursor()
    ph = sql_placeholder(engine)

    cur.execute(
        f"""
        INSERT INTO solicitudes
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        """,
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario)
    )

    conn.commit()
    cur.close()
    conn.close()

    return render_template("confirmacion.html", active="form")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        password = (request.form.get("password") or "").strip()

        conn, engine = get_db()
        cur = conn.cursor()
        ph = sql_placeholder(engine)

        cur.execute(
            f"SELECT * FROM usuarios WHERE usuario={ph} AND password={ph}",
            (usuario, password)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        user = fetchone_dict(row, engine)

        if user:
            session["logged_in"] = True
            session["usuario"] = user["usuario"]
            return redirect(url_for("ver_solicitudes"))
        else:
            error = "Usuario o clave incorrecta"

    return render_template("login.html", error=error, active="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/solicitudes")
@login_required
def ver_solicitudes():
    conn, engine = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM solicitudes
        ORDER BY creado DESC
        LIMIT 50
    """)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    solicitudes = fetchall_list(rows, engine)
    return render_template("solicitudes.html", solicitudes=solicitudes, active="solicitudes")


# Local run (Render usa gunicorn)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
