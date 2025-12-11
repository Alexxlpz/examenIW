from pydantic import BaseModel, Field
from typing import Optional
from usuario import PyObjectId  # Reutilizamos el tipo


class Evento(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)

    nombre: str
    latitud: float
    longitud: float
    imagen_url: Optional[str] = None

    # Guardamos datos básicos del creador para no hacer mil consultas
    creador_email: str
    creador_nombre: str

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "nombre": "Hackathon Web",
                "latitud": 40.416,
                "longitud": -3.703,
                "creador_email": "estudiante@ucm.es",
                "creador_nombre": "Estudiante IW"
            }
        }