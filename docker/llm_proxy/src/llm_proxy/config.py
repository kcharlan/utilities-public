from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 4141
    log_level: str = "info"
    output_dir: str = "/output"


settings = Settings()
