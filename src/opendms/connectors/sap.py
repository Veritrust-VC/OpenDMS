"""SAP connector — declared, not implemented.

Rīgas siltums needs master-data lookup against SAP so a document arriving in the
DVS can be matched to a real counterparty, contract or object rather than to a
free-text name. That is the whole use case, and it is entirely blocked on
information we do not have: nobody has told us which SAP product, which
integration channel, or which objects are in scope. Guessing here is expensive —
an OData v4 client and an RFC/BAPI client share almost no code.

So this module registers the connection kind, renders in the GUI, and answers
every call with a structured refusal that names what is missing. SPEC below is
the integration questionnaire; it lives next to the code it describes so the two
cannot drift apart. Once answered, `IMPLEMENTED = True` and the operations get
real bodies — no other file needs to change.
"""

from __future__ import annotations

from opendms.connectors.base import Field, Operation, PlaceholderDriver, Result

KIND = "sap"
DISPLAY_NAME = "SAP"
IMPLEMENTED = False
SUMMARY = "Master-data lookup — counterparty, contract and object references."

CONFIG_FIELDS = (
    Field("base_url", "Service base URL", required=False,
          help="OData service root or Integration Suite endpoint, once known."),
    Field("client", "SAP client", required=False, placeholder="100"),
    Field("channel", "Integration channel", required=False, kind="select",
          choices=("odata_v2", "odata_v4", "rfc_bapi", "soap", "integration_suite"),
          help="Decides which client we build. Unknown at time of writing."),
)

SECRET_FIELDS = (
    Field("username", "Technical user", required=False),
    Field("password", "Password / client secret", kind="password", required=False),
)

OPERATIONS = (
    Operation("lookup_partner", "connector/sap.lookup-partner",
              "Find a business partner by registration number or name."),
    Operation("lookup_contract", "connector/sap.lookup-contract",
              "Find contracts or supply objects for a partner."),
)

SPEC: tuple[str, ...] = (
    "Product and release — S/4HANA on-premise, S/4HANA Cloud, or ECC 6.0 (with EHP level).",
    "Integration channel — OData v2 or v4 via SAP Gateway, RFC/BAPI, SOAP, or an "
    "Integration Suite (CPI) iFlow fronting it. This choice determines the client library.",
    "Whether an iFlow / API can be exposed for the pilot, or whether only a read replica "
    "or periodic extract is realistic within the pilot's scope.",
    "Authentication — technical user with basic auth, OAuth 2.0 client credentials, "
    "X.509 client certificate, or SAML bearer assertion.",
    "Network path from the pilot environment: direct, VPN, or IP allowlist, and who "
    "operates the firewall rule.",
    "Which master-data objects are in scope — business partner (BP/BUT000), contract "
    "account (FI-CA), installation or point of delivery (IS-U), cost centre, employee.",
    "Which field OpenDMS should search on: reģistrācijas numurs, client number, "
    "contract number, or object address.",
    "Which fields may be returned, and whether any of them are personal data — that "
    "decides the GDPR basis, the minimisation and what may be written into a document.",
    "A test or QA system with representative data, and whether it can be reached "
    "during the pilot. Building against production is not acceptable.",
    "Rate limits, quotas, or batch windows we must respect.",
)


async def test(config: dict, secret: dict) -> Result:
    return PlaceholderDriver._refuse(DISPLAY_NAME, SPEC)


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    return PlaceholderDriver._refuse(DISPLAY_NAME, SPEC)
