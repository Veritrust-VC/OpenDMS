# Dokumenta pārsūtīšana citai iestādei (e-adrese)

Iestāde pārsūta saņemtu dokumentu citai iestādei e-adresē — tā, kā tas notiek tagad,
caur VDAA DIV. Laboratorijā DIV aizstāj `div-emulator/` (tās pašas darbības un aploksne).

## Plūsma

```
Sūtītāja DVS                                     DIV (emulators)          Saņēmēja DVS
 darbinieks: „Pārsūtīt citai iestādei”
  → pieprasījums (adresāts, iemesls, pavadvēstule, datnes)
  → process vdvc/dokumenta-parsutisana (trigeris document.forwarding)
      forward.request@1   nolasa pieprasījumu
      DMN                 sūtījuma veids, metadatu pievienošana, iesniedzēja informēšana
      div.send@1          DIV aploksne + datnes ──SendMessage──▶  pastkaste
      forward.record@1    DVS notikums DocumentSent; reģistrā DocumentSent → adresāta DID
      submitter.notify@1  e-pasts iesniedzējam „pārsūtīts …”
                                                   ◀──GetMessageHeaders/GetMessage── ievade „e-adrese”
                                                                      → reģistrā DocumentReceived uz TO PAŠU
                                                                        reģistra dokumentu (mainās turētājs)
                                                                      → DVS dokuments + procesi
                                                   ◀──ConfirmMessage──
  statuss: nosūtīts → saņemts → apstiprināts  ◀──paziņojumi (Delivered, Confirmed)
```

## DIV aploksne

`http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0` `Envelope`:

| Daļa | Saturs |
|---|---|
| `GeneralMetadata` | autors (informācijas sistēma), datums, `DocumentKindCode` (no DMN), apraksts = pavadvēstule, nosaukums |
| `PayloadReference/File` | katra datne: MIME, izmērs, nosaukums, `ContentReference` = LV-DATNE ID, SHA-256 |
| `ExtendedMetadata/p:Parsutisana` | `urn:lv:vdvc:parsutisana:1.0`: LV-DOK ID, reģistra DID, sūtītāja DID, sūtītāja reģ. Nr., iemesls |
| `SenderTransportMetadata` | sūtītāja e-adrese, atsauce, adresāti, paziņot par piegādi |

Ja DMN tā nosaka, pievieno `metadati.xml` (Dokumentu metadatu standarts) — saņēmējs to glabā
kā `sutitaja-metadati.xml` (izcelsmes pierādījums).

## Konfigurācija (bez saskarnes)

| Kur | Kas |
|---|---|
| DVS vide | `DIV_URL`, `DIV_TOKEN`, `DIV_E_ADDRESS` |
| `ievade.yaml` (saņēmējam) | kanāls `veids: e-adrese` |
| DVS procesi | trigeris `document.forwarding` → `lv.vdvc.dokumenta-parsutisana` |
| Emulators | `addresses.yaml` — e-adrešu katalogs; žetoni vidē |
