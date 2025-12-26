import os
import sqlite3
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)

# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render (Postgres)
SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")  # Local

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "1")  # "1" para asegurar admin


# =========================
# DB HELPERS (Postgres o SQLite)
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def get_pg_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
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
    cols = [r[1] for r in cur.fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype};")


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

            -- legacy para no romper
            zona TEXT,
            dueno TEXT,
            tel TEXT,
            mascota TEXT,
            muestra TEXT,
            direccion TEXT,
            fecha DATE NULL,
            horario TEXT,

            -- nuevo
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
            creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # asegurar columnas nuevas si ya existía
        for col in [
            ("dueno_nombre", "TEXT"),
            ("dueno_telefono", "TEXT"),
            ("vivienda_tipo", "TEXT"),
            ("torre", "TEXT"),
            ("apto", "TEXT"),
            ("direccion_detalle", "TEXT"),
            ("horario_turno", "TEXT"),
            ("horario_rango", "TEXT"),
            ("mascota_nombre", "TEXT"),
            ("mascota_especie", "TEXT"),
            ("mascota_otro", "TEXT"),
            ("mascota_raza", "TEXT"),
            ("mascota_edad", "TEXT"),
            ("muestra_tipo", "TEXT"),
            ("muestra_otro", "TEXT"),
            ("muestra_condicion", "TEXT"),
        ]:
            pg_add_column_if_missing(cur, "solicitudes", col[0], col[1])

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

        for col in [
            ("dueno_nombre", "TEXT"),
            ("dueno_telefono", "TEXT"),
            ("vivienda_tipo", "TEXT"),
            ("torre", "TEXT"),
            ("apto", "TEXT"),
            ("direccion_detalle", "TEXT"),
            ("horario_turno", "TEXT"),
            ("horario_rango", "TEXT"),
            ("mascota_nombre", "TEXT"),
            ("mascota_especie", "TEXT"),
            ("mascota_otro", "TEXT"),
            ("mascota_raza", "TEXT"),
            ("mascota_edad", "TEXT"),
            ("muestra_tipo", "TEXT"),
            ("muestra_otro", "TEXT"),
            ("muestra_condicion", "TEXT"),
        ]:
            sqlite_add_column_if_missing(cur, "solicitudes", col[0], col[1])

    # seed admin
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
    dueno_nombre = (request.form.get("dueno_nombre") or "").strip()
    dueno_telefono = (request.form.get("dueno_telefono") or "").strip()

    vivienda_tipo = (request.form.get("vivienda_tipo") or "").strip()
    direccion = (request.form.get("direccion") or "").strip()
    torre = (request.form.get("torre") or "").strip()
    apto = (request.form.get("apto") or "").strip()
    direccion_detalle = (request.form.get("direccion_detalle") or "").strip()

    horario_turno = (request.form.get("horario_turno") or "").strip()
    horario_rango = (request.form.get("horario_rango") or "").strip()

    fecha_str = (request.form.get("fecha") or "").strip()
    fecha = fecha_str if fecha_str else None

    mascota_nombre = (request.form.get("mascota_nombre") or "").strip()
    mascota_especie = (request.form.get("mascota_especie") or "").strip()
    mascota_otro = (request.form.get("mascota_otro") or "").strip()
    mascota_raza = (request.form.get("mascota_raza") or "").strip()
    mascota_edad = (request.form.get("mascota_edad") or "").strip()

    muestra_tipo = (request.form.get("muestra_tipo") or "").strip()
    muestra_otro = (request.form.get("muestra_otro") or "").strip()
    muestra_condicion = (request.form.get("muestra_condicion") or "").strip()

    # legacy (para que viejas consultas no revienten)
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
          dueno, tel, mascota, muestra, direccion, fecha, horario,
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


@app.route("/solicitudes/borrar", methods=["POST"])
@login_required
def borrar_solicitudes():
    ids = request.form.getlist("ids")
    # filtrar ids válidos
    ids = [i for i in ids if str(i).isdigit()]

    if not ids:
        flash("No seleccionaste ninguna solicitud.", "warn")
        return redirect(url_for("ver_solicitudes"))

    conn, engine = get_db()
    cur = conn.cursor()

    if engine == "pg":
        cur.execute("DELETE FROM solicitudes WHERE id = ANY(%s)", (ids,))
    else:
        placeholders = ",".join(["?"] * len(ids))
        cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders})", ids)

    conn.commit()
    cur.close()
    conn.close()

    flash(f"Se borraron {len(ids)} solicitud(es).", "ok")
    return redirect(url_for("ver_solicitudes"))


# =========================
# START LOCAL
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
