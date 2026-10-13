# DIV (e-adrese) emulators

Laboratorijas aizstājējs VDAA DIV UnifiedService, ar ko iestāžu DVS sūta un saņem
dokumentus e-adresē. Darbības un aploksne atbilst tām, ko izmanto e-rēķinu klients
pret DIV: `SendMessage`, `GetMessageServerConfirmation`, `GetMessageHeaders`,
`GetMessage`, `ConfirmMessage`, paziņojumi sūtītājam, adrešu katalogs.

| Darbība | HTTP |
|---|---|
| SendMessage | `POST /UnifiedService/SendMessage` `{envelope, attachments[{contentId, contents}]}` |
| GetMessageServerConfirmation | `GET /UnifiedService/GetMessageServerConfirmation/{id}` |
| GetMessageHeaders | `GET /UnifiedService/GetMessageHeaders` |
| GetMessage | `GET /UnifiedService/GetMessage/{id}` |
| ConfirmMessage | `POST /UnifiedService/ConfirmMessage/{id}` `{NotifySender}` |
| Paziņojumi | `GET /UnifiedService/GetNotifications`, `POST /UnifiedService/ConfirmNotifications` |
| Adrešu katalogs | `GET /AddressLists/Search?q=` |

Aploksne: `http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0` `Envelope` —
`SenderDocument/DocumentMetadata` (`GeneralMetadata`, `PayloadReference/File` ar
`ContentReference`, SHA-256 un izmēru, `ExtendedMetadata`) un
`SenderTransportMetadata`. Serveris pievieno `ServerTransportMetadata`.

Pārbauda: sūtītāja e-adrese atbilst žetonam; adresāti ir katalogā; katram pielikumam
ir apraksts aploksnē ar pareizu kontrolsummu un izmēru; neaprakstītus pielikumus noraida.

**Atšķirības no DIV:** JSON pār HTTP (nevis SOAP), žetons (nevis sertifikāts un
WS-Security), aploksnes XAdES paraksts netiek pārbaudīts.

```
docker build -t div-emulator .
docker run -p 8700:8700 -v ./addresses.yaml:/etc/div/addresses.yaml:ro -v div-data:/data \
  -e DIV_TOKEN_A=... -e DIV_TOKEN_B=... div-emulator
```
