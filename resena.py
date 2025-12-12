from pydantic import BaseModel, Field, EmailStr, BeforeValidator
from typing import Optional, Annotated
from datetime import datetime

PyObjectId = Annotated[str, BeforeValidator(str)]


class Resena(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)

    # Datos del establecimiento [cite: 16, 17, 18, 19]
    nombre_establecimiento: str
    direccion: str
    latitud: float
    longitud: float
    valoracion: int  # 0 a 5

    # Datos del autor y seguridad
    autor_nombre: str
    autor_email: EmailStr
    token_oauth: str  # Guardamos el token usado
    fecha_emision_token: datetime = Field(default_factory=datetime.now)
    fecha_caducidad_token: Optional[datetime] = None

    # Multimedia [cite: 30]
    imagen_url: Optional[str] = None


    class Config:
        # Esto permite que Pydantic entienda tanto 'id' como '_id'
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "nombre": "Estudiante IW",
                "email": "estudiante@ucm.es"
            }
        }