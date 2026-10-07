from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    # ---------------------------------------------------------------
    # Supabase — identity (Auth) and data (Postgres) both live here.
    # ---------------------------------------------------------------
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    DATABASE_URL: str = ""  
    STORAGE_DIR: str = "./storage"

    # ---------------------------------------------------------------
    # Production Email Provider (Resend API)
    # ---------------------------------------------------------------
    RESEND_API_KEY: str = ""

    # ---------------------------------------------------------------
    # Sessions / cookies and CORS
    # ---------------------------------------------------------------
    COOKIE_SECURE: bool = True          
    COOKIE_DOMAIN: str = ""              
    ACCESS_COOKIE_NAME: str = "nc_access"
    REFRESH_COOKIE_NAME: str = "nc_refresh"
    CSRF_COOKIE_NAME: str = "nc_csrf"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # Default fallback origin string — actual production overrides 
    # should happen via Environment Variables in Render.
    CORS_ORIGINS: str = "https://notecast-web.onrender.com"

    # ---------------------------------------------------------------
    # Rate limiting
    # ---------------------------------------------------------------
    LOGIN_RATE_LIMIT: int = 5          
    LOGIN_RATE_WINDOW_SEC: int = 900   
    SIGNUP_RATE_LIMIT: int = 3
    SIGNUP_RATE_WINDOW_SEC: int = 3600
    RESET_RATE_LIMIT: int = 3
    RESET_RATE_WINDOW_SEC: int = 3600

    # ---------------------------------------------------------------
    # AI providers
    # ---------------------------------------------------------------
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""

    GEMINI_TEXT_MODEL: str = "gemini-3.5-flash"
    GEMINI_VISION_MODEL: str = "gemini-3.5-flash"
    GEMINI_ASR_MODEL: str = "gemini-3.5-flash"
    GEMINI_EMBED_MODEL: str = "text-embedding-004"

    GROQ_TEXT_MODEL: str = "openai/gpt-oss-120b"
    GROQ_VISION_MODEL: str = "meta-llama/llama-4-maverick-17b-128e-instruct"
    GROQ_ASR_MODEL: str = "whisper-large-v3"

    DEEPSEEK_TEXT_MODEL: str = "deepseek-chat"

    TEXT_PROVIDER_ORDER: str = "gemini,groq,deepseek"
    VISION_PROVIDER_ORDER: str = "gemini,groq"
    ASR_PROVIDER_ORDER: str = "groq,gemini"
    EMBED_PROVIDER_ORDER: str = "gemini"

    FREE_MONTHLY_VIDEOS: int = 100

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self):
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.STORAGE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        (p / "frames").mkdir(exist_ok=True)
        (p / "exports").mkdir(exist_ok=True)
        return p

    def order(self, csv: str) -> list[str]:
        return [p.strip().lower() for p in csv.split(",") if p.strip()]


settings = Settings()