from pydantic import BaseModel
from typing import Optional

class Player(BaseModel):
    """
    Represents the state and data of a player in the bunker.
    """
    name: str
    is_connected: bool = True
    role: Optional[str] = None