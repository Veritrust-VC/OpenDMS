# UAPF Packages

This directory is mounted into the `uapf-engine` container as `/packages` (read-only).
Any `.uapf` files placed here at container build time (or via volume update + restart)
are loaded by the engine on startup.

The engine reloads packages only at startup. To deploy a new package version:

```bash
cp new-package.uapf ./uapf-packages/
docker compose restart uapf-engine
```

## Bundled

- `lv.tiesibsargs.iesnieguma-izskatisana-0.1.0.uapf` — Tiesibsarga complaint
  classification process. Source: https://processgit.org/AI_Sandbox/iesnieguma-izskatisana
