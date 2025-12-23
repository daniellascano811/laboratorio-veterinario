import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "cambia-esto-por-una-clave-larga"  # para sesiones (login/logout)

DB_NAME = "laboratorio.db"

# ====== CONFIG LOGIN (BÁSICO PARA PRACTICAR) ======
# Cambia estas credenciales cuando quieras
ADMIN_USER = "admin"
ADMIN_PASS = "1234"


# ====== DB HELPERS ======
def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zona TEXT,
            dueno_nombre TEXT,
            dueno_telefono TEXT,
            dueno_email TEXT,
            mascota_nombre TEXT,
            mascota_tipo TEXT,
            mascota_edad INTEGER,
            mascota_raza TEXT,
            muestra_tipo TEXT,
            direccion TEXT,
            fecha TEXT,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado TEXT
        )
    """)
    conn.commit()
    conn.close()


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


# ====== ROUTES ======
@app.route("/")
def home():
    return render_template("formulario.html")


@app.route("/solicitud", methods=["POST"])
def solicitud():
    datos = request.form.to_dict()

    # Normalizar horario: viene como "Mañana (8:00 - 12:00)" etc.
    horario = datos.get("horario", "").strip()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO solicitudes (
            zona, dueno_nombre, dueno_telefono, dueno_email,
            mascota_nombre, mascota_tipo, mascota_edad, mascota_raza,
            muestra_tipo, direccion, fecha, horario, estado, creado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos.get("zona"),
        datos.get("dueno_nombre"),
        datos.get("dueno_telefono"),
        datos.get("dueno_email"),
        datos.get("mascota_nombre"),
        datos.get("mascota_tipo"),
        datos.get("mascota_edad") or None,
        datos.get("mascota_raza"),
        datos.get("muestra_tipo"),
        datos.get("direccion"),
        datos.get("fecha"),
        horario,
        "pendiente",
        datetime.now().isoformat(timespec="seconds")
    ))
    conn.commit()
    conn.close()

    return render_template("confirmacion.html")


@app.route("/solicitudes")
@login_required
def solicitudes():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, zona, dueno_nombre AS dueno, dueno_telefono AS tel,
               mascota_nombre AS mascota, muestra_tipo AS muestra,
               direccion, fecha, horario, estado, creado
        FROM solicitudes
        ORDER BY id DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("solicitudes.html", solicitudes=rows)


# ====== LOGIN / LOGOUT ======
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("usuario", "")
        p = request.form.get("password", "")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("solicitudes"))
        else:
            error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
