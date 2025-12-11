from pydantic import BaseModel, Field, EmailStr, BeforeValidator
from typing import Optional, Annotated

# Truco Pro: Esto convierte automáticamente el ObjectId de Mongo a string
# Así no tienes que hacerlo manualmente en cada endpoint.
PyObjectId = Annotated[str, BeforeValidator(str)]


class Usuario(BaseModel):
    # El alias="_id" es la clave mágica.
    # Le dice a Pydantic: "Si en la BD se llama '_id', guárdalo aquí en 'id'"
    id: Optional[PyObjectId] = Field(alias="_id", default=None)

    nombre: str
    email: EmailStr

    class Config:
        # Esto permite que Pydantic entienda tanto 'id' como '_id'
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "nombre": "Estudiante IW",
                "email": "estudiante@ucm.es"
            }
        }