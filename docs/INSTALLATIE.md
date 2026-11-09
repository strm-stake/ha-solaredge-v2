# Installatiegids: SolarEdge Monitoring API v2 voor Home Assistant

🇬🇧 [English version](INSTALLATION.md)

Met deze integratie lees je je SolarEdge-installatie in Home Assistant uit via de nieuwe Monitoring API v2 (OAuth 2.0).
Je hebt ongeveer 30 minuten nodig en doorloopt vier stappen. De oude V1-API met site-sleutel is per 3 november 2026 uitgefaseerd.

## Voordat je begint

Je hebt vijf dingen nodig. Het eerste punt is het meest onderschat: SolarEdge accepteert alleen een HTTPS-adres met een domeinnaam als redirect, dus je hebt ergens een eigen webruimte nodig.

| Wat | Details |
| --- | --- |
| Home Assistant | Een recente versie (OS, Container of Core), bereikbaar op je thuisnetwerk. Je moet kunnen bij de map `/config` |
| SolarEdge-account | Het mySolarEdge-account van de **huiseigenaar**. Een installateursaccount kan geen Site Access geven |
| Developer-portal | Toegang tot developer.solaredge.com met datzelfde account |
| Eigen HTTPS-domein | Eén statische pagina op een domein dat jij beheert, bijvoorbeeld je eigen website, GitHub Pages of Netlify |
| Apparaat op het thuisnetwerk | Je doet de koppeling vanaf een computer of telefoon in hetzelfde netwerk als Home Assistant |

## Hoe het werkt

SolarEdge stuurt je na het inloggen terug naar een HTTPS-adres, maar Home Assistant draait meestal op een `http://`-adres in je eigen netwerk. Een kleine relay-pagina op jouw domein overbrugt dat.

1. Je start de installatie in Home Assistant en klikt op **Automatisch inloggen**.
2. Er opent een SolarEdge-tabblad. Je logt in en keurt de toegang goed.
3. SolarEdge stuurt je browser naar jouw relay-pagina, met een eenmalige `code` in het adres.
4. De relay-pagina stuurt dezelfde browser meteen door naar Home Assistant op je thuisnetwerk. Daarom moet je vanaf een apparaat in dat netwerk werken.
5. De integratie wisselt de code in voor tokens (met PKCE), haalt je sitegegevens op en maakt de koppeling aan.

Home Assistant hoeft dus niet vanaf internet bereikbaar te zijn. De relay-pagina bewaart niets en bevat alleen een paar regels JavaScript.

## Stap 1: de relay-pagina plaatsen

Neem het bestand [`web/solaredge-callback.html`](../web/solaredge-callback.html) uit deze repository en zet het op je eigen domein, bijvoorbeeld op `https://jouwdomein.nl/solaredge-callback.html`.
Pas alleen de regel `HA_BASE` aan naar het adres waarop jij Home Assistant opent, zonder slash aan het eind (bijvoorbeeld `http://192.168.1.50:8123`).
Dat adres moet bereikbaar zijn vanuit de browser waarmee je inlogt.

Controleer daarna in je browser of `https://jouwdomein.nl/solaredge-callback.html` laadt. Je ziet dan de melding dat de pagina door SolarEdge wordt aangeroepen.
Noteer dit adres, je hebt het nodig bij stap 3 en 4. Het moet in beide stappen exact hetzelfde zijn.

## Stap 2: de integratie installeren

Je kunt de integratie op twee manieren installeren: via de Marketplace van Home Assistant (de repository staat op GitHub), of handmatig.

**Via de Marketplace** (Home Assistant 2026.11 en nieuwer, de opvolger van HACS):

1. Open **Instellingen → Marketplace** en accepteer de waarschuwing over community-projecten.
2. Kies **Add from link** en vul de URL van deze GitHub-repository in. Je koppelt GitHub daarvoor eenmalig via device sign-in, zonder wachtwoord in Home Assistant.
3. Installeer **SolarEdge Monitoring API v2**. Installeren kan zonder herstart, updates vragen wel een herstart.

Op een oudere Home Assistant-versie gebruik je HACS: **Custom repositories**, type *Integration*.

**Handmatig:** kopieer de map `custom_components/solaredge_v2` uit deze repository naar de map `custom_components` in je Home Assistant-configuratie. De map moet er zo uitzien:

```text
/config/
└── custom_components/
    └── solaredge_v2/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── diagnostics.py
        ├── http_view.py
        ├── manifest.json
        ├── parse.py
        ├── sensor.py
        └── translations/
```

Maak de map `custom_components` aan als die nog niet bestaat. Je kunt de bestanden op een van deze manieren op hun plek zetten:

- **Samba share** (add-on *Samba share*): sleep de map naar de netwerkshare `config`.
- **File editor** of **Studio Code Server** (add-ons): maak de map en bestanden aan in de browser.
- **SSH** (add-on *Terminal & SSH*): kopieer met `scp` of `cp`.

Herstart daarna via **Instellingen → Systeem → Herstarten**. Zonder herstart kent Home Assistant de integratie nog niet en verschijnt *SolarEdge Monitoring API v2* niet in de lijst bij stap 4.

## Stap 3: de SolarEdge developer-app aanmaken

Log in op developer.solaredge.com met het account van de huiseigenaar en maak een nieuwe app aan. Gebruik onderstaande waarden. De menunamen in de portal kunnen iets afwijken, de veldnamen blijven gelijk.

| Veld | Waarde |
| --- | --- |
| Service | Monitoring API |
| Access type | **Site Access** |
| Origin URL | `https://jouwdomein.nl` (alleen het domein, zonder pad) |
| Redirect URI | `https://jouwdomein.nl/solaredge-callback.html` |
| Returned URL | Exact hetzelfde adres als de Redirect URI |
| Scopes | `SITE_DATA` en `DEVICE_DATA` |

Bewaar na het aanmaken de **Client ID** en de **Client Secret**. Het secret zie je maar één keer. Raak je het kwijt, dan maak je een nieuw secret of een nieuwe app aan.

De Redirect URI en de Returned URL moeten tot op het teken gelijk zijn aan het adres dat je in stap 4 invult. Een verschil van een slash of een hoofdletter geeft een foutmelding bij het inloggen.

## Stap 4: toevoegen en inloggen

Werk vanaf een apparaat in hetzelfde netwerk als Home Assistant.

1. Ga naar **Instellingen → Apparaten & services → Integratie toevoegen** en kies **SolarEdge Monitoring API v2**.
2. Vul de **Client ID** en het **Client secret** in uit stap 3.
3. Vul bij **Redirect URI** je relay-adres in (het veld bevat een voorbeeldadres dat je moet vervangen), bijvoorbeeld `https://jouwdomein.nl/solaredge-callback.html`.
4. Laat **Extra authorize-parameters** op de standaardwaarde `scope=SITE_DATA DEVICE_DATA` staan en verstuur het formulier.
5. Kies **Automatisch inloggen**. Er opent een SolarEdge-tabblad.
6. Log in met het huiseigenaaraccount en keur de toegang goed voor je site.
7. Je wordt via je relay-pagina teruggestuurd naar Home Assistant. Het tabblad meldt dat de koppeling klaar is. Sluit het tabblad en ga terug naar Home Assistant.

Het resultaat is een integratie met de naam *SolarEdge* gevolgd door de naam van je site. De eerste waarden verschijnen binnen enkele minuten.

Werkt de doorstuurstap niet, bijvoorbeeld omdat je niet op het thuisnetwerk zit? Kies dan **Handmatig inloggen**: kopieer na het goedkeuren het volledige adres van het tabblad (het bevat `code=`) en plak het in het veld in Home Assistant. Automatisch inloggen is de aanbevolen route, handmatig is alleen een noodoplossing.

## Wat je krijgt

De integratie maakt per waarde in de API-respons een sensor aan. Veel tekstvelden (zoals firmwareversies) staan standaard uit; die zet je zelf aan als je ze wilt zien. De belangrijkste sensoren:

| Sensor | Bron | Opmerking |
| --- | --- | --- |
| Solar power | `/power` | Laatste gevulde kwartier in W. SolarEdge loopt 15 tot 30 minuten achter. De tijd staat in het attribuut `data_timestamp` |
| Production today | `/overview` | Wh sinds middernacht |
| Energy this month / this year | `/energy` | Maand- en jaartotaal in Wh |
| Lifetime energy | `/lifetime-energy` | Teller van de omvormer |
| Omvormer: AC power, energy, voltage, current, frequency | `/inverters/telemetry` | Eigen apparaat per omvormer. Alleen met telemetrie aan |
| Batterij en meter | `/storage`, `/meters` | Alleen als de inventaris (`/devices`) ze meldt |
| Open alerts, peak power, last update | `/alerts`, `/sites/{id}` | Sitegegevens en meldingen |
| Credits (gebruikt en resterend) | Interne teller | Per factuurperiode |

De waarden zijn niet realtime. De API werkt per kwartier. Zie het kopje over realtime als je live data nodig hebt.

## Credits en polling

Elke API-aanroep kost één credit. De gratis tier geeft 2.000 credits per maand en maximaal 10 aanroepen per minuut. SolarEdge heeft zelf maar elke 15 minuten nieuwe data, dus vaker pollen dan elke 15 minuten levert niets op. De integratie rekent het interval daarom automatisch uit je budget uit. Bij de standaardinstellingen is dat ongeveer elke 25 minuten overdag.

Open **Instellingen → Apparaten & services → SolarEdge Monitoring API v2 → Configureren** om dit aan te passen:

| Optie | Standaard | Effect |
| --- | --- | --- |
| Telemetrie van omvormer, meter en batterij lezen | Aan | Haalt per omvormer vermogen, spanning en stroom op. Zet uit om credits te sparen |
| Minuten tussen vermogensupdates | 0 (automatisch) | 0 laat de integratie het interval kiezen. Het minimum is 15 minuten |
| Credits per factuurperiode | 1.800 | Je budget, met marge onder de 2.000 |
| Dag waarop de credits resetten | 1 | De dag waarop jouw factuurperiode begint |
| Alleen overdag pollen | Aan | Zon boven de horizon plus 45 minuten. Bespaart ongeveer de helft van de credits |

De overige gegevens gaan veel zuiniger: sitegegevens, maand- en jaartotaal, lifetime-energie en alerts elke 12 uur, apparatenlijst elke 24 uur. Een aanroep die steeds een fout geeft (4xx) wordt tijdelijk overgeslagen en de SolarEdge-melding komt in het logboek. De waarden worden bewaard, dus een herstart van Home Assistant kost geen credits.

## Realtime nodig?

Via de cloud-API kom je niet onder het kwartier. Wil je het actuele vermogen per seconde, gebruik dan **Modbus TCP** lokaal op je omvormer, zonder credits, naast deze integratie.
De community-integratie [SolarEdge Modbus Multi](https://github.com/WillCodeForCats/solaredge-modbus-multi/wiki/Configuration) doet dat voor Home Assistant.

Let op, volgens de [SunSpec-technote van SolarEdge](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf) werkt Modbus TCP alleen via een **LAN-kabel**, niet via wifi.
Het staat standaard uit en je zet het aan in het menu van de omvormer of in SetApp, vaak met installateursrechten. Er is maar één Modbus-verbinding tegelijk toegestaan.

## Problemen oplossen

| Wat je ziet | Meest waarschijnlijke oorzaak | Oplossing |
| --- | --- | --- |
| *Invalid redirect_uri* of autorisatie geweigerd | De Redirect URI, de Returned URL en het veld in Home Assistant zijn niet exact gelijk | Maak alle drie identiek, ook qua slash en hoofdletters. De melding van SolarEdge staat letterlijk in de foutmelding |
| Pagina niet gevonden (404) op `/api/solaredge_v2/callback` of *Setup could not continue* | Home Assistant is na het kopiëren niet herstart, of je koos Handmatig inloggen en de browser kwam toch bij de callback | Herstart Home Assistant en begin opnieuw met Automatisch inloggen |
| Na het goedkeuren gebeurt er niets in Home Assistant | Je zit niet op het thuisnetwerk, of `HA_BASE` in de relay-pagina klopt niet | Controleer `HA_BASE`. Gebruik anders Handmatig inloggen en plak het volledige adres met `code=` |
| Je ziet geen site of krijgt geen toegang | Je gebruikt een installateursaccount | Log in met het account van de huiseigenaar. Site Access werkt alleen daarmee |
| De waarde loopt een kwartier of langer achter | SolarEdge levert per kwartier met 15 tot 30 minuten vertraging | Dit is normaal. Gebruik lokaal Modbus voor live data |
| Veel sensoren staan uitgeschakeld | Tekstvelden en details staan standaard uit | Zet ze aan via de entiteitsinstellingen van de sensor |
| *SolarEdge API-limiet bereikt* | Je credits of de limiet van 10 aanroepen per minuut zijn op | Zet telemetrie uit en laat Alleen overdag pollen aan. Wacht tot de factuurperiode reset |
| Home Assistant vraagt opnieuw in te loggen | Het token is verlopen of ingetrokken | Volg de melding en doorloop stap 4 opnieuw. Gebruik hetzelfde token niet gelijktijdig in een ander hulpmiddel, want SolarEdge vervangt het bij elk gebruik |

Wil je meer zien? Open **Instellingen → Systeem → Logboeken** en filter op `solaredge_v2`. Op de integratiepagina kun je ook **Diagnostiek downloaden**.
Die export bevat geen client ID, secret, tokens of site ID en is geschikt om bij een vraag te voegen.

## Privacy, updaten en verwijderen

- **Waar blijven je gegevens?** De integratie praat alleen met SolarEdge (`monitoringapi.solaredge.com` en `connect.solaredge.com`). Client secret en tokens staan in de configuratie van je eigen Home Assistant.
- **De relay-pagina.** Ze bewaart niets en stuurt geen referrer mee. De eenmalige code verschijnt wel in het toegangslogboek van je webhost. Die code is kortlevend en onbruikbaar zonder je client secret.
- **Updaten.** Vervang de map `solaredge_v2` door de nieuwe versie en herstart Home Assistant (of update via de Marketplace). Je instellingen blijven behouden.
- **Verwijderen.** Verwijder de integratie onder *Apparaten & services*, daarna de map `solaredge_v2` en tot slot de app in de developer-portal van SolarEdge, zodat het token niet meer geldig is.

## Beperkingen en status

Dit is een onofficieel community-project en niet gelieerd aan SolarEdge. Het is gebouwd en getest op één woninginstallatie met één omvormer, zonder batterij of meter.

- De antwoordformaten van lifetime-energie, alerts, meters en batterijen zijn gebaseerd op de SolarEdge-documentatie en nog niet met echte data van meerdere installaties gecontroleerd. De sensoren verschijnen automatisch zodra er waarden zijn.
- Gegevens per optimizer en live power-flow vallen onder SolarEdge Advanced Monitoring en zitten niet in de gratis tier.
- De integratie vult de langetermijnstatistieken van Home Assistant niet achteraf aan.
- SolarEdge kan de V2-API wijzigen. Controleer na een update van SolarEdge of de sensoren nog waarden geven en meld afwijkingen met de diagnostiekexport.
