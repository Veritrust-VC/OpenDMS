"""
Versioned response templates kept in OpenDMS (the "veidņu bibliotēka").

The process package decides WHICH template applies (a DMN returns the
template ID); the text lives here, versioned, so a lawyer can change wording
without touching the process. The seed set is SYNTHETIC — placeholders for the
office's real templates (Darba uzdevums N4) — and is marked as such.
"""

from __future__ import annotations

SEED = [
    ("TPL-ATTEIKT", "Atteikums uzsākt pārbaudes lietu", """\
[SINTĒTISKA VEIDNE — demonstrācijai]

Rekvizīti: Tiesībsarga birojs, {datums}, Nr. {registracijas_nr}
Adresāts: iesniedzējs

Tiesībsarga birojs ir izvērtējis Jūsu iesniegumu par jautājumu: {joma}.

Normatīvā atsauce: saskaņā ar Tiesībsarga likuma 13. pantu tiesībsargs pārbaudes
lietu neuzsāk, ja {pamatojums}.

Pārsūdzības kārtība: tiesībsarga lēmums nav pārsūdzams; Jums ir tiesības vērsties
kompetentajā iestādē vai tiesā.
"""),
    ("TPL-VIRZIT-IZSKATISANAI", "Iesnieguma pieņemšana izskatīšanai", """\
[SINTĒTISKA VEIDNE — demonstrācijai]

Rekvizīti: Tiesībsarga birojs, {datums}, Nr. {registracijas_nr}

Jūsu iesniegums par jautājumu „{joma}” ir pieņemts izskatīšanai un nodots
{nodala}. Atbildi sniegsim {termins} dienu laikā.

Normatīvā atsauce: Tiesībsarga likuma 12. pants.
"""),
    ("TPL-PIENEMSANA-BERNU", "Iesnieguma pieņemšana — bērnu tiesības", """\
[SINTĒTISKA VEIDNE — demonstrācijai]

Rekvizīti: Tiesībsarga birojs, {datums}, Nr. {registracijas_nr}

Jūsu iesniegums par bērna tiesību jautājumu ir pieņemts izskatīšanai Bērnu
tiesību nodaļā. Atbildi sniegsim {termins} dienu laikā.

Normatīvā atsauce: Tiesībsarga likuma 12. pants; Bērnu tiesību aizsardzības likums.
"""),
    ("TPL-PARSUTIT-CITAI-IESTADEI", "Iesnieguma pārsūtīšana kompetentajai iestādei", """\
[SINTĒTISKA VEIDNE — demonstrācijai]

Rekvizīti: Tiesībsarga birojs, {datums}, Nr. {registracijas_nr}

Jūsu iesniegumā minētais jautājums nav tiesībsarga kompetencē.
Kompetentā iestāde: {kompetenta_iestade}. Iesniegums pārsūtīts tai.

Normatīvā atsauce: Iesniegumu likuma 5. pants.

Pārsūdzības kārtība: lēmumu par pārsūtīšanu var apstrīdēt Tiesībsarga birojā
viena mēneša laikā.
"""),
    ("TPL-UZSAKT-PARBAUDI", "Pārbaudes lietas uzsākšana", """\
[SINTĒTISKA VEIDNE — demonstrācijai]

Rekvizīti: Tiesībsarga birojs, {datums}, Nr. {registracijas_nr}

Pamatojoties uz Jūsu iesniegumu, tiesībsargs uzsāk pārbaudes lietu par
jautājumu „{joma}”. Lieta nodota {nodala}.

Normatīvā atsauce: Tiesībsarga likuma 12. un 15. pants.
"""),
]


async def seed(conn) -> None:
    for tid, title, body in SEED:
        await conn.execute(
            """INSERT INTO response_templates (template_id, version, title, body, synthetic)
               VALUES ($1, 1, $2, $3, TRUE) ON CONFLICT (template_id, version) DO NOTHING""",
            tid, title, body)


async def latest(conn, template_id: str) -> dict | None:
    row = await conn.fetchrow(
        """SELECT template_id, version, title, body, synthetic FROM response_templates
            WHERE template_id = $1 AND is_active ORDER BY version DESC LIMIT 1""", template_id)
    return dict(row) if row else None
