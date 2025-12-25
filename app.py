import os
import re
import sqlite3
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)

# =========================
# CONFIG
# =========================
app = Flask(__name__)

# SECRET_KEY (para sesiones)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# Variables
DATABASE_URL_RAW = os.environ.get("DATABASE_URL")  # Render Postgres
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")  # Local

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")


# =========================
# HELPERS: SANITIZE DATABASE_URL
# =========================
def clean_database_url(url: str | None) -> str | None:
    if not url:
        return None

    # 1) quitar espacios extremos y comillas envolventes
    dsn = url.strip().strip('"').strip("'")

    # 2) quitar saltos de línea / tabs invisibles dentro (esto mata el sslmode roto)
    dsn = re.sub(r"[\r\n\t ]+", "", dsn)

    # 3) normalizar scheme
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]

    # 4) si ya viene sslmode, arreglarlo:
    #    - quita comillas del valor (sslmode="require" -> sslmode=require)
    dsn = re.sub(r"sslmode=['\"]?([^&'\"]+)['\"]?", r"sslmode=\1", dsn)

    # 5) forzar sslmode=require (sin comillas)
    if "sslmode=" in dsn:
        dsn = re.sub(r"sslmode=[^&]+", "sslmode=require", dsn)
    else:
        join_char = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{join_char}sslmode=require"

    return dsn


def using_postgres() -> bool:
    return bool(DATABASE_URL_RAW)


def get_pg_conn():
    dsn = clean_database_url(DATABASE_URL_RAW)
    if not dsn:
        raise RuntimeError("DATABASE_URL no está configurada.")
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
        return row  # dict_row
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

    ph = sql_placeholder(engine)
    cur.execute(f"SELECT 1 FROM usuarios WHERE usuario={ph}", (ADMIN_USER,))
    exists = cur.fetchone()

    if exists is None:
        cur.execute(
            f"INSERT INTO usuarios (usuario, nombre, password) VALUES ({ph},{ph},{ph})",
            (ADMIN_USER, "Administrador", ADMIN_PASSWORD)
        )

    conn.commit()
    cur.close()
    conn.close()


# Inicializa DB al arrancar
try:
    init_db()
except Exception as e:
    print("init_db() error:", e)
    # Importante: NO rompemos el arranque para que el servicio viva y puedas ver logs.


# =========================
# LOGIN REQUIRED
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
    return render_template("formulario.html", title="Nueva solicitud", active="form")


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    # OJO: estos names deben coincidir con el HTML
    zona = request.form.get("zona")
    dueno = request.form.get("dueno")
    tel = request.form.get("tel")
    mascota = request.form.get("mascota")
    muestra = request.form.get("muestra")
    direccion = request.form.get("direccion")

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

    return render_template("confirmacion.html", title="Solicitud enviada", active="form")


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
        user = cur.fetchone()
        cur.close()
        conn.close()

        user = fetchone_dict(user, engine)

        if user:
            session["logged_in"] = True
            session["usuario"] = user["usuario"]
            return redirect(url_for("ver_solicitudes"))
        else:
            error = "Usuario o clave incorrecta"

    return render_template("login.html", error=error, title="Login", active="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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
    solicitudes = cur.fetchall()

    cur.close()
    conn.close()

    solicitudes = fetchall_list(solicitudes, engine)

    return render_template(
        "solicitudes.html",
        solicitudes=solicitudes,
        title="Solicitudes",
        active="solicitudes"
    )


# =========================
# START LOCAL
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
