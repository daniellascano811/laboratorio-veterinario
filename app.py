import os
import sqlite3
from functools import wraps
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

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
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# Render (Postgres)
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()

# Local (SQLite)
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")

# Admin (opcional por env vars)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "1").strip()  # "1" o "0"


# =========================
# DB HELPERS (Postgres o SQLite)
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def normalize_pg_url(raw_url: str) -> str:
    """
    Acepta un DATABASE_URL tipo:
      postgresql://user:pass@host:5432/dbname
    y garantiza:
      - sin espacios / saltos raros
      - sslmode=require como query param correcto
    """
    u = (raw_url or "").strip()

    # Si el usuario pegó con saltos de línea, los quitamos
    u = " ".join(u.split())

    # Si el usuario pegó algo tipo: ".../db sslmode=require" (MAL),
    # lo arreglamos separando por espacio:
    if " sslmode=" in u and "?" not in u:
        # toma la parte antes del espacio, ignora lo demás
        u = u.split(" ")[0].strip()

    parsed = urlparse(u)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    # Forzamos sslmode=require bien
    query["sslmode"] = "require"

    new_parsed = parsed._replace(query=urlencode(query))
    return urlunparse(new_parsed)


def get_pg_conn():
    dsn = normalize_pg_url(DATABASE_URL)
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
            muestra_cual TEXT,
            direccion TEXT,
            fecha DATE NULL,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # migración segura si la columna no existía antes
        try:
            cur.execute("ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS muestra_cual TEXT;")
        except Exception:
            pass
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
            muestra_cual TEXT,
            direccion TEXT,
            fecha TEXT NULL,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

    ph = sql_placeholder(engine)

    # Admin sync
    if FORCE_ADMIN_SYNC == "1":
        cur.execute(f"SELECT * FROM usuarios WHERE usuario={ph}", (ADMIN_USER,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"INSERT INTO usuarios (usuario, nombre, password) VALUES ({ph},{ph},{ph})",
                (ADMIN_USER, "Administrador", ADMIN_PASSWORD)
            )
        else:
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
    zona = request.form.get("zona")
    dueno = request.form.get("dueno")
    tel = request.form.get("tel")
    mascota = request.form.get("mascota")
    muestra = request.form.get("muestra")
    muestra_cual = request.form.get("muestra_cual")
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
        (zona, dueno, tel, mascota, muestra, muestra_cual, direccion, fecha, horario)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        """,
        (zona, dueno, tel, mascota, muestra, muestra_cual, direccion, fecha, horario)
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

    return render_template("login.html", error=error, title="Login")


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

    return render_template("solicitudes.html", solicitudes=solicitudes, title="Solicitudes", active="solicitudes")


# =========================
# START LOCAL
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
