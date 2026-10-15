# LNA pieņemšanas simulators

Laboratorijas aizstājējs Latvijas Nacionālā arhīva elektroniskajai saskarnei, ar ko DVS iesniedz
iznīcināšanas aktus (104. p.), uzskaites sarakstus (94.–96. p.), gada nodošanas vienošanās (174. p.)
un OPEX pakotnes (69., 176. p.). Pakotni iestāde augšupielādē LNA S3 ievades krātuvē (`<iestāde>/…zip`
un `.zip.sha256`); simulators pārbauda kontrolsummu, pārbauda pakotni ar standarta pārbaudītāju
(`kisc/dokumentu-arhivesanas-standarts` `riki/validet_pakotni.py`), ieraksta atskaiti `<pakotne>.parbaude.json`
un pieņemtu pakotni izvērš `glabatava/<iestāde>/` (Preservica OPEX pakāpeniskās ielādes vietā).

| Darbība | HTTP |
|---|---|
| Iesniegt | `POST /api/v1/iesniegumi` `{veids: akts\|saraksts\|plans\|nodosana, atsauce, xml \| s3Key \| gads}` |
| Statuss un lēmums | `GET /api/v1/iesniegumi/{id}` |
| Arhīvista skats | `GET /` (manuāla izskatīšana, ja `LNA_REVIEW=manual`) |

Lēmumi: `akts` → Saskanots/Noraidits (XSD, pastāvīgi glabājamie aktā, EK izvērtējums); `saraksts` →
Apstiprinats/Noraidits (XSD, arhīva kods, uzskaites kodi, kopsavilkums); `plans` → Saskanots;
`nodosana` → Pienemts/Noraidits ar pieņemšanas akta datiem.

**Atšķirības no LNA:** JSON pār HTTP ar iestādes žetonu; lēmumi pēc formāliem noteikumiem vai arhīvista
klikšķa; saturiskā ekspertīze netiek simulēta.

```
docker build -f lna-simulator/Dockerfile -t pac/lna-simulator .
docker run -p 8710:8710 -v lna-data:/data -e LNA_TOKENS="ombud=…" \
  -e LNA_S3_ENDPOINT=… -e LNA_S3_ACCESS_KEY=… -e LNA_S3_SECRET_KEY=… pac/lna-simulator
```
