import os
from flask import Flask, render_template, request, redirect, url_for, session, abort
import psycopg
from psycopg.rows import dict_row
from functools import wraps
from datetime import datetime

# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
FORCE_ADMIN_SYNC = os.environ.get("FORCE_ADMIN_SYNC", "0") == "1"

# =========================
# DB
# =========================
def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

            # tabla usuarios
            cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                password TEXT NOT NULL
            )
            """)

            # tabla solicitudes
            cur.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
                id SERIAL PRIMARY KEY,
                dueno TEXT,
                telefono TEXT,
                vivienda TEXT,
                direccion TEXT,
                horario TEXT,
                fecha DATE,
                mascota TEXT,
                especie TEXT,
                raza TEXT,
                edad TEXT,
                muestra TEXT,
                muestra_cual TEXT,
                condicion TEXT,
                estado TEXT DEFAULT 'pendiente',
                creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # crear admin si no existe
            cur.execute("SELECT id FROM usuarios WHERE username=%s", (ADMIN_USER,))
            admin = cur.fetchone()

            if not admin:
                cur.execute("""
                    INSERT INTO usuarios (username, nombre, password)
                    VALUES (%s, %s, %s)
                """, (ADMIN_USER, "Administrador", ADMIN_PASSWORD))

            elif FORCE_ADMIN_SYNC:
                cur.execute("""
                    UPDATE usuarios
                    SET password=%s
                    WHERE username=%s
                """, (ADMIN_PASSWORD, ADMIN_USER))

            conn.commit()

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
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username")
        pwd = request.form.get("password")

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM usuarios
                    WHERE username=%s AND password=%s
                """, (user, pwd))
                u = cur.fetchone()

        if u:
            session["user"] = u["username"]
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="Credenciales incorrectas")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/home")
@login_required
def home():
    return render_template("home.html", active="form")

@app.route("/crear-solicitud", methods=["POST"])
@login_required
def crear_solicitud():
    data = request.form

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO solicitudes (
                    dueno, telefono, vivienda, direccion,
                    horario, fecha,
                    mascota, especie, raza, edad,
                    muestra, muestra_cual, condicion
                ) VALUES (
                    %s,%s,%s,%s,
                    %s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s
                )
            """, (
                data.get("dueno"),
                data.get("telefono"),
                data.get("vivienda"),
                data.get("direccion"),
                data.get("horario"),
                data.get("fecha"),
                data.get("mascota"),
                data.get("especie"),
                data.get("raza"),
                data.get("edad"),
                data.get("muestra"),
                data.get("muestra_cual"),
                data.get("condicion"),
            ))
            conn.commit()

    return redirect(url_for("ver_solicitudes"))

@app.route("/solicitudes")
@login_required
def ver_solicitudes():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM solicitudes
                ORDER BY creado DESC
                LIMIT 50
            """)
            solicitudes = cur.fetchall()

    return render_template(
        "solicitudes.html",
        solicitudes=solicitudes,
        active="solicitudes"
    )

@app.route("/borrar", methods=["POST"])
@login_required
def borrar():
    ids = request.form.getlist("ids")
    if not ids:
        return redirect(url_for("ver_solicitudes"))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM solicitudes WHERE id = ANY(%s)",
                (ids,)
            )
            conn.commit()

    return redirect(url_for("ver_solicitudes"))

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
