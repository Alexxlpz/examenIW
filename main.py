import json
import uvicorn
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from motor.motor_asyncio import AsyncIOMotorClient
from environs import Env
from bson import ObjectId
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import time

# --- TUS MODELOS ---
from usuario import Usuario
from resena import Resena

# --- CONFIGURACIÓN APP ---
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

#usuarios_col = db["Usuarios"]
#eventos_col = db["Eventos"]
#visitas_col = db["Visitas"]
col_resenas = db["Resenas"]

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
        return RedirectResponse(url="/resenas")
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

        now = int(time.time())
        expires_at = token.get("expires_at")

        request.session["token_data"] = {
            "access_token": token.get("access_token"),
            "created_at": token.get("created_at") or now,
            "expires_at": expires_at or (now + 3599) # que es lo que suele poner google de tardanza, esto lo pondremos por si algun casual da fallo pero no deberia
        }

        usuario = Usuario(nombre=user_info["name"], email=user_info["email"])
        request.session["user"] = json.loads(usuario.model_dump_json(by_alias=True))

        return RedirectResponse(url="/resenas")
    except Exception as e:
        print(f"Error Auth: {e}")
        return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


# --- LÓGICA PRINCIPAL ---

@app.get("/resenas", response_class=HTMLResponse)
async def listar_resenas(request: Request):
    usuario = get_usuario_actual(request)
    if not usuario: return RedirectResponse("/")

    lista_resenas = []  # Para pintar las tarjetas con Jinja
    lista_para_mapa = []  # Para pintar los marcadores con JS

    async for doc in col_resenas.find():
        # 1. Para el listado visual (Objetos Pydantic)
        lista_resenas.append(Resena(**doc))

        # 2. Para el mapa (Diccionarios serializables a JSON)
        # Hacemos una copia para no afectar al objeto original
        d = doc.copy()
        d["id"] = str(d["_id"])  # Convertimos ObjectId a String
        if "_id" in d: del d["_id"]
        lista_para_mapa.append(d)

    return templates.TemplateResponse("lista.html", {
        "request": request,
        "usuario": usuario,
        "resenas": lista_resenas,
        "resenas_json": json.dumps(lista_para_mapa, default=str)  # Serializamos fechas etc.
    })


@app.get("/resenas/crear", response_class=HTMLResponse)
async def form_crear_resena(request: Request):
    usuario = get_usuario_actual(request)
    if not usuario: return RedirectResponse("/")
    return templates.TemplateResponse("crear.html", {"request": request, "usuario": usuario})


@app.post("/resenas/crear")
async def crear_resena_db(
        request: Request,
        nombre: str = Form(...),
        direccion: str = Form(...),
        valoracion: int = Form(...),
        latitud: float = Form(...),
        longitud: float = Form(...),
        imagen: UploadFile = File(None)
):
    usuario = get_usuario_actual(request)
    token_info = request.session.get("token_data")

    if not usuario or not token_info: return RedirectResponse("/")

    url_img = subir_imagen_cloudinary(imagen)

    now = int(time.time())

    ts_emision = token_info.get("created_at") or now
    ts_caducidad = token_info.get("expires_at") or (now + 3600)
    nueva_resena = Resena(
        nombre_establecimiento=nombre,
        direccion=direccion,
        valoracion=valoracion,
        latitud=latitud,
        longitud=longitud,
        imagen_url=url_img,
        autor_nombre=usuario.nombre,
        autor_email=usuario.email,
        token_oauth=token_info.get("access_token", "TOKEN_NO_DISPONIBLE"),

        fecha_emision_token=ts_emision,
        fecha_caducidad_token=ts_caducidad
    )

    await col_resenas.insert_one(nueva_resena.model_dump(by_alias=True, exclude={"id"}))

    return RedirectResponse("/resenas", status_code=303)


@app.get("/resenas/detalle/{id_resena}", response_class=HTMLResponse)
async def detalle_resena(request: Request, id_resena: str):
    usuario = get_usuario_actual(request)
    if not usuario: return RedirectResponse("/")

    doc = await col_resenas.find_one({"_id": ObjectId(id_resena)})
    if not doc: return HTMLResponse("Reseña no encontrada", 404)

    resena = Resena(**doc)

    fechas = {
        "emision": resena.fecha_emision_token,
        "caducidad": resena.fecha_caducidad_token
    }

    return templates.TemplateResponse("detalle.html", {
        "request": request,
        "usuario": usuario,
        "r": resena,
        "fechas": fechas
    })

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)