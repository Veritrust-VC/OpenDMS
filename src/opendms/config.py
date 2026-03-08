"""OpenDMS application configuration."""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "OpenDMS"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql://opendms:opendms@localhost:5432/opendms"
    db_pool_min: int = 2
    db_pool_max: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Elasticsearch (optional — degrades gracefully)
    elasticsearch_url: Optional[str] = None

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours
    superadmin_email: str = "admin@opendms.local"
    superadmin_password: str = "admin"  # Changed on first login

    # Storage
    storage_backend: str = "local"  # local | s3 | azure
    storage_local_path: str = "/data/documents"
    storage_s3_endpoint: Optional[str] = None  # MinIO: http://minio:9000
    storage_s3_bucket: str = "opendms-documents"
    storage_s3_access_key: Optional[str] = None
    storage_s3_secret_key: Optional[str] = None
    storage_s3_region: str = "us-east-1"
    storage_azure_connection_string: Optional[str] = None
    storage_azure_container: str = "opendms-documents"

    # VeriDocs SDK sidecar
    sdk_url: str = "http://localhost:3100"
    sdk_api_key: str = ""
    sdk_enabled: bool = True

    # Branding
    brand_name: str = "OpenDMS"
    brand_logo_url: str = ""
    brand_primary_color: str = "#0d7c66"

    model_config = {"env_prefix": "OPENDMS_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
