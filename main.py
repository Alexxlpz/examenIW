import json
import uvicorn
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from motor.motor_asyncio import AsyncIOMotorClient
from environs import Env
from bson import ObjectId
from datetime import datetime

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# --- TUS MODELOS ---
from usuario import Usuario
from evento import Evento
from visita import Visita

env = Env()
env.read_env(path=".env", override=True)

app = FastAPI(title="Examen IW - Clean Code")

# 1. MIDDLEWARE
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.add_middleware(SessionMiddleware, secret_key=env("SECRET_KEY", "secreto"))

# 2. CARGAMOS EL DIRECTORIO DE TEMPLATES
templates = Jinja2Templates(directory="templates")

# 3. OAUTH
oauth = OAuth()
oauth.register(
    name='google',
    client_id=env("GOOGLE_CLIENT_ID"),
    client_secret=env("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# 4. CLOUDINARY
cloudinary.config(
    cloud_name=env("CLOUDINARY_CLOUD_NAME"),
    api_key=env("CLOUDINARY_API_KEY"),
    api_secret=env("CLOUDINARY_API_SECRET")
)

# 5. DATABASE SETUP (VARIABLES GLOBALES)
client = AsyncIOMotorClient(env("MONGO_URI"))
db = client["ExamenDB"]

usuarios_col = db["Usuarios"]
eventos_col = db["Eventos"]
visitas_col = db["Visitas"]


# FUNCIONES DE AYUDA

def subir_imagen_cloudinary(imagen: UploadFile):
    if not imagen or not imagen.filename:
        return None
    try:
        res = cloudinary.uploader.upload(imagen.file, folder="examen_iw")
        return res.get("secure_url")
    except Exception as e:
        print(f"Error Cloudinary: {e}")
        return None


def get_usuario_actual(request: Request):
    user_data = request.session.get("user")
    if user_data:
        return Usuario(**user_data)
    return None


# --- RUTAS AUTH ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if get_usuario_actual(request):
        return RedirectResponse(url="/mapa")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login")
async def login(request: Request):
    base_url_env = env("BASE_URL", None)

    if base_url_env:
        redirect_uri = f"{base_url_env}/auth"
    else:
        # En local: detecta http://localhost:8000/auth automáticamente
        redirect_uri = request.url_for('auth')

    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth")
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
        if not user_info: return HTMLResponse("Error Google")

        # Usamos la variable 'usuarios_col'
        usuario_existente = await usuarios_col.find_one({"email": user_info["email"]})

        if usuario_existente:
            await usuarios_col.update_one(
                {"_id": usuario_existente["_id"]},
                {"$set": {"nombre": user_info["name"]}}
            )
            usuario_db = Usuario(**usuario_existente)
            usuario_db.nombre = user_info["name"]
        else:
            usuario_db = Usuario(nombre=user_info["name"], email=user_info["email"])
            # model_dump para convertir el Pydantic a diccionario para Mongo
            res = await usuarios_col.insert_one(usuario_db.model_dump(by_alias=True, exclude={"id"}))
            usuario_db.id = str(res.inserted_id)

        request.session["user"] = json.loads(usuario_db.model_dump_json(by_alias=True))
        return RedirectResponse(url="/mapa")
    except Exception as e:
        print(f"Error Auth: {e}")
        return RedirectResponse(url="/")


@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/")


# --- LÓGICA PRINCIPAL ---

@app.post("/visitar")
async def visitar_otro(email_destino: str = Form(...)):
    return RedirectResponse(url=f"/mapa?target_email={email_destino}", status_code=303)


@app.get("/mapa", response_class=HTMLResponse)
async def ver_mapa(request: Request, target_email: str = None):
    usuario_logueado = get_usuario_actual(request)
    if not usuario_logueado: return RedirectResponse("/")

    email_dueno = target_email if target_email else usuario_logueado.email #si estamos visitando a otro cojemos el tarjet (que es al que vamos a visitar) si no es nuestro propio email
    es_propietario = (usuario_logueado.email == email_dueno) #si el email del usuario logueado es igual al email del target, entonces es el propietario, si no esta visitando y recortamos funcionalidad

    lista_visitas = []

    if es_propietario:
        # A. LEER VISITAS (Usamos Pydantic para traer los datos limpios)
        cursor = visitas_col.find({"anfitrion": email_dueno}).sort("timestamp", -1)
        async for doc in cursor:
            # Validamos con Pydantic al leer
            v_obj = Visita(**doc)
            # Para la vista, convertimos a dict y formateamos fecha
            v_dict = v_obj.model_dump()
            v_dict["timestamp"] = v_obj.timestamp.strftime("%d/%m/%Y %H:%M")
            lista_visitas.append(v_dict)
    else:
        # B. REGISTRAR VISITA (Usamos Pydantic para crear)
        # Creamos el objeto Visita
        nueva_visita = Visita(
            anfitrion=email_dueno,
            visitante=usuario_logueado.nombre,
            visitante_email=str(usuario_logueado.email)
            # timestamp se pone solo gracias al default_factory en el modelo
        )

        # Insertamos usando la variable global 'visitas_col'
        await visitas_col.insert_one(nueva_visita.model_dump(by_alias=True, exclude={"id"}))

    # C. OBTENER EVENTOS (Variable global 'eventos_col')
    eventos_list = []
    cursor_ev = eventos_col.find({"creador_email": email_dueno})
    async for doc in cursor_ev:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
        eventos_list.append(doc)

    return templates.TemplateResponse("mapa.html", {
        "request": request,
        "usuario": usuario_logueado,
        "target_email": email_dueno,
        "es_propietario": es_propietario,
        "eventos": eventos_list,
        "eventos_json": json.dumps(eventos_list),
        "visitas": lista_visitas
    })


@app.post("/eventos/crear")
async def crear_evento(
        request: Request,
        nombre: str = Form(...),
        latitud: float = Form(...),
        longitud: float = Form(...),
        imagen: UploadFile = File(None)
):
    usuario = get_usuario_actual(request)
    if not usuario: return RedirectResponse("/")

    url_img = subir_imagen_cloudinary(imagen)

    nuevo_evento = Evento(
        nombre=nombre,
        latitud=latitud,
        longitud=longitud,
        imagen_url=url_img,
        creador_email=str(usuario.email),
        creador_nombre=usuario.nombre
    )

    # Variable global 'eventos_col'
    await eventos_col.insert_one(nuevo_evento.model_dump(by_alias=True, exclude={"id"}))
    return RedirectResponse(url="/mapa", status_code=303)


@app.post("/eventos/borrar/{id_evento}")
async def borrar_evento(id_evento: str, request: Request):
    usuario = get_usuario_actual(request)
    if not usuario: return RedirectResponse("/")

    # Variable global 'eventos_col'
    await eventos_col.delete_one({
        "_id": ObjectId(id_evento),
        "creador_email": usuario.email
    })
    return RedirectResponse(url="/mapa", status_code=303)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)