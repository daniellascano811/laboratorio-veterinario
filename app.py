import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-cambia-esto")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "laboratorio.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zona TEXT NOT NULL,
            dueno_nombre TEXT NOT NULL,
            dueno_telefono TEXT NOT NULL,
            dueno_email TEXT,
            mascota_nombre TEXT NOT NULL,
            mascota_tipo TEXT NOT NULL,
            mascota_edad INTEGER,
            mascota_raza TEXT,
            muestra_tipo TEXT NOT NULL,
            direccion TEXT NOT NULL,
            fecha TEXT,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS veterinarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'vet',
            creado TEXT NOT NULL
        )
    """)

    # ✅ Admin por defecto: admin / 1234
    cur.execute("SELECT COUNT(*) as c FROM veterinarios WHERE rol='admin'")
    c = cur.fetchone()["c"]
    if c == 0:
        cur.execute("""
            INSERT INTO veterinarios (usuario, nombre, password_hash, rol, creado)
            VALUES (?, ?, ?, 'admin', ?)
        """, (
            "admin",
            "Administrador",
            generate_password_hash("1234"),
            datetime.now().isoformat(timespec="seconds")
        ))

    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if session.get("rol") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def home():
    return render_template("formulario.html", title="Nueva solicitud")


@app.route("/solicitud", methods=["POST"])
def solicitud():
    f = request.form

    dueno_nombre = (f.get("dueno_nombre") or "").strip()
    dueno_telefono = (f.get("dueno_telefono") or "").strip()
    dueno_email = (f.get("dueno_email") or "").strip()

    mascota_nombre = (f.get("mascota_nombre") or "").strip()
    mascota_tipo = (f.get("mascota_tipo") or "").strip()
    mascota_edad = f.get("mascota_edad")
    mascota_raza = (f.get("mascota_raza") or "").strip()

    muestra_tipo = (f.get("muestra_tipo") or "").strip()
    direccion = (f.get("direccion") or "").strip()
    zona = (f.get("zona") or "").strip()
    fecha = (f.get("fecha") or "").strip()
    horario = (f.get("horario") or "").strip()

    # Validación mínima
    if not all([dueno_nombre, dueno_telefono, mascota_nombre, mascota_tipo, muestra_tipo, direccion, zona]):
        return render_template("confirmacion.html", ok=False, mensaje="Faltan datos obligatorios.", title="Error")

    # Edad opcional
    try:
        mascota_edad_int = int(mascota_edad) if mascota_edad not in (None, "") else None
    except:
        mascota_edad_int = None

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO solicitudes (
            zona, dueno_nombre, dueno_telefono, dueno_email,
            mascota_nombre, mascota_tipo, mascota_edad, mascota_raza,
            muestra_tipo, direccion, fecha, horario, estado, creado
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        zona, dueno_nombre, dueno_telefono, dueno_email or None,
        mascota_nombre, mascota_tipo, mascota_edad_int, mascota_raza or None,
        muestra_tipo, direccion, fecha or None, horario or None,
        "pendiente",
        datetime.now().isoformat(timespec="seconds")
    ))

    conn.commit()
    conn.close()

    return render_template("confirmacion.html", ok=True, mensaje="Solicitud recibida ✅ Guardada en SQLite.", title="Confirmación")


@app.route("/solicitudes")
@login_required
def solicitudes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50")
    rows = cur.fetchall()
    conn.close()
    return render_template("solicitudes.html", rows=rows, title="Solicitudes")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("solicitudes"))

    error = None

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        password = (request.form.get("password") or "").strip()  # ✅ coincide con tu HTML

        if not usuario or not password:
            error = "Completa usuario y contraseña."
            return render_template("login.html", error=error, title="Login")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM veterinarios WHERE usuario = ?", (usuario,))
        u = cur.fetchone()
        conn.close()

        if not u or not check_password_hash(u["password_hash"], password):
            error = "Usuario o contraseña incorrectos."
            return render_template("login.html", error=error, title="Login")

        session["logged_in"] = True
        session["usuario"] = u["usuario"]
        session["nombre"] = u["nombre"]
        session["rol"] = u["rol"]
        return redirect(url_for("solicitudes"))

    return render_template("login.html", error=error, title="Login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/crear-vet", methods=["GET", "POST"])
@admin_required
def crear_vet():
    error = None

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        nombre = (request.form.get("nombre") or "").strip()
        clave = (request.form.get("clave") or "").strip()

        if not usuario or not nombre or not clave:
            error = "Completa todos los campos."
            return render_template("crear_vet.html", error=error, title="Crear veterinario")

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO veterinarios(usuario, nombre, password_hash, rol, creado)
                VALUES (?,?,?,?,?)
            """, (
                usuario,
                nombre,
                generate_password_hash(clave),
                "vet",
                datetime.now().isoformat(timespec="seconds")
            ))
            conn.commit()
            conn.close()
            return redirect(url_for("solicitudes"))
        except sqlite3.IntegrityError:
            error = "Ese usuario ya existe."

    return render_template("crear_vet.html", error=error, title="Crear veterinario")


# ✅ Inicializa BD al arrancar
init_db()

if __name__ == "__main__":
    app.run(debug=True)
