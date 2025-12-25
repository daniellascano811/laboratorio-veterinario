import os
import sqlite3
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Render
SQLITE_PATH = "app_local.db"                   # Local

def using_postgres():
    return bool(DATABASE_URL)

def get_pg_conn():
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg.connect(dsn, row_factory=dict_row)

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
    if using_postgres():
        return get_pg_conn(), "pg"
    return get_sqlite_conn(), "sqlite"

def ph(engine):
    return "%s" if engine == "pg" else "?"

def rows_to_list(rows, engine):
    if engine == "pg":
        return rows
    return [dict(r) for r in rows]

def init_db():
    conn, engine = get_db()
    cur = conn.cursor()

    if engine == "pg":
        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios(
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes(
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
        CREATE TABLE IF NOT EXISTS usuarios(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes(
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

    p = ph(engine)
    cur.execute(f"SELECT 1 FROM usuarios WHERE usuario={p}", ("admin",))
    if cur.fetchone() is None:
        cur.execute(
            f"INSERT INTO usuarios (usuario,password) VALUES ({p},{p})",
            ("admin", "1234"),
        )

    conn.commit()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print("init_db() error:", e)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/")
def home():
    return render_template("formulario.html", active="form")

@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    zona = request.form.get("zona")
    dueno = request.form.get("dueno")
    tel = request.form.get("tel")
    mascota = request.form.get("mascota")
    muestra = request.form.get("muestra")
    direccion = request.form.get("direccion")
    fecha = (request.form.get("fecha") or "").strip() or None
    horario = (request.form.get("horario") or "").strip() or None

    conn, engine = get_db()
    cur = conn.cursor()
    p = ph(engine)

    cur.execute(
        f"""
        INSERT INTO solicitudes
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario)
        VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
        """,
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario),
    )

    conn.commit()
    cur.close()
    conn.close()

    return render_template("confirmacion.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        password = (request.form.get("password") or "").strip()

        conn, engine = get_db()
        cur = conn.cursor()
        p = ph(engine)

        cur.execute(
            f"SELECT * FROM usuarios WHERE usuario={p} AND password={p}",
            (usuario, password),
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session["logged_in"] = True
            session["usuario"] = usuario
            return redirect(url_for("ver_solicitudes"))
        error = "Usuario o clave incorrecta"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/solicitudes")
@login_required
def ver_solicitudes():
    conn, engine = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM solicitudes ORDER BY creado DESC LIMIT 50")
    solicitudes = cur.fetchall()
    cur.close()
    conn.close()

    solicitudes = rows_to_list(solicitudes, engine)
    return render_template("solicitudes.html", solicitudes=solicitudes, active="solicitudes")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
