import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, abort
)

# Psycopg (Postgres)
# Requiere: psycopg[binary] en requirements.txt
import psycopg

# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render Postgres URL
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")

# Si quieres forzar admin setup (opcional)
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "0")  # "1" para forzar


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
    # DB local (archivo)
    db_path = os.path.join(os.path.dirname(__file__), "app_local.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_conn():
    # En Render normalmente funciona directo con DATABASE_URL
    # Si tu URL incluye ?sslmode=require, psycopg lo puede parsear,
    # pero si te sale error de "invalid sslmode value", tu URL está mal pegada.
    return psycopg.connect(DATABASE_URL, autocommit=False)


def get_db():
    """
    Retorna (conn, engine) donde engine es "pg" o "sqlite"
    """
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"


def sql_placeholder(engine: str) -> str:
    """
    psycopg usa %s
    sqlite usa ?
    """
    return "%s" if engine == "pg" else "?"


def fetchall_list(rows, engine: str):
    """
    Convierte rows a lista de dict
    """
    out = []
    for r in rows:
        if engine == "pg":
            out.append(dict(r))
        else:
            out.append(dict(r))
    return out


def init_db():
    """
    Crea tablas si no existen y agrega columnas nuevas si faltan.
    Compatible con PG y SQLite.
    """
    conn, engine = get_db()
    cur = conn.cursor()
    try:
        if engine == "pg":
            # Tabla principal
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

            # En PG es más fácil asegurar columnas con ALTER IF NOT EXISTS (según versión)
            # Pero para evitar líos, intentamos y si falla ignoramos.
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
            # SQLite
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

            # Asegurar columnas nuevas (SQLite no tiene IF NOT EXISTS en ALTER COLUMN)
            cur.execute("PRAGMA table_info(solicitudes)")
            existing = {row[1] for row in cur.fetchall()}  # name is index 1

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


# Inicializa DB al arrancar (sin tumbar app si falla)
try:
    init_db()
except Exception as e:
    print("init_db() error:", e)


# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    # Página pública: formulario (sin login)
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
    # Dueño
    dueno_nombre = (request.form.get("dueno_nombre") or "").strip()
    tel = (request.form.get("tel") or "").strip()
    tipo_vivienda = (request.form.get("tipo_vivienda") or "").strip()  # casa/apartamento
    direccion = (request.form.get("direccion") or "").strip()
    torre = (request.form.get("torre") or "").strip()
    apto = (request.form.get("apto") or "").strip()
    porteria = (request.form.get("porteria") or "").strip()
    turno = (request.form.get("turno") or "").strip()  # mañana / tarde
    franja = (request.form.get("franja") or "").strip()  # 9-12 / 1-5
    fecha_str = (request.form.get("fecha") or "").strip()

    # Mascota
    mascota_nombre = (request.form.get("mascota_nombre") or "").strip()
    especie = (request.form.get("especie") or "").strip()  # perro / gato / otro
    especie_otro = (request.form.get("especie_otro") or "").strip()
    raza = (request.form.get("raza") or "").strip()
    edad = (request.form.get("edad") or "").strip()

    # Muestra
    muestra_tipo = (request.form.get("muestra_tipo") or "").strip()  # sangre/orina/heces/otro
    muestra_otro = (request.form.get("muestra_otro") or "").strip()
    condicion_especial = (request.form.get("condicion_especial") or "").strip()

    # Validaciones mínimas
    if not dueno_nombre or not tel or not tipo_vivienda or not direccion or not turno or not franja:
        return render_template(
            "formulario.html",
            active="form",
            error="Completa los campos obligatorios del dueño (Nombre, Tel, Vivienda, Dirección, Turno y Franja)."
        )

    # Fecha: guardamos como DATE en PG o texto en sqlite
    fecha_val = None
    if fecha_str:
        try:
            # Si viene YYYY-MM-DD
            fecha_val = fecha_str
        except Exception:
            fecha_val = None

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
        if engine == "pg":
            cur.execute("""
                SELECT *
                FROM solicitudes
                ORDER BY id DESC
                LIMIT 50
            """)
            rows = cur.fetchall()
            solicitudes = fetchall_list(rows, engine)
        else:
            cur.execute("""
                SELECT *
                FROM solicitudes
                ORDER BY id DESC
                LIMIT 50
            """)
            solicitudes = [dict(r) for r in cur.fetchall()]
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
            ph = "%s"
            placeholders = ",".join([ph] * len(ids))
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
