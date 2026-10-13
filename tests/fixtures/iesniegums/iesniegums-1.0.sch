<?xml version="1.0" encoding="UTF-8"?>
<!--
  iesniegums-1.0.sch
  Noteikumi starp laukiem. XSD nosaka, kas ir lauks; šeit — kam jābūt patiesam
  starp laukiem. To pašu noteikumu avotu izpilda veidlapa un DVS ievade, tāpēc
  veidlapā pieņemts iesniegums nevar tikt noraidīts DVS.

  Ziņojumi ir latviski, jo tos rāda iesniedzējam.
  queryBinding xslt (XPath 1.0), lai noteikumus var izpildīt arī bez XSLT 2.0 procesora.
-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt">

  <sch:ns prefix="i" uri="urn:lv:tiesibsargs:iesniegums:1.0"/>

  <sch:pattern id="P-persona">
    <sch:rule context="i:Iesniedzejs | i:ParstavamaPersona">
      <sch:assert id="P1" test="i:PusesTips != 'FiziskaPersona' or (normalize-space(i:Vards) and normalize-space(i:Uzvards))">
        Fiziskai personai jānorāda vārds un uzvārds.
      </sch:assert>
      <sch:assert id="P2" test="i:PusesTips != 'JuridiskaPersona' or (normalize-space(i:Nosaukums) and i:RegistracijasNr)">
        Juridiskai personai jānorāda nosaukums un reģistrācijas numurs.
      </sch:assert>
      <sch:assert id="P3" test="i:PusesTips != 'FiziskaPersona' or not(i:Nosaukums or i:RegistracijasNr)">
        Fiziskai personai nenorāda nosaukumu un reģistrācijas numuru.
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <sch:pattern id="A-atbilde">
    <sch:rule context="i:Iesniedzejs">
      <sch:assert id="A1" test="i:AtbildesVeids != 'EPasts' or i:Kontakti/i:Epasts">
        Lai atbildi saņemtu e-pastā, jānorāda e-pasta adrese.
      </sch:assert>
      <sch:assert id="A2" test="i:AtbildesVeids != 'EAdrese' or i:Kontakti/i:EAdrese">
        Lai atbildi saņemtu e-adresē, jānorāda e-adreses identifikators.
      </sch:assert>
      <sch:assert id="A3" test="i:AtbildesVeids != 'Pasts' or i:Kontakti/i:PastaAdrese">
        Lai atbildi saņemtu pa pastu, jānorāda pasta adrese.
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <sch:pattern id="R-parstavis">
    <sch:rule context="i:Parstavis">
      <sch:assert id="R1" test="i:Pamats != 'Cits' or i:PamatsApraksts">
        Ja pārstāvības pamats ir „Cits”, tas jāapraksta.
      </sch:assert>
      <sch:assert id="R2" test="i:Pamats != 'Pilnvara' or ../i:Pielikumi/i:Pielikums">
        Pārstāvot uz pilnvaras pamata, pilnvara jāpievieno pielikumā.
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <sch:pattern id="S-soli">
    <sch:rule context="i:IeprieksejieSoli">
      <sch:assert id="S1" test="i:VersiesIestade = 'false' or i:VersiesIestade = '0' or i:VersanasDatums">
        Ja esat vērsies iestādē, norādiet, kad.
      </sch:assert>
      <sch:assert id="S2" test="(i:VersiesIestade = 'true' or i:VersiesIestade = '1') or not(i:VersanasDatums or i:AtbildeSanemta or i:AtbildesKopsavilkums)">
        Atbildes ziņas norāda tikai tad, ja esat vērsies iestādē.
      </sch:assert>
      <sch:assert id="S3" test="not(i:AtbildesKopsavilkums) or i:AtbildeSanemta = 'true' or i:AtbildeSanemta = '1'">
        Atbildes kopsavilkumu norāda tikai tad, ja atbilde saņemta.
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- Vai Jautajums/Kods pastāv, ir izvēlams un pieder Jomai, pārbauda DVS ievade pret
       publicēto tēmu klasifikatoru (tiesibsargs/temu-klasifikators), ne šī datne:
       klasifikators mainās neatkarīgi no veidlapas. -->

</sch:schema>
