from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Render assigns a port dynamically through this variable.
    # Default is 8000 for local development.
    PORT: int = 8000

    class Config:
        env_file = ".env"
        # Ignore extra environment variables not defined here
        extra = "ignore" 

# Instantiate settings to import across the app
settings = Settings()