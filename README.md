# SolarEdge Monitoring API v2 (OAuth) voor Home Assistant

Onofficiële integratie voor de nieuwe SolarEdge Monitoring API v2 met OAuth 2.0 *Site Access*.
De oude V1-API met site-API-key is per 3 november 2026 uitgefaseerd. Niet gelieerd aan SolarEdge.

**📘 Volledige installatiegids: [docs/INSTALLATIE.md](docs/INSTALLATIE.md)**

## Wat zit erin

| Bestand | Doel |
|---|---|
| `custom_components/solaredge_v2/` | de integratie |
| `docs/INSTALLATIE.md` | stap-voor-stap installatiegids, credits, problemen oplossen |
| `web/solaredge-callback.html` | relay-pagina die je op je eigen HTTPS-domein zet |
| `tools/probe.py` | los testscript om endpoints en parameters tegen de echte API te controleren |
| `tests/` | tests (parser, volledige config flow met callback, sensoren) |

## Waarom een relay-pagina

SolarEdge accepteert als redirect alleen **HTTPS met hostnaam** (geen `http://` of IP) en stuurt geen `state` mee.
Home Assistant draait meestal op een `http://`-adres in je eigen netwerk. Daarom:

1. SolarEdge stuurt je browser naar `https://example.com/solaredge-callback.html?code=…&site_id=…` (jouw domein).
2. Die statische pagina stuurt dezelfde browser door naar `http://<jouw-home-assistant>:8123/api/solaredge_v2/callback?…`
   Dat werkt alleen vanaf een apparaat op je thuisnetwerk. Home Assistant hoeft niet vanaf internet bereikbaar te zijn.
3. De integratie heeft een eigen callback-view, koppelt de redirect aan de lopende setup via `external_id` en gebruikt PKCE.

De eenmalige code verschijnt in de logs van je webserver. Hij is kortlevend en onbruikbaar zonder je client secret en de PKCE-verifier.

## Installatie

### 1. Relay-pagina

Zet `web/solaredge-callback.html` op je eigen HTTPS-domein, bijvoorbeeld `https://example.com/solaredge-callback.html`.
Pas bovenin `HA_BASE` aan naar het adres waarop jij Home Assistant opent (zonder slash aan het eind).

### 2. Integratie installeren

**Via de Marketplace** (Home Assistant 2026.11 en nieuwer, voorheen HACS): zodra de repository op GitHub staat,
ga je naar **Instellingen → Marketplace → Add from link**, vul de URL van de repository in en installeer de integratie.
Voor de Marketplace is een GitHub-koppeling via device sign-in nodig. Oudere Home Assistant-versies gebruiken HACS:
**Custom repositories → Integration**.

**Handmatig:** kopieer de map `custom_components/solaredge_v2` naar `/config/custom_components/` en herstart Home Assistant.

### 3. SolarEdge developer-app

Log in op https://developer.solaredge.com met het **mySolarEdge-huiseigenaar**-account (geen installateursaccount) en maak een app:

- Service: **Monitoring API**, Access type: **Site Access**
- **Origin URL:** `https://example.com`
- **Redirect URI** en **Returned URL:** `https://example.com/solaredge-callback.html`
- **Scopes:** `SITE_DATA` en `DEVICE_DATA`
- Bewaar Client ID en Client Secret (het secret zie je maar één keer).

### 4. Integratie toevoegen

**Instellingen → Apparaten & services → Integratie toevoegen → SolarEdge Monitoring API v2.**
Vul Client ID en secret in, vervang de voorbeeld-Redirect URI door jouw relay-adres, kies **Automatisch inloggen** en keur de toegang goed.
Lukt de doorstuurstap niet, kies **Handmatig inloggen** en plak het adres van de tab na het goedkeuren.

Het refresh-token wordt door SolarEdge bij elk gebruik vervangen; de integratie slaat het nieuwe token direct op.
Gebruik hetzelfde token dus niet tegelijk in `probe.py` of een tweede integratie.

## Entiteiten

Per waarde in de V2-respons een sensor, met nette namen voor de belangrijkste:

| Entiteit | Bron | Opmerking |
|---|---|---|
| **Solar power** | `/power` | nieuwste *gevulde* kwartier (SolarEdge loopt 15-30 min achter; de tijd staat in attribuut `data_timestamp`) |
| Production today | `/overview?from=<vandaag 00:00>&to=nu` | Wh |
| Energy this month / this year | `/energy?resolution=MONTH` | Wh |
| Lifetime energy | `/lifetime-energy` | onboard teller |
| Omvormer: AC power, energy, voltage, current, frequency, consumed AC | `/inverters/telemetry` | eigen apparaat per omvormer |
| Batterij / meter | `/storage/...`, `/meters/...` | alleen als de inventaris (`/devices`) ze meldt |
| Open alerts, peak power, last update, apparaatgegevens | `/alerts`, `/sites/{id}`, `/devices` | veel tekstvelden staan standaard uit |

## Credits en poll-schema

Elke call kost 1 credit; gratis tier = 2.000 per maand en 10 per minuut. SolarEdge heeft zelf maar elke 15 minuten nieuwe data, dus vaker pollen heeft geen zin.

* **Live vermogen** (`/power`) wordt overdag gepolld; **productie vandaag** elke 2x dat interval; **omvormer-telemetrie** elke 4x.
* **Overdag** = zon boven de horizon (entiteit `sun.sun`) + 45 minuten erna. 's Nachts wordt niets opgehaald (optie *Alleen overdag pollen*).
* **Langzame data** (site, energie maand/jaar, lifetime, alerts) elke 12 uur, apparaten elke 24 uur.
* Interval 0 = **automatisch**, berekend uit het budget (standaard 1.800 per cyclus). Bij de standaardinstellingen ongeveer elke 25 minuten.
* Een endpoint dat 4xx geeft wordt tijdelijk overgeslagen, met de SolarEdge-melding in het log.
* Waarden worden bewaard, dus een herstart kost geen credits.

## Realtime?

De cloud-API werkt per kwartier. Voor live vermogen kun je lokaal Modbus TCP gebruiken (alleen via LAN, niet via wifi, volgens de
SolarEdge SunSpec-technote) met bijvoorbeeld de community-integratie *SolarEdge Modbus Multi*.

## Belangrijk om te weten

* Onofficieel project, getest op één woninginstallatie zonder batterij of meter.
* Het formaat van `/lifetime-energy`, `/alerts` en de meter/batterij-responses is nog niet met echte data van meerdere installaties gezien; de sensoren verschijnen automatisch zodra er waarden zijn.
* Optimizer-data en live power-flow vallen onder SolarEdge Advanced Monitoring en zitten niet in de gratis tier.
* Nog geen backfill naar uurstatistieken.
* `tools/probe.py` laat precies zien wat SolarEdge teruggeeft.


## Tests

```
pip install pytest-homeassistant-custom-component
pytest            # in de projectmap
```
