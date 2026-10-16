"""
Pluggable document storage backend.
Supports: local filesystem, S3-compatible (MinIO/AWS), Azure Blob.
"""

import asyncio
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
    @abstractmethod
    async def list(self, prefix: str) -> dict:
        """One level of the storage tree under ``prefix`` (a folder key, with or
        without a trailing slash). Returns {"folders": [name, ...],
        "files": [{"name", "size", "modified"}, ...]}, both sorted by name."""


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

    async def list(self, prefix: str) -> dict:
        from datetime import datetime, timezone
        folders, files = [], []
        p = self._path(prefix.strip("/")) if prefix.strip("/") else self.base_path
        if os.path.isdir(p):
            with os.scandir(p) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        folders.append(e.name)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat()
                        files.append({"name": e.name, "size": st.st_size,
                                      "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
        return {"folders": sorted(folders), "files": sorted(files, key=lambda f: f["name"])}


class S3Storage(StorageBackend):
    """S3-compatible object storage (SeaweedFS, MinIO, AWS). Path-style addressing; boto3
    calls run in a worker thread so a slow store never blocks the API's event loop.
    The bucket must already exist — a system's key is allowed only its own bucket."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str):
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise RuntimeError("boto3 required for S3 storage: pip install boto3")
        self.client = boto3.session.Session().client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=5, read_timeout=30, retries={"max_attempts": 3, "mode": "standard"}),
        )
        self.bucket = bucket
        logger.info("S3 storage: %s/%s", endpoint, bucket)

    async def put(self, key: str, data: bytes, content_type: str = "") -> str:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data, **extra)
        return key

    async def get(self, key: str) -> Optional[bytes]:
        def _get():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self.client.exceptions.NoSuchKey:
                return None
            except Exception as e:
                code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
                if code in ("NoSuchKey", "404", "NotFound"):
                    return None
                raise
        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        def _head():
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception as e:
                code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
                if code in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
        return await asyncio.to_thread(_head)

    async def list(self, prefix: str) -> dict:
        prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

        def _list():
            folders, files = [], []
            for page in self.client.get_paginator("list_objects_v2").paginate(
                    Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                for cp in page.get("CommonPrefixes", []):
                    folders.append(cp["Prefix"][len(prefix):].rstrip("/"))
                for o in page.get("Contents", []):
                    name = o["Key"][len(prefix):]
                    if name:
                        files.append({"name": name, "size": o["Size"], "modified": o["LastModified"].isoformat()})
            return {"folders": sorted(folders), "files": sorted(files, key=lambda f: f["name"])}
        return await asyncio.to_thread(_list)


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

    async def list(self, prefix: str) -> dict:
        prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        folders, files = [], []
        for item in self.container_client.walk_blobs(name_starts_with=prefix, delimiter="/"):
            name = item.name[len(prefix):]
            if name.endswith("/"):
                folders.append(name.rstrip("/"))
            elif name:
                files.append({"name": name, "size": item.size,
                              "modified": item.last_modified.isoformat() if item.last_modified else None})
        return {"folders": sorted(folders), "files": sorted(files, key=lambda f: f["name"])}


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
