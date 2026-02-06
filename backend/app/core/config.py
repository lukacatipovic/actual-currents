"""
Configuration settings for Actual Currents API
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    # API Configuration
    API_VERSION: str = "v1"
    PROJECT_NAME: str = "Actual Currents API"
    DEBUG: bool = False

    # S3 Configuration
    S3_BUCKET: str = "actual-currents-data"
    S3_REGION: str = "us-east-2"
    ZARR_PATH: str = "adcirc54.zarr"

    # Data source (local or S3)
    # Use LOCAL for development, S3 for production
    DATA_SOURCE: str = "S3"  # Options: "LOCAL" or "S3"
    LOCAL_ZARR_PATH: str = "../../data/adcirc54.zarr"

    # Tidal prediction settings
    REFERENCE_TIME: str = "2000-01-01T00:00:00Z"  # ADCIRC reference time
    LATITUDE_FOR_NODAL: float = 55.0  # Used for nodal corrections

    # API limits
    MAX_NODES_PER_REQUEST: int = 500_000  # Prevent huge responses
    MAX_TIME_POINTS: int = 100  # Max time series points per request

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()
