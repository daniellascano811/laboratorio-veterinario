from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Cambia esto por una clave más larga cuando lo subas a producción
app.secret_key = "cambia_esta_clave_por_una_muy_larga_123456"

DB_NAME = "laboratorio.db"


# ---------------- DB HELPERS ----------------
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Tabla solicitudes
    c.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zona TEXT NOT NULL,
            dueno TEXT NOT NULL,
            tel TEXT NOT NULL,
            email TEXT,
            mascota TEXT NOT NULL,
            mascota_tipo TEXT,
            mascota_edad INTEGER,
            mascota_raza TEXT,
            muestra TEXT NOT NULL,
            direccion TEXT NOT NULL,
            fecha TEXT,
            horario TEXT,
            estado TEXT DEFAULT 'pendiente',
            creado TEXT NOT NULL
        )
    """)

    # Tabla usuarios
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            clave_hash TEXT NOT NULL,
            rol TEXT NOT NULL, -- admin / vet
            creado TEXT NOT NULL
        )
    """)

    conn.commit()

    # Crear admin por defecto si no existe
    c.execute("SELECT id FROM usuarios WHERE usuario = ?", ("admin",))
    existe_admin = c.fetchone()

    if not existe_admin:
        admin_pass = "1234"  # <-- CAMBIA ESTO apenas termines de probar
        c.execute("""
            INSERT INTO usuarios (usuario, nombre, clave_hash, rol, creado)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "admin",
            "Administrador",
            generate_password_hash(admin_pass),
            "admin",
            datetime.now().isoformat(timespec="seconds")
        ))
        conn.commit()

    conn.close()


# ---------------- AUTH DECORATORS ----------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if session.get("rol") != "admin":
            return "Acceso denegado (solo admin).", 403
        return f(*args, **kwargs)
    return wrapper


# ---------------- ROUTES PUBLIC ----------------
@app.route("/")
def home():
    # Formulario público: el cliente solicita recogida
    return render_template("formulario.html")


@app.route("/solicitud", methods=["POST"])
def solicitud():
    data = request.form

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO solicitudes (
            zona, dueno, tel, email, mascota, mascota_tipo, mascota_edad, mascota_raza,
            muestra, direccion, fecha, horario, estado, creado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("zona"),
        data.get("dueno_nombre"),
        data.get("dueno_telefono"),
        data.get("dueno_email"),
        data.get("mascota_nombre"),
        data.get("mascota_tipo"),
        data.get("mascota_edad") if data.get("mascota_edad") else None,
        data.get("mascota_raza"),
        data.get("muestra_tipo"),
        data.get("direccion"),
        data.get("fecha"),
        data.get("horario"),
        "pendiente",
        datetime.now().isoformat(timespec="seconds")
    ))

    conn.commit()
    conn.close()

    return render_template("confirmacion.html")


# ---------------- ROUTES LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # Si ya está logueado, lo mando a solicitudes
    if session.get("user_id"):
        return redirect(url_for("solicitudes"))

    error = None

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "").strip()

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,))
        user = c.fetchone()
        conn.close()

        if not user:
            error = "Usuario no existe."
        else:
            if check_password_hash(user["clave_hash"], clave):
                session["user_id"] = user["id"]
                session["usuario"] = user["usuario"]
                session["nombre"] = user["nombre"]
                session["rol"] = user["rol"]
                return redirect(url_for("solicitudes"))
            else:
                error = "Clave incorrecta."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- ROUTES INTERNAS ----------------
@app.route("/solicitudes")
@login_required
def solicitudes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()

    return render_template("solicitudes.html", rows=rows)


@app.route("/crear-vet", methods=["GET", "POST"])
@admin_required
def crear_vet():
    error = None

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        nombre = request.form.get("nombre", "").strip()
        clave = request.form.get("clave", "").strip()

        if not usuario or not nombre or not clave:
            error = "Completa todos los campos."
            return render_template("crear_vet.html", error=error)

        conn = get_db()
        c = conn.cursor()

        # Verificar si ya existe
        c.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
        if c.fetchone():
            conn.close()
            error = "Ese usuario ya existe."
            return render_template("crear_vet.html", error=error)

        c.execute("""
            INSERT INTO usuarios (usuario, nombre, clave_hash, rol, creado)
            VALUES (?, ?, ?, ?, ?)
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

    return render_template("crear_vet.html", error=error)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_db()
    # debug=True solo local. En producción Render usa gunicorn
    app.run(debug=True)
