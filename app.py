import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, abort
)

import psycopg
from psycopg.rows import dict_row  # ✅ clave para que PG devuelva dicts


# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render Postgres URL
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")


# =========================
# AUTH
# =========================
def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# =========================
# DB HELPERS
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def get_sqlite_conn():
    db_path = os.path.join(os.path.dirname(__file__), "app_local.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_conn():
    # ✅ row_factory=dict_row hace que fetchall() retorne dicts (no tuplas)
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_db():
    """
    Retorna (conn, engine) donde engine es "pg" o "sqlite"
    """
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"


def sql_placeholder(engine: str) -> str:
    return "%s" if engine == "pg" else "?"


def init_db():
    conn, engine = get_db()
    cur = conn.cursor()
    try:
        if engine == "pg":
            cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
              id SERIAL PRIMARY KEY,

              -- Dueño
              dueno_nombre TEXT,
              tel TEXT,
              tipo_vivienda TEXT,
              direccion TEXT,
              torre TEXT,
              apto TEXT,
              porteria TEXT,
              turno TEXT,
              franja TEXT,
              fecha DATE,

              -- Mascota
              mascota_nombre TEXT,
              especie TEXT,
              especie_otro TEXT,
              raza TEXT,
              edad TEXT,

              -- Muestra
              muestra_tipo TEXT,
              muestra_otro TEXT,
              condicion_especial TEXT,

              estado TEXT DEFAULT 'pendiente',
              creado TIMESTAMP DEFAULT NOW()
            );
            """)
            conn.commit()

            cols = [
                ("dueno_nombre", "TEXT"),
                ("tel", "TEXT"),
                ("tipo_vivienda", "TEXT"),
                ("direccion", "TEXT"),
                ("torre", "TEXT"),
                ("apto", "TEXT"),
                ("porteria", "TEXT"),
                ("turno", "TEXT"),
                ("franja", "TEXT"),
                ("fecha", "DATE"),
                ("mascota_nombre", "TEXT"),
                ("especie", "TEXT"),
                ("especie_otro", "TEXT"),
                ("raza", "TEXT"),
                ("edad", "TEXT"),
                ("muestra_tipo", "TEXT"),
                ("muestra_otro", "TEXT"),
                ("condicion_especial", "TEXT"),
                ("estado", "TEXT"),
                ("creado", "TIMESTAMP"),
            ]

            for col, typ in cols:
                try:
                    cur.execute(f"ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS {col} {typ};")
                    conn.commit()
                except Exception:
                    conn.rollback()

        else:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,

              dueno_nombre TEXT,
              tel TEXT,
              tipo_vivienda TEXT,
              direccion TEXT,
              torre TEXT,
              apto TEXT,
              porteria TEXT,
              turno TEXT,
              franja TEXT,
              fecha TEXT,

              mascota_nombre TEXT,
              especie TEXT,
              especie_otro TEXT,
              raza TEXT,
              edad TEXT,

              muestra_tipo TEXT,
              muestra_otro TEXT,
              condicion_especial TEXT,

              estado TEXT DEFAULT 'pendiente',
              creado TEXT
            );
            """)
            conn.commit()

            cur.execute("PRAGMA table_info(solicitudes)")
            existing = {row[1] for row in cur.fetchall()}

            def add_col(name, typ):
                if name not in existing:
                    cur.execute(f"ALTER TABLE solicitudes ADD COLUMN {name} {typ}")
                    conn.commit()

            add_col("dueno_nombre", "TEXT")
            add_col("tel", "TEXT")
            add_col("tipo_vivienda", "TEXT")
            add_col("direccion", "TEXT")
            add_col("torre", "TEXT")
            add_col("apto", "TEXT")
            add_col("porteria", "TEXT")
            add_col("turno", "TEXT")
            add_col("franja", "TEXT")
            add_col("fecha", "TEXT")
            add_col("mascota_nombre", "TEXT")
            add_col("especie", "TEXT")
            add_col("especie_otro", "TEXT")
            add_col("raza", "TEXT")
            add_col("edad", "TEXT")
            add_col("muestra_tipo", "TEXT")
            add_col("muestra_otro", "TEXT")
            add_col("condicion_especial", "TEXT")
            add_col("estado", "TEXT")
            add_col("creado", "TEXT")

    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


# Init DB sin tumbar app
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
    return render_template("login.html", active="login")


@app.post("/login")
def login_post():
    usuario = (request.form.get("usuario") or "").strip()
    password = (request.form.get("password") or "").strip()

    if usuario == ADMIN_USER and password == ADMIN_PASSWORD:
        session["logged_in"] = True
        session["admin_user"] = usuario
        return redirect(url_for("ver_solicitudes"))

    return render_template("login.html", active="login", error="Usuario o contraseña incorrectos")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.post("/solicitud")
def crear_solicitud():
    dueno_nombre = (request.form.get("dueno_nombre") or "").strip()
    tel = (request.form.get("tel") or "").strip()
    tipo_vivienda = (request.form.get("tipo_vivienda") or "").strip()
    direccion = (request.form.get("direccion") or "").strip()
    torre = (request.form.get("torre") or "").strip()
    apto = (request.form.get("apto") or "").strip()
    porteria = (request.form.get("porteria") or "").strip()
    turno = (request.form.get("turno") or "").strip()
    franja = (request.form.get("franja") or "").strip()
    fecha_str = (request.form.get("fecha") or "").strip()

    mascota_nombre = (request.form.get("mascota_nombre") or "").strip()
    especie = (request.form.get("especie") or "").strip()
    especie_otro = (request.form.get("especie_otro") or "").strip()
    raza = (request.form.get("raza") or "").strip()
    edad = (request.form.get("edad") or "").strip()

    muestra_tipo = (request.form.get("muestra_tipo") or "").strip()
    muestra_otro = (request.form.get("muestra_otro") or "").strip()
    condicion_especial = (request.form.get("condicion_especial") or "").strip()

    if not dueno_nombre or not tel or not tipo_vivienda or not direccion or not turno or not franja:
        return render_template(
            "formulario.html",
            active="form",
            error="Completa los campos obligatorios del dueño (Nombre, Tel, Vivienda, Dirección, Turno y Franja)."
        )

    fecha_val = fecha_str if fecha_str else None
    creado = datetime.utcnow().isoformat()

    conn, engine = get_db()
    ph = sql_placeholder(engine)
    cur = conn.cursor()
    try:
        if engine == "pg":
            cur.execute(
                f"""
                INSERT INTO solicitudes
                (dueno_nombre, tel, tipo_vivienda, direccion, torre, apto, porteria, turno, franja, fecha,
                 mascota_nombre, especie, especie_otro, raza, edad,
                 muestra_tipo, muestra_otro, condicion_especial, estado)
                VALUES
                ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph})
                """,
                (
                    dueno_nombre, tel, tipo_vivienda, direccion, torre, apto, porteria, turno, franja, fecha_val,
                    mascota_nombre, especie, especie_otro, raza, edad,
                    muestra_tipo, muestra_otro, condicion_especial, "pendiente"
                )
            )
        else:
            cur.execute(
                f"""
                INSERT INTO solicitudes
                (dueno_nombre, tel, tipo_vivienda, direccion, torre, apto, porteria, turno, franja, fecha,
                 mascota_nombre, especie, especie_otro, raza, edad,
                 muestra_tipo, muestra_otro, condicion_especial, estado, creado)
                VALUES
                ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},{ph})
                """,
                (
                    dueno_nombre, tel, tipo_vivienda, direccion, torre, apto, porteria, turno, franja, fecha_val,
                    mascota_nombre, especie, especie_otro, raza, edad,
                    muestra_tipo, muestra_otro, condicion_especial, "pendiente", creado
                )
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("crear_solicitud() error:", e)
        return render_template("formulario.html", active="form", error="Error guardando la solicitud. Revisa logs.")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    return render_template("confirmacion.html", active="form")


@app.get("/solicitudes")
@require_login
def ver_solicitudes():
    conn, engine = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT *
            FROM solicitudes
            ORDER BY id DESC
            LIMIT 50
        """)
        rows = cur.fetchall()

        if engine == "pg":
            # ✅ ya vienen como dict gracias a dict_row
            solicitudes = rows
        else:
            solicitudes = [dict(r) for r in rows]

    except Exception as e:
        print("ver_solicitudes() error:", e)
        return abort(500)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    return render_template("solicitudes.html", solicitudes=solicitudes, active="solicitudes")


@app.post("/solicitudes/borrar")
@require_login
def borrar_solicitudes():
    ids = request.form.getlist("ids")
    ids = [i for i in ids if str(i).isdigit()]
    if not ids:
        return redirect(url_for("ver_solicitudes"))

    conn, engine = get_db()
    cur = conn.cursor()
    try:
        if engine == "pg":
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders})", tuple(ids))
        else:
            placeholders = ",".join(["?"] * len(ids))
            cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders})", ids)

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("borrar_solicitudes() error:", e)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    return redirect(url_for("ver_solicitudes"))


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
