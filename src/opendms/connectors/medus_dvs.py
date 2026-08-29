"""MEDUS DVS connector — declared, not implemented.

The write-back leg: once OpenDMS has classified and routed an incoming document,
the registration is meant to land in the organisation's existing DVS rather than
living only in the pilot system. Nothing about that interface is known to us
yet — not the protocol, not whether a public API exists at all.

ONE QUESTION MATTERS MORE THAN THE REST and is called out first in SPEC: who
allocates the registration number. If MEDUS owns the sequence, OpenDMS must ask
for a number and never mint one, otherwise the two systems will diverge and the
lietvedība record becomes unreliable. That single answer changes the document
lifecycle, not just this connector.

SECOND, AND WORTH RAISING BEFORE BUILDING: the comparable Process-as-Code pilot
agreements exclude production deployment and full integration during the pilot
(the Tukums Vienošanās 2.2 is explicit about it). If the Rīgas siltums agreement
carries the same exclusion, then write-back into a live MEDUS may be out of
scope regardless of whether the interface exists, and the pilot should target a
test instance or a recorded intent rather than a real registration.
"""

from __future__ import annotations

from opendms.connectors.base import Field, Operation, PlaceholderDriver, Result

KIND = "medus_dvs"
DISPLAY_NAME = "MEDUS DVS"
IMPLEMENTED = False
SUMMARY = "Registration write-back into the organisation's document management system."

CONFIG_FIELDS = (
    Field("base_url", "Service base URL", required=False),
    Field("protocol", "Protocol", required=False, kind="select",
          choices=("rest", "soap", "file_exchange", "database"),
          help="Unknown at time of writing; decides the entire client shape."),
    Field("register_code", "Target register", required=False,
          help="Which MEDUS register incoming documents should be written to."),
)

SECRET_FIELDS = (
    Field("username", "Service account", required=False),
    Field("password", "Password / API key", kind="password", required=False),
)

OPERATIONS = (
    Operation("register_document", "connector/medus.register-document",
              "Write a classified incoming document into the DVS register."),
    Operation("attach_file", "connector/medus.attach-file",
              "Attach the original file to a registered document."),
    Operation("fetch_nomenclature", "connector/medus.fetch-nomenclature",
              "Read the document classification scheme.", direction="inbound"),
)

SPEC: tuple[str, ...] = (
    "WHO ALLOCATES THE REGISTRATION NUMBER — MEDUS or OpenDMS. If MEDUS owns the "
    "sequence, OpenDMS must request a number rather than mint one, and the document "
    "lifecycle changes accordingly. Answer this before anything else.",
    "Whether the pilot agreement permits writing into a live DVS at all, or whether a "
    "test instance is required (compare Tukums Vienošanās 2.2, which excludes "
    "production integration during the pilot).",
    "Vendor, product version, and whether a documented API exists — or whether the only "
    "realistic integration is a file drop or a direct database view.",
    "Protocol and message format: REST/JSON, SOAP/XML, or a watched folder with an "
    "accompanying metadata schema.",
    "Authentication and whether a service account can be issued for the pilot.",
    "The document classification scheme (nomenklatūra) in use and how it is exposed — "
    "whether OpenDMS should read it from MEDUS or hold its own copy.",
    "Mandatory metadata for a registration: which fields must be present, their value "
    "domains, and which are validated on write.",
    "Idempotency: whether re-sending the same document creates a duplicate, and if there "
    "is an external-reference field OpenDMS can use as the deduplication key.",
    "Whether MEDUS can notify OpenDMS of later status changes (callback or polling), or "
    "whether the write is fire-and-forget.",
    "Retention and access rules that apply once a document is registered, and who the "
    "pārzinis is for the registered copy.",
)


async def test(config: dict, secret: dict) -> Result:
    return PlaceholderDriver._refuse(DISPLAY_NAME, SPEC)


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    return PlaceholderDriver._refuse(DISPLAY_NAME, SPEC)
