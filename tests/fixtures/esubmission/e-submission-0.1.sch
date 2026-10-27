<?xml version="1.0" encoding="UTF-8"?>
<!--
  e-submission 0.1 — noteikumu slānis (ISO Schematron), profils lv.tiesibsargs.

  Divi līmeņi:
    E-…  kļūda (role="error")  — instance nav lietojama: salauztas atsauces, pretrunīgi lauki,
                                 veidlapas obligātie lauki. Neder reģistrēšanai.
    W-…  brīdinājums (role="warning") — juridisks nepilnīgums. Iesniegumu pieņem (APL 56. p. 4. d.);
                                 brīdinājuma ID izmanto izvērtēšanas solis lēmumam (atstāt bez izskatīšanas,
                                 lūgt precizēt, prasīt parakstu, pārsūtīt).
  Katram noteikumam norādīts avots.
-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt">
  <sch:title>e-submission 0.1 — lv.tiesibsargs</sch:title>
  <sch:ns prefix="es" uri="urn:uas:esubmission:0.1"/>

  <!-- ======================= Uzbūve un atsauces ======================= -->
  <sch:pattern id="kodols">
    <sch:rule context="es:eSubmission">
      <sch:assert id="E-001" role="error" test="@profile = 'lv.tiesibsargs'">E-001: profils jābūt 'lv.tiesibsargs'.</sch:assert>
      <sch:assert id="E-002" role="error" test="count(es:parties/es:party[es:role = 'submitter']) &gt;= 1">E-002: jābūt vismaz vienam iesniedzējam (role submitter).</sch:assert>
    </sch:rule>
    <sch:rule context="es:party">
      <sch:assert id="E-003" role="error" test="count(//es:party[es:id = current()/es:id]) = 1">E-003: personas id "<sch:value-of select="es:id"/>" nav unikāls.</sch:assert>
      <sch:assert id="E-004" role="error" test="not(es:partyType = 'naturalPerson' and (es:legalName or es:registrationNo or es:code))">E-004: fiziskai personai nav nosaukuma, reģistrācijas numura vai iestādes koda.</sch:assert>
    </sch:rule>
    <sch:rule context="es:fact">
      <sch:assert id="E-005" role="error" test="count(//es:fact[es:id = current()/es:id]) = 1">E-005: fakta id "<sch:value-of select="es:id"/>" nav unikāls.</sch:assert>
    </sch:rule>
    <sch:rule context="es:claim">
      <sch:assert id="E-006" role="error" test="count(//es:claim[es:id = current()/es:id]) = 1">E-006: prasījuma id "<sch:value-of select="es:id"/>" nav unikāls.</sch:assert>
    </sch:rule>
    <sch:rule context="es:attachment">
      <sch:assert id="E-007" role="error" test="count(//es:attachment[es:id = current()/es:id]) = 1">E-007: pielikuma id "<sch:value-of select="es:id"/>" nav unikāls.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <sch:pattern id="atsauces">
    <sch:rule context="es:actor | es:addressedTo | es:signer | es:represents">
      <sch:assert id="E-010" role="error" test="//es:party[es:id = current()]">E-010: atsauce "<sch:value-of select="."/>" (<sch:value-of select="local-name()"/>) neatbilst nevienai personai.</sch:assert>
    </sch:rule>
    <sch:rule context="es:evidence">
      <sch:assert id="E-011" role="error" test="//es:attachment[es:id = current()]">E-011: pierādījums "<sch:value-of select="."/>" neatbilst nevienam pielikumam.</sch:assert>
    </sch:rule>
    <sch:rule context="es:relatedFact">
      <sch:assert id="E-012" role="error" test="//es:fact[es:id = current()]">E-012: prasījuma saistītais fakts "<sch:value-of select="."/>" nav atrasts.</sch:assert>
    </sch:rule>
    <sch:rule context="es:fact">
      <sch:assert id="E-013" role="error" test="not(es:basis = 'documented') or es:evidence">E-013: fakts "<sch:value-of select="es:id"/>" atzīmēts kā pierādīts, bet nav pierādījuma.</sch:assert>
    </sch:rule>
    <sch:rule context="es:when/es:period">
      <sch:assert id="E-014" role="error" test="not(es:to) or number(translate(es:to,'-','')) &gt;= number(translate(es:from,'-',''))">E-014: perioda beigas ir pirms sākuma.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ====================== Strukturējums un statuss ====================== -->
  <sch:pattern id="strukturejums">
    <sch:rule context="es:eSubmission[es:provenance/es:structuring/es:method = 'ai']">
      <sch:assert id="E-020" role="error" test="not(es:identity/es:status = 'reviewed' or es:identity/es:status = 'registered') or es:provenance/es:structuring/es:reviewedBy">E-020: MI strukturētu iesniegumu nevar atzīmēt kā pārskatītu bez pārskatītāja (reviewedBy).</sch:assert>
      <sch:assert id="W-021" role="warning" test="not(es:facts/es:fact[not(es:sourceExcerpt)])">W-021: MI iegūtajiem faktiem ieteicams avota fragments (sourceExcerpt) pārbaudāmībai.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ========================= Tiešsaistes veidlapa ========================= -->
  <sch:pattern id="veidlapa">
    <sch:rule context="es:eSubmission[es:identity/es:channel = 'portal']">
      <sch:assert id="E-030" role="error" test="es:declarations">E-030: veidlapas iesniegumam jābūt apliecinājumiem (declarations).</sch:assert>
      <sch:assert id="E-031" role="error" test="es:narrative and es:claims and es:priorSteps">E-031: veidlapā obligāti izklāsts, prasījums un iepriekšējie soļi.</sch:assert>
      <sch:assert id="E-032" role="error" test="es:privacy/es:replyChannel">E-032: veidlapā jānorāda, kā saņemt atbildi.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ============= Iesniedzējs (Iesniegumu likums 3. p. 2. d., 7. p. 1. d. 1. p.) ============= -->
  <sch:pattern id="iesniedzejs">
    <sch:rule context="es:party[es:role = 'submitter' or es:role = 'coSubmitter']">
      <sch:assert id="W-101" role="warning" test="not(es:partyType = 'naturalPerson') or (normalize-space(es:givenName) and normalize-space(es:familyName))">W-101: iesniedzējam nav norādīts vārds un uzvārds (Iesniegumu likums 3. p. 2. d.; 7. p. 1. d. 1. p.).</sch:assert>
      <sch:assert id="W-102" role="warning" test="not(es:partyType = 'legalPerson') or normalize-space(es:legalName)">W-102: juridiskās personas iesniedzējam nav nosaukuma (Iesniegumu likums 3. p. 2. d.).</sch:assert>
      <sch:assert id="W-103" role="warning" test="normalize-space(es:address)">W-103: iesniedzējam nav adreses (Iesniegumu likums 3. p. 2. d.; 7. p. 1. d. 1. p.).</sch:assert>
      <sch:assert id="W-104" role="warning" test="not(es:partyType = 'legalPerson') or es:registrationNo">W-104: juridiskajai personai nav reģistrācijas numura (APL 56. p. 1. d.).</sch:assert>
      <sch:assert id="W-105" role="warning" test="es:partyType != 'unknown'">W-105: iesniedzējs nav identificējams — anonīms iesniegums (Pārbaudes lietu reglaments 24. p.).</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- =========== Paraksts (Iesniegumu likums 2. p. 3.–4. d., 7. p. 1. d. 2. p.; Reglaments 10.–12. p.) =========== -->
  <sch:pattern id="paraksts">
    <sch:rule context="es:identity/es:signature">
      <sch:assert id="W-110" role="warning" test="es:method != 'none'">W-110: iesniegums nav parakstīts (Iesniegumu likums 7. p. 1. d. 2. p.). Elektroniskam — Pārbaudes lietu reglaments 10.–12. p.: ja redzams iespējams pārkāpums, 5 darbdienās lūgt parakstītu iesniegumu.</sch:assert>
      <sch:assert id="W-111" role="warning" test="not(../es:channel = 'email' or ../es:channel = 'portal') or es:method = 'qualifiedESignature' or es:method = 'latvijaLvIdentified'">W-111: elektroniskais iesniegums bez elektroniskā paraksta vai latvija.lv identitātes pārbaudes (Iesniegumu likums 2. p. 3.–4. d.).</sch:assert>
      <sch:assert id="W-112" role="warning" test="not(../es:channel = 'oral') or es:method = 'oralRecorded'">W-112: mutvārdu iesniegums jānoformē rakstveidā un jāparaksta (Iesniegumu likums 3. p. 3. d.; Reglaments 9. p.).</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ============ Pārstāvība (APL 56. p. 1.¹ d.; Pārbaudes lietu reglaments 6. p.) ============ -->
  <sch:pattern id="parstaviba">
    <sch:rule context="es:party[es:role = 'representative']">
      <sch:assert id="W-120" role="warning" test="es:representation">W-120: pārstāvim nav norādīts, kuru personu un uz kāda pamata viņš pārstāv.</sch:assert>
    </sch:rule>
    <sch:rule context="es:representation">
      <sch:assert id="W-121" role="warning" test="not(es:basis = 'authorisation') or es:evidence">W-121: pilnvarojums nav pievienots (APL 56. p. 1.¹ d.).</sch:assert>
      <sch:assert id="W-122" role="warning" test="es:basis != 'none'">W-122: iesniegums citas personas interesēs bez pilnvarojuma — konsultants sazinās ar personu, kuras tiesības skartas (Pārbaudes lietu reglaments 6. p.).</sch:assert>
      <sch:assert id="E-123" role="error" test="not(es:basis = 'other') or es:description">E-123: pamatam 'other' nepieciešams apraksts.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ==================== Saturs (Iesniegumu likums 7. p. 1. d. 4. p.; APL 56. p.) ==================== -->
  <sch:pattern id="saturs">
    <sch:rule context="es:eSubmission">
      <sch:assert id="W-130" role="warning" test="es:claims/es:claim">W-130: nav prasījuma — nav skaidrs, ko persona lūdz (APL 56. p. 1. d.; Iesniegumu likums 7. p. 1. d. 4. p.).</sch:assert>
      <sch:assert id="W-131" role="warning" test="es:facts/es:fact">W-131: nav norādīti apstākļi vai fakti (Iesniegumu likums 3. p. 4. d.).</sch:assert>
      <sch:assert id="W-132" role="warning" test="es:parties/es:party[es:role = 'respondent']">W-132: nav norādīta iestāde vai persona, kuras rīcība ir iesnieguma priekšmets (Tiesībsarga likums 12. p.; Reglaments 23. p.).</sch:assert>
      <sch:assert id="W-133" role="warning" test="es:rightsAffected">W-133: nav norādīta tiesību joma — jāklasificē (tēmu klasifikators).</sch:assert>
    </sch:rule>
    <sch:rule context="es:claim[es:type = 'investigate' or es:type = 'opinion' or es:type = 'remedy']">
      <sch:assert id="W-134" role="warning" test="es:relatedFact">W-134: prasījums "<sch:value-of select="es:id"/>" nav sasaistīts ar faktiem.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ============ Iepriekšējie soļi un tiesa (Pārbaudes lietu reglaments 24. p.) ============ -->
  <sch:pattern id="ieprieksejie-soli">
    <sch:rule context="es:priorSteps">
      <sch:assert id="W-140" role="warning" test="es:step">W-140: nav ziņu, ka persona vērsusies iestādē vai izmantojusi vispārējos tiesību aizsardzības līdzekļus (Reglaments 24. p.).</sch:assert>
      <sch:assert id="W-141" role="warning" test="es:court/es:status != 'pending'">W-141: jautājums tiek izskatīts tiesā (Reglaments 24. p.; Tiesībsarga likums 24. p. 3. d.).</sch:assert>
      <sch:assert id="W-142" role="warning" test="es:court/es:status != 'decided'">W-142: par jautājumu ir tiesas nolēmums (Reglaments 24. p.).</sch:assert>
    </sch:rule>
    <sch:rule context="es:priorSteps/es:step">
      <sch:assert id="E-143" role="error" test="not(es:responseSummary or es:responseDate) or es:responseReceived = 'true' or es:responseReceived = '1'">E-143: atbildes datums vai kopsavilkums norādīts, bet atbilde atzīmēta kā nesaņemta.</sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ===================== Atbilde un atklātība (Iesniegumu likums 5., 9. p.) ===================== -->
  <sch:pattern id="atbilde">
    <sch:rule context="es:privacy/es:replyChannel">
      <sch:assert id="W-150" role="warning" test=". != 'email' or //es:party[es:role = 'submitter'][1]/es:contact/es:email">W-150: atbilde pa e-pastu, bet iesniedzējam nav e-pasta.</sch:assert>
      <sch:assert id="W-151" role="warning" test=". != 'eAddress' or //es:party[es:role = 'submitter'][1]/es:contact/es:eAddress">W-151: atbilde e-adresē, bet iesniedzējam nav e-adreses konta.</sch:assert>
      <sch:assert id="W-152" role="warning" test=". != 'post' or //es:party[es:role = 'submitter'][1]/es:address">W-152: atbilde pa pastu, bet iesniedzējam nav adreses.</sch:assert>
    </sch:rule>
    <sch:rule context="es:privacy[es:doNotDiscloseIdentity = 'true' or es:doNotDiscloseIdentity = '1']">
      <sch:report id="W-153" role="warning" test="true()">W-153: iesniedzējs lūdz neizpaust identitāti — iestādei sūtāmajos dokumentos personas datus neiekļaut (Iesniegumu likums 9. p. 1. d.; Tiesībsarga likums 23. p. 6. d.).</sch:report>
    </sch:rule>
  </sch:pattern>
</sch:schema>
