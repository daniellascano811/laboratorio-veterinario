import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)

# =========================
# CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")


# =========================
# DB CONNECTION
# =========================
def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


# =========================
# INIT DB (solo crea tablas si no existen)
# =========================
def init_db():
    conn = get_db()
    cur = conn.cursor()

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
        direccion TEXT,
        fecha DATE,
        horario TEXT,
        estado TEXT DEFAULT 'pendiente',
        creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Admin por defecto
    cur.execute("SELECT * FROM usuarios WHERE usuario='admin'")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO usuarios (usuario, nombre, password)
            VALUES ('admin', 'Administrador', '1234')
        """)

    conn.commit()
    cur.close()
    conn.close()


# =========================
# LOGIN REQUIRED
# =========================
def login_required(view):
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("formulario.html", title="Nueva solicitud")


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO solicitudes
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["zona"],
        request.form["dueno_nombre"],
        request.form["dueno_telefono"],
        request.form["mascota_nombre"],
        request.form["muestra_tipo"],
        request.form["direccion"],
        request.form["fecha"],
        request.form["horario"]
    ))

    conn.commit()
    cur.close()
    conn.close()

    return render_template("confirmacion.html", title="Solicitud enviada")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM usuarios WHERE usuario=%s AND password=%s",
            (usuario, password)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

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
    conn = get_db()
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

    return render_template(
        "solicitudes.html",
        solicitudes=solicitudes,
        title="Solicitudes"
    )


# =========================
# START
# =========================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
