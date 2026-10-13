# Dokumentu ievade (ievades kanāli)

Kā dokuments nonāk DVS. Visi kanāli beidzas vienā vietā — `intake/service.py: ingest()` —
un pēc tam dokumentu apstrādā tie paši uzstādītie procesi neatkarīgi no kanāla.

## Kanāli

| Kanāls | `SanemsanasKanals` | Kā ienāk | Konfigurācija |
|---|---|---|---|
| Manuāla augšupielāde | `DVSLietotajs` | lietotājs DVS saskarnē izveido dokumentu un pievieno datni | vienmēr ieslēgts |
| E-pasts | `EPasts` | IMAP pastkastes aptauja; atbilde ar SMTP | `ievade.yaml`, `veids: epasts` |
| Tiešsaistes forma | `Portals` | publiska lapa `/iesniegt/<kanāls>` bez pieteikšanās | `ievade.yaml`, `veids: tiessaistes-forma` |

Konfigurācijas saskarnes nav — kanālus apraksta YAML datnē (`OPENDMS_INTAKE_CONFIG`,
noklusēti `/etc/opendms/ievade.yaml`). Datni pārlasa, kad tā mainās. Paroles datnē nav:
kanāls norāda vides mainīgā nosaukumu (`parole_env`).

## Plūsma

```
e-pasts / forma
 → sūtītājs atļauts? (e-pastam: atlautie_sutitaji; citādi — noraidīts, bez atbildes)
 → eDoc (.edoc/.asice) atvērts: parakstītās datnes + parakstu dati + integritātes pārbaude
 → dokuments izveidots ar neitrālu nosaukumu („Iesniegums (e-pasts)”)
      reģistrs izveidē saņem tikai šo nosaukumu; temats paliek DVS
 → DVS metadati: sūtītājs, saņemšanas laiks, kanāls, temats, eDoc parakstu dati
 → datnes pievienotas: parakstītais dokuments pirmais (to lasa procesi), tad citi
   pielikumi, tad oriģinālais eDoc konteiners (juridiskais oriģināls), tad ziņas teksts
 → notikums document.received → procesi:
      reģistrēšana (LV-DOK), klasificēšana, virzīšana, semantiskais apraksts,
      nodošana centrālajam reģistram
 → apstiprinājums sūtītājam, kad dokumentam ir LV-DOK un tas nodots reģistram
   (vai pēc `gaidit_s` ar to, kas ir)
```

Apstiprinājumā: reģistrācijas numurs, dokumenta identifikators (LV-DOK), saite uz
centrālā reģistra publisko izsekošanu (`/track/<kods>`; meklēt var arī pēc LV-DOK) un
eDoc parakstu kopsavilkums. Formai apstiprinājums tiek sūtīts caur norādīto e-pasta
kanālu, ja iesniedzējs norādīja e-pastu; lapa pati rāda statusu.

## eDoc

Tiek pārbaudīts: katra parakstā norādītā datne atbilst parakstā ierakstītajai
kontrolsummai; nolasīts parakstītājs, sertifikāta izdevējs, derīgums, parakstīšanas laiks.

**Netiek** pārbaudīts: paraksta kriptogrāfiskā vērtība, sertifikātu ķēde, atsaukšana,
laika zīmogs. Tam vajag kvalificētu validācijas pakalpojumu; līdz tam apstiprinājumā
rakstīts „Paraksta juridiskā derīguma pārbaude tiek veikta atsevišķi”.

## Drošība

- E-pasta kanālam — atļauto sūtītāju saraksts (testēšanā obligāts), lai pastkaste
  nekļūtu par atvērtu ieeju MI apstrādei un automātiskām atbildēm citiem.
- Formai — ierobežojums 5 iesniegumi / 10 min no adreses, slēpts lauks pret robotiem,
  izmēra ierobežojums.
- Dublikāti (tas pats `Message-ID` / formas kods) netiek reģistrēti atkārtoti.
- Neizdevusies ziņa paliek nelasīta un tiek mēģināta nākamajā aptaujā.
- Personas dati (sūtītājs, temats) paliek DVS; centrālajam reģistram — tikai centrālā projekcija.

## Piemērs `ievade.yaml`

```yaml
registrs_publiskais_url: https://dokregistrs.example.lv
kanali:
  - id: epasts
    veids: epasts
    ieslegts: true
    imap: {host: mail.example.lv, port: 993, ssl: true, lietotajs: iesniegumi@example.lv, mape: INBOX}
    smtp: {host: mail.example.lv, port: 587, starttls: true, no_adreses: iesniegumi@example.lv}
    parole_env: OPENDMS_INTAKE_EMAIL_PASSWORD
    intervals_s: 60
    atlautie_sutitaji: ["*@example.lv"]
    apstiprinajums: {ieslegts: true, gaidit_s: 900}
  - id: forma
    veids: tiessaistes-forma
    ieslegts: true
    nosaukums: Iesniegums
    max_mb: 20
    apstiprinajums: {kanals: epasts}
```

## API

| Metode | Ceļš | Piekļuve |
|---|---|---|
| GET | `/api/ievade/kanali` | operators — kanāli (bez parolēm) un skaitītāji |
| GET | `/api/ievade/ieraksti` | operators — saņemtie ieraksti |
| POST | `/api/ievade/kanali/{id}/parbaudit` | administrators — aptaujāt pastkasti tūlīt |
| GET/POST | `/api/ievade/forma/{id}` | publisks — formas apraksts / iesniegšana |
| GET | `/api/ievade/statuss/{kods}` | publisks — formas iesnieguma statuss (bez personas datiem) |
