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
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render (Postgres)
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")  # Local

# Admin seed (opcional)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "1")  # "1" para asegurar admin


# =========================
# DB HELPERS (Postgres o SQLite)
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def normalize_dsn(dsn: str) -> str:
    """
    Render ya suele traer un DSN correcto. No inventamos sslmode aquí.
    Si tu DATABASE_URL ya trae ?sslmode=require, perfecto.
    """
    return dsn


def get_pg_conn():
    dsn = normalize_dsn(DATABASE_URL)
    return psycopg.connect(dsn, row_factory=dict_row)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    # Retorna (conn, "pg"|"sqlite")
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
    # Postgres usa %s, sqlite usa ?
    return "%s" if engine == "pg" else "?"


# =========================
# MIGRATIONS / INIT DB
# =========================
def pg_add_column_if_missing(cur, table: str, col: str, coltype: str):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, col)
    )
    exists = cur.fetchone()
    if not exists:
        cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {coltype};')


def sqlite_add_column_if_missing(cur, table: str, col: str, coltype: str):
    cur.execute(f"PRAGMA table_info({table});")
    cols = [r[1] for r in cur.fetchall()]  # (cid, name, type, notnull, dflt_value, pk)
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype};")


def init_db():
    conn, engine = get_db()
    cur = conn.cursor()

    # --- tablas base ---
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

            -- LEGACY (para no romper nada viejo)
            zona TEXT,
            dueno TEXT,
            tel TEXT,
            mascota TEXT,
            muestra TEXT,
            direccion TEXT,
            fecha DATE NULL,
            horario TEXT,

            -- NUEVO (estructura real)
            dueno_nombre TEXT,
            dueno_telefono TEXT,
            vivienda_tipo TEXT,      -- casa/apto
            torre TEXT,
            apto TEXT,
            direccion_detalle TEXT,  -- interior / instrucciones

            horario_turno TEXT,      -- mañana/tarde
            horario_rango TEXT,      -- 9-12 / 1-5 etc

            mascota_nombre TEXT,
            mascota_especie TEXT,    -- perro/gato/otro
            mascota_otro TEXT,
            mascota_raza TEXT,
            mascota_edad TEXT,

            muestra_tipo TEXT,       -- sangre/heces/orina/otro
            muestra_otro TEXT,
            muestra_condicion TEXT,  -- refrigerada/urgente/etc

            estado TEXT DEFAULT 'pendiente',
            creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Asegurar columnas nuevas si la tabla ya existía
        pg_add_column_if_missing(cur, "solicitudes", "dueno_nombre", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "dueno_telefono", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "vivienda_tipo", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "torre", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "apto", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "direccion_detalle", "TEXT")

        pg_add_column_if_missing(cur, "solicitudes", "horario_turno", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "horario_rango", "TEXT")

        pg_add_column_if_missing(cur, "solicitudes", "mascota_nombre", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "mascota_especie", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "mascota_otro", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "mascota_raza", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "mascota_edad", "TEXT")

        pg_add_column_if_missing(cur, "solicitudes", "muestra_tipo", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "muestra_otro", "TEXT")
        pg_add_column_if_missing(cur, "solicitudes", "muestra_condicion", "TEXT")

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
            direccion TEXT,
            fecha TEXT NULL,
            horario TEXT,

            dueno_nombre TEXT,
            dueno_telefono TEXT,
            vivienda_tipo TEXT,
            torre TEXT,
            apto TEXT,
            direccion_detalle TEXT,

            horario_turno TEXT,
            horario_rango TEXT,

            mascota_nombre TEXT,
            mascota_especie TEXT,
            mascota_otro TEXT,
            mascota_raza TEXT,
            mascota_edad TEXT,

            muestra_tipo TEXT,
            muestra_otro TEXT,
            muestra_condicion TEXT,

            estado TEXT DEFAULT 'pendiente',
            creado DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        sqlite_add_column_if_missing(cur, "solicitudes", "dueno_nombre", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "dueno_telefono", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "vivienda_tipo", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "torre", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "apto", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "direccion_detalle", "TEXT")

        sqlite_add_column_if_missing(cur, "solicitudes", "horario_turno", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "horario_rango", "TEXT")

        sqlite_add_column_if_missing(cur, "solicitudes", "mascota_nombre", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "mascota_especie", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "mascota_otro", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "mascota_raza", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "mascota_edad", "TEXT")

        sqlite_add_column_if_missing(cur, "solicitudes", "muestra_tipo", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "muestra_otro", "TEXT")
        sqlite_add_column_if_missing(cur, "solicitudes", "muestra_condicion", "TEXT")

    # --- seed admin ---
    ph = sql_placeholder(engine)
    cur.execute(f"SELECT 1 FROM usuarios WHERE usuario={ph}", (ADMIN_USER,))
    exists = cur.fetchone()

    if exists is None:
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


# Inicializa DB al arrancar
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
    return render_template("formulario.html", title="Nueva solicitud de muestra", active="form")


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    # ----- DUEÑO -----
    dueno_nombre = (request.form.get("dueno_nombre") or "").strip()
    dueno_telefono = (request.form.get("dueno_telefono") or "").strip()

    vivienda_tipo = (request.form.get("vivienda_tipo") or "").strip()  # casa/apto
    direccion = (request.form.get("direccion") or "").strip()
    torre = (request.form.get("torre") or "").strip()
    apto = (request.form.get("apto") or "").strip()
    direccion_detalle = (request.form.get("direccion_detalle") or "").strip()

    # horario
    horario_turno = (request.form.get("horario_turno") or "").strip()  # mañana/tarde
    horario_rango = (request.form.get("horario_rango") or "").strip()  # 9-12 / 1-5

    # fecha opcional
    fecha_str = (request.form.get("fecha") or "").strip()
    fecha = fecha_str if fecha_str else None

    # ----- MASCOTA -----
    mascota_nombre = (request.form.get("mascota_nombre") or "").strip()
    mascota_especie = (request.form.get("mascota_especie") or "").strip()  # perro/gato/otro
    mascota_otro = (request.form.get("mascota_otro") or "").strip()
    mascota_raza = (request.form.get("mascota_raza") or "").strip()
    mascota_edad = (request.form.get("mascota_edad") or "").strip()

    # ----- MUESTRA -----
    muestra_tipo = (request.form.get("muestra_tipo") or "").strip()  # sangre/heces/orina/otro
    muestra_otro = (request.form.get("muestra_otro") or "").strip()
    muestra_condicion = (request.form.get("muestra_condicion") or "").strip()

    # Guardamos también una versión "legacy" por si tu tabla vieja tenía datos:
    # dueno/tel/mascota/muestra/horario ya existían.
    dueno_legacy = dueno_nombre
    tel_legacy = dueno_telefono
    mascota_legacy = mascota_nombre
    muestra_legacy = muestra_tipo if muestra_tipo != "otro" else (muestra_otro or "otro")
    horario_legacy = f"{horario_turno} ({horario_rango})".strip()

    conn, engine = get_db()
    cur = conn.cursor()
    ph = sql_placeholder(engine)

    cur.execute(
        f"""
        INSERT INTO solicitudes
        (
          -- legacy
          dueno, tel, mascota, muestra, direccion, fecha, horario,

          -- nuevo
          dueno_nombre, dueno_telefono, vivienda_tipo, torre, apto, direccion_detalle,
          horario_turno, horario_rango,
          mascota_nombre, mascota_especie, mascota_otro, mascota_raza, mascota_edad,
          muestra_tipo, muestra_otro, muestra_condicion
        )
        VALUES
        (
          {ph},{ph},{ph},{ph},{ph},{ph},{ph},
          {ph},{ph},{ph},{ph},{ph},{ph},
          {ph},{ph},
          {ph},{ph},{ph},{ph},{ph},
          {ph},{ph},{ph}
        )
        """,
        (
            dueno_legacy, tel_legacy, mascota_legacy, muestra_legacy, direccion, fecha, horario_legacy,
            dueno_nombre, dueno_telefono, vivienda_tipo, torre, apto, direccion_detalle,
            horario_turno, horario_rango,
            mascota_nombre, mascota_especie, mascota_otro, mascota_raza, mascota_edad,
            muestra_tipo, muestra_otro, muestra_condicion
        )
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

    # Traemos las últimas 50 con los campos nuevos
    cur.execute("""
        SELECT
          id,
          dueno_nombre, dueno_telefono, vivienda_tipo, direccion, torre, apto, direccion_detalle,
          horario_turno, horario_rango, fecha,
          mascota_nombre, mascota_especie, mascota_otro, mascota_raza, mascota_edad,
          muestra_tipo, muestra_otro, muestra_condicion,
          estado, creado
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
    # Local ok con 127.0.0.1, Render usa gunicorn (no entra aquí)
    app.run(host="127.0.0.1", port=port, debug=True)
