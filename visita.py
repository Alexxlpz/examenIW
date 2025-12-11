from pydantic import BaseModel, Field, BeforeValidator
from typing import Optional, Annotated
from datetime import datetime

# Esto permite que Pydantic maneje los _id de MongoDB transparentemente
PyObjectId = Annotated[str, BeforeValidator(str)]

class Visita(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    anfitrion: str        # Email del dueño del mapa
    visitante: str        # Nombre de quien visita
    visitante_email: str  # Email de quien visita
    timestamp: datetime = Field(default_factory=datetime.now) # Fecha automática