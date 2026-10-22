"""Where things live — the same layout on disk and in an S3 container.

    dokumenti/<mape>/datnes/<datne>      the document's files
    dokumenti/<mape>/metadati.xml, …     its standard package (built in the same folder)
    dokumenti/<mape>/dvs-ieraksts.json   its DVS record (export / record sync)

<mape> is the package folder of the LV-DOK identifier (LV-DOK_…) or DVS-<id> while the
document has no identifier yet. When the identifier is assigned, the files move from
DVS-<id> to the LV-DOK folder, so one document is always one folder.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

ROOT = "dokumenti"


def folder(doc_id: int, doc_uid: Optional[str]) -> str:
    if doc_uid:
        from opendms.standard.package import folder_name
        return folder_name(doc_uid)
    return f"DVS-{doc_id}"


def prefix(doc_id: int, doc_uid: Optional[str]) -> str:
    return f"{ROOT}/{folder(doc_id, doc_uid)}"


async def file_key(storage, doc_id: int, doc_uid: Optional[str], file_name: str, data: bytes) -> tuple[str, str]:
    """Key and final file name for a new file of a document. A different file with the
    same name gets a suffix (name-2.ext); the same bytes reuse the existing key."""
    base = prefix(doc_id, doc_uid)
    stem, ext = os.path.splitext(file_name)
    name, n = file_name, 1
    while True:
        key = f"{base}/datnes/{name}"
        cur = await storage.get(key) if await storage.exists(key) else None
        if cur is None or hashlib.sha256(cur).digest() == hashlib.sha256(data).digest():
            return key, name
        n += 1
        name = f"{stem}-{n}{ext}"
