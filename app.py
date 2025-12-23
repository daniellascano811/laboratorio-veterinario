import os
import psycopg2
from psycopg2.extras import RealDictCursor

from functools import wraps
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
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada en variables de entorno.")
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


# =========================
# INIT DB (crea tablas si no existen)
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
        fecha DATE NULL,
        horario TEXT,
        estado TEXT DEFAULT 'pendiente',
        creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Admin por defecto
    cur.execute("SELECT 1 FROM usuarios WHERE usuario='admin'")
    existe = cur.fetchone()
    if not existe:
        cur.execute("""
            INSERT INTO usuarios (usuario, nombre, password)
            VALUES ('admin', 'Administrador', '1234')
        """)

    conn.commit()
    cur.close()
    conn.close()


# ✅ IMPORTANTE: esto hace que Render también cree tablas/admin
# (Gunicorn importa el archivo, así que esto sí corre)
try:
    init_db()
except Exception as e:
    # En producción, si algo falla, Render lo muestra en logs.
    # No rompemos el arranque si por algún motivo la DB está temporalmente no lista.
    print("init_db() error:", e)


# =========================
# LOGIN REQUIRED
# =========================
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("formulario.html", title="Nueva solicitud")


@app.route("/solicitud", methods=["POST"])
def crear_solicitud():
    zona = request.form.get("zona")
    dueno = request.form.get("dueno_nombre")
    tel = request.form.get("dueno_telefono")
    mascota = request.form.get("mascota_nombre")
    muestra = request.form.get("muestra_tipo")
    direccion = request.form.get("direccion")

    # ✅ Si fecha viene vacía, manda None (NULL) a Postgres
    fecha_str = request.form.get("fecha", "").strip()
    fecha = fecha_str if fecha_str else None

    horario = request.form.get("horario", "").strip() or None

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO solicitudes
        (zona, dueno, tel, mascota, muestra, direccion, fecha, horario)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (zona, dueno, tel, mascota, muestra, direccion, fecha, horario))

    conn.commit()
    cur.close()
    conn.close()

    return render_template("confirmacion.html", title="Solicitud enviada")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "").strip()

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
# START LOCAL
# =========================
if __name__ == "__main__":
    app.run(debug=True)
