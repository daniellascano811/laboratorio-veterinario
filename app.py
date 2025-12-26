import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, abort

# Psycopg 3 (Render/Postgres)
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "0").strip() == "1"

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "laboratorio.db")


# =========================
# HELPERS
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def get_sqlite_conn():
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_conn():
    if psycopg is None:
        raise RuntimeError("psycopg no está instalado. Revisa requirements.txt")
    # OJO: psycopg3 usa sslmode en URL o en parámetros
    # Si tu URL no trae ?sslmode=require igual Render suele funcionar por internal.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_db():
    """
    Retorna (conn, engine) donde engine = "pg" o "sqlite"
    """
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"


def sql_placeholder(engine: str) -> str:
    return "%s" if engine == "pg" else "?"


def fetchall_dicts(cur, engine: str):
    rows = cur.fetchall()
    if engine == "pg":
        # psycopg3 con dict_row ya devuelve dicts
        return rows
    # sqlite Row -> dict
    return [dict(r) for r in rows]


def fetchone_dict(cur, engine: str):
    row = cur.fetchone()
    if not row:
        return None
    if engine == "pg":
        return row
    return dict(row)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# =========================
# DB INIT / MIGRATION
# =========================
def init_db():
    conn, engine = get_db()
    ph = sql_placeholder(engine)

    try:
        cur = conn.cursor()

        # Tabla solicitudes (con columnas nuevas)
        if engine == "pg":
            cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
              id SERIAL PRIMARY KEY,
              dueno TEXT NOT NULL,
              tel TEXT NOT NULL,
              zona TEXT,
              vivienda TEXT,
              direccion TEXT,
              torre TEXT,
              apto TEXT,
              instrucciones TEXT,
              turno TEXT,
              franja TEXT,
              fecha DATE,
              mascota TEXT,
              especie TEXT,
              raza TEXT,
              edad TEXT,
              muestra TEXT,
              muestra_cual TEXT,
              condicion TEXT,
              estado TEXT DEFAULT 'pendiente',
              creado TIMESTAMP DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
              id SERIAL PRIMARY KEY,
              usuario TEXT UNIQUE NOT NULL,
              password TEXT NOT NULL
            );
            """)
        else:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              dueno TEXT NOT NULL,
              tel TEXT NOT NULL,
              zona TEXT,
              vivienda TEXT,
              direccion TEXT,
              torre TEXT,
              apto TEXT,
              instrucciones TEXT,
              turno TEXT,
              franja TEXT,
              fecha TEXT,
              mascota TEXT,
              especie TEXT,
              raza TEXT,
              edad TEXT,
              muestra TEXT,
              muestra_cual TEXT,
              condicion TEXT,
              estado TEXT DEFAULT 'pendiente',
              creado TEXT DEFAULT (datetime('now'))
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              usuario TEXT UNIQUE NOT NULL,
              password TEXT NOT NULL
            );
            """)

        # Crear/forzar admin si se pide
        if FORCE_ADMIN_SYNC:
            # upsert
            if engine == "pg":
                cur.execute(
                    "INSERT INTO usuarios (usuario, password) VALUES (%s, %s) "
                    "ON CONFLICT (usuario) DO UPDATE SET password = EXCLUDED.password;",
                    (ADMIN_USER, ADMIN_PASSWORD),
                )
            else:
                cur.execute("INSERT OR IGNORE INTO usuarios (usuario, password) VALUES (?, ?);", (ADMIN_USER, ADMIN_PASSWORD))
                cur.execute("UPDATE usuarios SET password=? WHERE usuario=?;", (ADMIN_PASSWORD, ADMIN_USER))

        conn.commit()

    finally:
        try:
            conn.close()
        except Exception:
            pass


# Inicializa DB al arrancar (Render y local)
try:
    init_db()
except Exception as e:
    print("init_db() error:", e)


# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    return render_template("formulario.html", active="form")


@app.get("/login")
def login():
    return render_template("login.html", active="")


@app.post("/login")
def login_post():
    usuario = (request.form.get("usuario") or "").strip()
    password = (request.form.get("password") or "").strip()

    conn, engine = get_db()
    try:
        cur = conn.cursor()
        ph = sql_placeholder(engine)
        cur.execute(f"SELECT * FROM usuarios WHERE usuario={ph} AND password={ph};", (usuario, password))
        user = fetchone_dict(cur, engine)
        if user:
            session["logged_in"] = True
            return redirect(url_for("ver_solicitudes"))
        return render_template("login.html", active="", error="Usuario o contraseña incorrectos.")
    finally:
        conn.close()


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.post("/crear-solicitud")
def crear_solicitud():
    # DUEÑO
    dueno = (request.form.get("dueno") or "").strip()
    tel = (request.form.get("tel") or "").strip()
    zona = (request.form.get("zona") or "").strip()

    vivienda = (request.form.get("vivienda") or "").strip()
    direccion = (request.form.get("direccion") or "").strip()
    torre = (request.form.get("torre") or "").strip()
    apto = (request.form.get("apto") or "").strip()
    instrucciones = (request.form.get("instrucciones") or "").strip()

    turno = (request.form.get("turno") or "").strip()          # mañana/tarde
    franja = (request.form.get("franja") or "").strip()        # 9-12 / 1-5

    fecha = (request.form.get("fecha") or "").strip()          # YYYY-MM-DD

    # MASCOTA
    mascota = (request.form.get("mascota") or "").strip()
    especie = (request.form.get("especie") or "").strip()
    raza = (request.form.get("raza") or "").strip()
    edad = (request.form.get("edad") or "").strip()

    muestra = (request.form.get("muestra") or "").strip()
    muestra_cual = (request.form.get("muestra_cual") or "").strip()
    condicion = (request.form.get("condicion") or "").strip()

    # Validaciones mínimas
    if not dueno or not tel:
        return "Faltan campos obligatorios (dueño y teléfono).", 400

    conn, engine = get_db()
    ph = sql_placeholder(engine)

    try:
        cur = conn.cursor()

        cur.execute(
            f"""
            INSERT INTO solicitudes
            (dueno, tel, zona, vivienda, direccion, torre, apto, instrucciones,
             turno, franja, fecha,
             mascota, especie, raza, edad,
             muestra, muestra_cual, condicion, estado)
            VALUES
            ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
             {ph},{ph},{ph},
             {ph},{ph},{ph},{ph},
             {ph},{ph},{ph},{ph});
            """,
            (
                dueno, tel, zona, vivienda, direccion, torre, apto, instrucciones,
                turno, franja, fecha if fecha else None,
                mascota, especie, raza, edad,
                muestra, muestra_cual, condicion, "pendiente",
            )
        )

        conn.commit()
        return redirect(url_for("home"))
    finally:
        conn.close()


@app.get("/solicitudes")
@login_required
def ver_solicitudes():
    conn, engine = get_db()
    ph = sql_placeholder(engine)
    try:
        cur = conn.cursor()
        # Ultimas 50
        if engine == "pg":
            cur.execute("SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50;")
        else:
            cur.execute("SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50;")

        solicitudes = fetchall_dicts(cur, engine)
        return render_template("solicitudes.html", solicitudes=solicitudes, active="solicitudes")
    finally:
        conn.close()


@app.post("/solicitudes/borrar")
@login_required
def borrar_solicitudes():
    ids = request.form.getlist("ids")
    if not ids:
        return redirect(url_for("ver_solicitudes"))

    # solo números
    ids = [i for i in ids if i.isdigit()]
    if not ids:
        return redirect(url_for("ver_solicitudes"))

    conn, engine = get_db()
    try:
        cur = conn.cursor()
        if engine == "pg":
            # IN con placeholders
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders});", ids)
        else:
            placeholders = ",".join(["?"] * len(ids))
            cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders});", ids)

        conn.commit()
        return redirect(url_for("ver_solicitudes"))
    finally:
        conn.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Render necesita 0.0.0.0
    app.run(host="0.0.0.0", port=port, debug=True)
