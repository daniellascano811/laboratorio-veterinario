import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)

# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render Postgres (Internal URL recomendado)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "0")  # "1" para forzar update del admin en arranque

SQLITE_PATH = os.environ.get("SQLITE_PATH", "app_local.db")


# =========================
# DB HELPERS (Postgres o SQLite)
# =========================
def using_postgres() -> bool:
    return bool(DATABASE_URL)


def get_pg_conn():
    # NO forzar sslmode aquí: Render lo maneja por la URL
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """
    Retorna (conn, engine) donde engine es "pg" o "sqlite"
    """
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"


def sql_placeholder(engine: str) -> str:
    return "%s" if engine == "pg" else "?"


def dictify_rows(engine: str, rows):
    if engine == "pg":
        return rows  # ya son dict por RealDictCursor
    # sqlite Row -> dict
    return [dict(r) for r in rows]


# =========================
# MIGRACIONES SUAVES
# =========================
def _pg_column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def _sqlite_column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols


def init_db():
    """
    - Crea tablas si no existen
    - Agrega columnas faltantes (sin romper)
    - FIX: usuarios.nombre NULL -> lo rellena
    - Garantiza que admin exista con nombre NO NULL
    """
    conn, engine = get_db()
    ph = sql_placeholder(engine)

    try:
        cur = conn.cursor()

        if engine == "pg":
            # ---- Tabla usuarios
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    usuario TEXT UNIQUE NOT NULL,
                    nombre  TEXT NOT NULL,
                    password TEXT NOT NULL
                )
                """
            )

            # ---- Tabla solicitudes
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS solicitudes (
                    id SERIAL PRIMARY KEY,

                    -- dueño
                    dueno TEXT,
                    tel TEXT,
                    zona TEXT,
                    vivienda TEXT,
                    direccion TEXT,
                    instrucciones TEXT,
                    turno TEXT,
                    fecha DATE,

                    -- mascota
                    mascota TEXT,
                    especie TEXT,
                    raza TEXT,
                    edad TEXT,

                    -- muestra
                    muestra TEXT,
                    muestra_cual TEXT,
                    condicion TEXT,

                    -- control
                    estado TEXT DEFAULT 'pendiente',
                    creado TIMESTAMP DEFAULT NOW()
                )
                """
            )

            # --- Migraciones por si tu tabla viene de antes con menos columnas:
            # (Solo agrega si faltan)
            needed_cols = [
                ("solicitudes", "vivienda", "TEXT"),
                ("solicitudes", "instrucciones", "TEXT"),
                ("solicitudes", "turno", "TEXT"),
                ("solicitudes", "especie", "TEXT"),
                ("solicitudes", "raza", "TEXT"),
                ("solicitudes", "edad", "TEXT"),
                ("solicitudes", "muestra_cual", "TEXT"),
                ("solicitudes", "condicion", "TEXT"),
                ("solicitudes", "creado", "TIMESTAMP DEFAULT NOW()"),
            ]
            for table, col, ddl in needed_cols:
                if not _pg_column_exists(cur, table, col):
                    cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {ddl}')

            # =========================
            # FIX DURO: usuarios.nombre NULL
            # =========================
            cur.execute("UPDATE usuarios SET nombre = usuario WHERE nombre IS NULL OR nombre = ''")

            # =========================
            # Asegurar admin sin NULL
            # =========================
            # Si existe, opcionalmente lo sincroniza si FORCE_ADMIN_SYNC=1
            if FORCE_ADMIN_SYNC == "1":
                cur.execute(
                    """
                    INSERT INTO usuarios (usuario, nombre, password)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (usuario)
                    DO UPDATE SET nombre = EXCLUDED.nombre, password = EXCLUDED.password
                    """,
                    (ADMIN_USER, ADMIN_USER, ADMIN_PASSWORD),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO usuarios (usuario, nombre, password)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (usuario) DO NOTHING
                    """,
                    (ADMIN_USER, ADMIN_USER, ADMIN_PASSWORD),
                )

        else:
            # SQLITE
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    nombre  TEXT NOT NULL,
                    password TEXT NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS solicitudes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dueno TEXT,
                    tel TEXT,
                    zona TEXT,
                    vivienda TEXT,
                    direccion TEXT,
                    instrucciones TEXT,
                    turno TEXT,
                    fecha TEXT,

                    mascota TEXT,
                    especie TEXT,
                    raza TEXT,
                    edad TEXT,

                    muestra TEXT,
                    muestra_cual TEXT,
                    condicion TEXT,

                    estado TEXT DEFAULT 'pendiente',
                    creado TEXT
                )
                """
            )

            # Migraciones SQLite
            needed_cols = [
                ("solicitudes", "vivienda", "TEXT"),
                ("solicitudes", "instrucciones", "TEXT"),
                ("solicitudes", "turno", "TEXT"),
                ("solicitudes", "especie", "TEXT"),
                ("solicitudes", "raza", "TEXT"),
                ("solicitudes", "edad", "TEXT"),
                ("solicitudes", "muestra_cual", "TEXT"),
                ("solicitudes", "condicion", "TEXT"),
                ("solicitudes", "creado", "TEXT"),
            ]
            for table, col, ddl in needed_cols:
                if not _sqlite_column_exists(cur, table, col):
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

            # FIX: usuarios.nombre NULL (por si tu DB vieja lo tenía)
            cur.execute("UPDATE usuarios SET nombre = usuario WHERE nombre IS NULL OR nombre = ''")

            # admin
            if FORCE_ADMIN_SYNC == "1":
                # upsert manual (sqlite)
                cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (ADMIN_USER,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE usuarios SET nombre = ?, password = ? WHERE usuario = ?",
                        (ADMIN_USER, ADMIN_PASSWORD, ADMIN_USER),
                    )
                else:
                    cur.execute(
                        "INSERT INTO usuarios (usuario, nombre, password) VALUES (?, ?, ?)",
                        (ADMIN_USER, ADMIN_USER, ADMIN_PASSWORD),
                    )
            else:
                cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (ADMIN_USER,))
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        "INSERT INTO usuarios (usuario, nombre, password) VALUES (?, ?, ?)",
                        (ADMIN_USER, ADMIN_USER, ADMIN_PASSWORD),
                    )

        conn.commit()

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("init_db() error:", e)
        raise
    finally:
        conn.close()


# =========================
# AUTH
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# =========================
# ROUTES
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    init_db()  # asegura tablas y admin

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        password = (request.form.get("password") or "").strip()

        conn, engine = get_db()
        try:
            cur = conn.cursor()
            ph = sql_placeholder(engine)
            cur.execute(
                f"SELECT usuario, nombre, password FROM usuarios WHERE usuario = {ph}",
                (usuario,),
            )
            row = cur.fetchone()

            if not row:
                flash("Usuario no existe", "error")
                return redirect(url_for("login"))

            if engine == "sqlite":
                row = dict(row)

            if row["password"] != password:
                flash("Clave incorrecta", "error")
                return redirect(url_for("login"))

            session["user"] = row["usuario"]
            session["nombre"] = row["nombre"]
            return redirect(url_for("home"))

        finally:
            conn.close()

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    # FORMULARIO sin login (como querías)
    # Si quieres obligar login, cámbialo a @login_required
    return render_template("formulario.html", active="form")


@app.route("/crear-solicitud", methods=["POST"])
def crear_solicitud():
    """
    Inserta una solicitud con los campos nuevos.
    Si faltan campos en el form, no rompe: pone "".
    """
    # dueño
    dueno = (request.form.get("dueno") or "").strip()
    tel = (request.form.get("tel") or "").strip()
    zona = (request.form.get("zona") or "").strip()
    vivienda = (request.form.get("vivienda") or "").strip()  # casa/apto
    direccion = (request.form.get("direccion") or "").strip()
    instrucciones = (request.form.get("instrucciones") or "").strip()
    turno = (request.form.get("turno") or "").strip()  # mañana/tarde
    fecha = (request.form.get("fecha") or "").strip()

    # mascota
    mascota = (request.form.get("mascota") or "").strip()
    especie = (request.form.get("especie") or "").strip()
    raza = (request.form.get("raza") or "").strip()
    edad = (request.form.get("edad") or "").strip()

    # muestra
    muestra = (request.form.get("muestra") or "").strip()
    muestra_cual = (request.form.get("muestra_cual") or "").strip()
    condicion = (request.form.get("condicion") or "").strip()

    # validación mínima
    if not dueno or not tel or not direccion or not turno or not fecha or not mascota or not muestra:
        flash("Faltan campos obligatorios.", "error")
        return redirect(url_for("home"))

    conn, engine = get_db()
    ph = sql_placeholder(engine)
    try:
        cur = conn.cursor()

        if engine == "pg":
            cur.execute(
                f"""
                INSERT INTO solicitudes
                (dueno, tel, zona, vivienda, direccion, instrucciones, turno, fecha,
                 mascota, especie, raza, edad,
                 muestra, muestra_cual, condicion, estado)
                VALUES
                ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph})
                """,
                (
                    dueno, tel, zona, vivienda, direccion, instrucciones, turno, fecha,
                    mascota, especie, raza, edad,
                    muestra, muestra_cual, condicion, "pendiente"
                ),
            )
        else:
            creado = datetime.utcnow().isoformat()
            cur.execute(
                f"""
                INSERT INTO solicitudes
                (dueno, tel, zona, vivienda, direccion, instrucciones, turno, fecha,
                 mascota, especie, raza, edad,
                 muestra, muestra_cual, condicion, estado, creado)
                VALUES
                ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},{ph})
                """,
                (
                    dueno, tel, zona, vivienda, direccion, instrucciones, turno, fecha,
                    mascota, especie, raza, edad,
                    muestra, muestra_cual, condicion, "pendiente", creado
                ),
            )

        conn.commit()
        return render_template("confirmacion.html", dueno=dueno)

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("crear_solicitud() error:", e)
        # si hay error, vuelve al form y muestra algo
        flash("Error guardando la solicitud. Revisa logs.", "error")
        return redirect(url_for("home"))
    finally:
        conn.close()


@app.route("/solicitudes")
@login_required
def ver_solicitudes():
    conn, engine = get_db()
    ph = sql_placeholder(engine)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50"
        )
        rows = cur.fetchall()
        solicitudes = dictify_rows(engine, rows)
        return render_template("solicitudes.html", solicitudes=solicitudes, active="solicitudes")
    except Exception as e:
        print("ver_solicitudes() error:", e)
        raise
    finally:
        conn.close()


@app.route("/borrar-solicitudes", methods=["POST"])
@login_required
def borrar_solicitudes():
    ids = request.form.getlist("ids")  # checkboxes name="ids"
    ids = [i for i in ids if str(i).isdigit()]
    if not ids:
        return redirect(url_for("ver_solicitudes"))

    conn, engine = get_db()
    try:
        cur = conn.cursor()
        if engine == "pg":
            cur.execute("DELETE FROM solicitudes WHERE id = ANY(%s)", (ids,))
        else:
            placeholders = ",".join(["?"] * len(ids))
            cur.execute(f"DELETE FROM solicitudes WHERE id IN ({placeholders})", ids)

        conn.commit()
        return redirect(url_for("ver_solicitudes"))
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("borrar_solicitudes() error:", e)
        raise
    finally:
        conn.close()


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
