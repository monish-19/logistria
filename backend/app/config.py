from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "logistria.db"
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./logistria.db"
AUTO_LIMIT = float(os.getenv("AUTO_LIMIT", "5000"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "groq/openai/gpt-oss-120b")
NARRATOR_MODEL = os.getenv("NARRATOR_MODEL", "groq/llama-3.1-8b-instant")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")
ADAPTER = (os.getenv("ADAPTER") or "mock").lower()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
ERP_NEXT_BASE_URL = os.getenv("ERP_NEXT_BASE_URL") or os.getenv("ERP_BASE_URL") or ""
ERP_NEXT_API_KEY = os.getenv("ERP_NEXT_API_KEY") or os.getenv("ERP_API_KEY") or ""
ERP_NEXT_API_SECRET = os.getenv("ERP_NEXT_API_SECRET") or os.getenv("ERP_API_SECRET") or ""
GENERIC_ADAPTER_CONFIG = os.getenv("GENERIC_ADAPTER_CONFIG") or os.getenv("ERP_GENERIC_CONFIG") or ""
GENERIC_BASE_URL = os.getenv("GENERIC_BASE_URL") or os.getenv("ERP_BASE_URL") or ""
ADAPTER_FALLBACK = os.getenv("ADAPTER_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
DEPOT_LAT = float(os.getenv("DEPOT_LAT", "13.0827"))
DEPOT_LON = float(os.getenv("DEPOT_LON", "80.2707"))
