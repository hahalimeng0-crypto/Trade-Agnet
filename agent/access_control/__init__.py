"""Authentication primitives for the HTTP and WebSocket boundary."""

from .jwt import JWTCodec, JWTError
from .models import Principal

__all__ = [
    "JWTCodec",
    "JWTError",
    "Principal",
]
