"""
Pluggable document storage backend.
Supports: local filesystem, S3-compatible (MinIO/AWS), Azure Blob.
"""

import os, uuid, logging, shutil
from typing import Optional, BinaryIO
from abc import ABC, abstractmethod
from opendms.config import get_settings

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "") -> str: ...
    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]: ...
    @abstractmethod
    async def delete(self, key: str) -> bool: ...
    @abstractmethod
    async def exists(self, key: str) -> bool: ...


class LocalStorage(StorageBackend):
    def __init__(self, base_path: str):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.base_path, key.replace("/", os.sep))

    async def put(self, key: str, data: bytes, content_type: str = "") -> str:
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return key

    async def get(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    async def delete(self, key: str) -> bool:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)
            return True
        return False

    async def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))


class S3Storage(StorageBackend):
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str):
        try:
            import boto3
            from botocore.config import Config
            session = boto3.session.Session()
            self.client = session.client(
                "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                aws_secret_access_key=secret_key, region_name=region,
                config=Config(signature_version="s3v4"),
            )
            self.bucket = bucket
            # Ensure bucket exists
            try:
                self.client.head_bucket(Bucket=bucket)
            except Exception:
                self.client.create_bucket(Bucket=bucket)
            logger.info("S3 storage: %s/%s", endpoint, bucket)
        except ImportError:
            raise RuntimeError("boto3 required for S3 storage: pip install boto3")

    async def put(self, key: str, data: bytes, content_type: str = "") -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return key

    async def get(self, key: str) -> Optional[bytes]:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception:
            return None

    async def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


class AzureStorage(StorageBackend):
    def __init__(self, connection_string: str, container: str):
        try:
            from azure.storage.blob import BlobServiceClient
            self.blob_service = BlobServiceClient.from_connection_string(connection_string)
            self.container_client = self.blob_service.get_container_client(container)
            try:
                self.container_client.get_container_properties()
            except Exception:
                self.container_client.create_container()
            logger.info("Azure Blob storage: %s", container)
        except ImportError:
            raise RuntimeError("azure-storage-blob required: pip install azure-storage-blob")

    async def put(self, key: str, data: bytes, content_type: str = "") -> str:
        kwargs = {"content_settings": {"content_type": content_type}} if content_type else {}
        self.container_client.upload_blob(name=key, data=data, overwrite=True, **kwargs)
        return key

    async def get(self, key: str) -> Optional[bytes]:
        try:
            blob = self.container_client.get_blob_client(key)
            return blob.download_blob().readall()
        except Exception:
            return None

    async def delete(self, key: str) -> bool:
        try:
            self.container_client.delete_blob(key)
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        try:
            self.container_client.get_blob_client(key).get_blob_properties()
            return True
        except Exception:
            return False


_storage: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "s3":
            _storage = S3Storage(
                s.storage_s3_endpoint or "", s.storage_s3_bucket,
                s.storage_s3_access_key or "", s.storage_s3_secret_key or "", s.storage_s3_region,
            )
        elif s.storage_backend == "azure":
            _storage = AzureStorage(s.storage_azure_connection_string or "", s.storage_azure_container)
        else:
            _storage = LocalStorage(s.storage_local_path)
    return _storage


def generate_storage_key(org_id: int, filename: str) -> str:
    """Generate a unique storage key: org/{org_id}/YYYY/MM/{uuid}/{filename}"""
    from datetime import datetime
    now = datetime.utcnow()
    uid = uuid.uuid4().hex[:12]
    return f"org/{org_id}/{now.year}/{now.month:02d}/{uid}/{filename}"
