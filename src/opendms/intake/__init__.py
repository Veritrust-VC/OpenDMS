"""Ievade — how documents enter the DVS.

Channels (ievades kanāli):
  - manual upload in the DVS GUI (routers/documents.py) — always on;
  - e-mail mailbox (intake/email_channel.py) — IMAP poll, SMTP acknowledgement;
  - public web form (routers/intake.py, frontend /iesniegt/<id>).

All non-GUI channels go through intake/service.py:ingest(), configured in a
YAML file (intake/config.py). There is no configuration GUI by design.
"""
