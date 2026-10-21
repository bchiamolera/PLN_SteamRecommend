"""Credentials belong to the offline collector, never to the frontend."""
import os
from pathlib import Path
from dotenv import load_dotenv

def steam_api_key(operation, *, required=True):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / "1_Coleta_Dados" / ".env", override=False)
    value = os.getenv("STEAM_API_KEY", "").strip()
    if required and not value:
        raise ValueError(f"{operation} requires STEAM_API_KEY. Set it in the environment or .env. Register at https://steamcommunity.com/dev/apikey")
    return value
