import os
import sqlite3
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)

# =========================
# APP / CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render Postgres
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")  # Local


# =========================
# DB HELPERS
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def _pg_dsn_with_ssl(dsn: str) -> str:
    # Render suele aceptar sslmode=require.
    # Si ya viene en la URL, no lo duplicamos.
    if "sslmode=" in dsn:
        return dsn
    join_char = "&" if "?" in dsn else "?"
    return f"{dsn}{join_char}sslmode=require"


def get_pg_conn():
    dsn = _pg_dsn_with_ssl(DATABASE_URL)
    return psycopg.connect(dsn, row_factory=dict_row)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    # retorna (conn, engine)
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


def column_exists_pg(cur, table: str, column: str) -> bool:
    cur.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        LIMIT 1
    """, (table, column))
    return cur.fetchone() is not None


def column_exists_sqlite(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]  # (cid, name, type, notnull, dflt_value, pk)
    return column in cols


# =========================
# INIT DB (con migración)
# =========================
def init_db():
    conn, engine = get_db()
    cur = conn.cursor()
    ph = sql_placeholder(engine)

    if engine == "pg":
        # tablas
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

        # migración suave: si la tabla existía sin muestra_cual
        if not column_exists_pg(cur, "solicitudes", "muestra_cual"):
            cur.execute("ALTER TABLE solicitudes ADD COLUMN muestra_cual TEXT;")

    else:
        # SQLite
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

        # migración suave por si existía sin columna
        if not column_exists_sqlite(cur, "solicitudes", "muestra_cual"):
            cur.execute("ALTER TABLE solicitudes ADD COLUMN muestra_cual TEXT;")

    # crear admin (pero respetando env si lo pusiste)
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "1234")

    cur.execute(f"SELECT 1 FROM usuarios WHERE usuario={ph}", (admin_user,))
    exists = cur.fetchone()
    if exists is None:
        cur.execute(
            f"INSERT INTO usuarios (usuario, nombre, password) VALUES ({ph},{ph},{ph})",
            (admin_user, "Administrador", admin_pass)
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f"DB inicializada OK ({'Postgres' if engine=='pg' else 'SQLite'})")


# IMPORTANTE: inicializa al arrancar
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
    return render_template("formulario.html", active="form", title="Nueva solicitud")


def _get_form_value(*keys, default=""):
    """Lee el primer key que exista (para soportar nombres viejos/nuevos)."""
    for k in keys:
        v = request.form.get(k)
        if v is not None:
            return v.strip()
    return default


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    # Soportar nombres nuevos + viejos (por si el HTML quedó mixto)
    zona = _get_form_value("zona")
    dueno = _get_form_value("dueno", "dueno_nombre")
    tel = _get_form_value("tel", "dueno_telefono")
    mascota = _get_form_value("mascota", "mascota_nombre")
    muestra = _get_form_value("muestra", "muestra_tipo")
    muestra_cual = _get_form_value("muestra_cual", "muestra_detalle", "cual")

    direccion = _get_form_value("direccion")
    fecha_str = _get_form_value("fecha", default="")
    fecha = fecha_str if fecha_str else None
    horario = _get_form_value("horario", default="") or None

    conn, engine = get_db()
    cur = conn.cursor()
    ph = sql_placeholder(engine)

    # INSERT seguro (no depende del orden raro)
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

    return render_template("confirmacion.html", active="form", title="Solicitud enviada")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = _get_form_value("usuario")
        password = _get_form_value("password")

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

    return render_template("solicitudes.html", active="solicitudes", solicitudes=solicitudes, title="Solicitudes")


# =========================
# START LOCAL
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

