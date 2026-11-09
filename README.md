# SolarEdge Monitoring API v2 (OAuth) for Home Assistant

🇳🇱 [Nederlandse versie](README.nl.md)

Unofficial integration for the new SolarEdge Monitoring API v2 using OAuth 2.0 *Site Access*.
The old V1 API with a site API key was retired on 3 November 2026. Not affiliated with SolarEdge.

**📘 Full installation guide: [docs/INSTALLATION.md](docs/INSTALLATION.md)**

## What is included

| File | Purpose |
|---|---|
| `custom_components/solaredge_v2/` | the integration |
| `docs/INSTALLATION.md` | step-by-step guide, credits, troubleshooting |
| `web/solaredge-callback.html` | relay page you host on your own HTTPS domain |
| `tools/probe.py` | standalone script to check endpoints and parameters against the real API |
| `tests/` | tests (parser, full config flow with callback, sensors) |

## Why a relay page

SolarEdge only accepts an **HTTPS redirect with a hostname** (no `http://` and no IP address) and does not return a `state` value.
Home Assistant usually runs on an `http://` address inside your own network. So:

1. SolarEdge sends your browser to `https://example.com/solaredge-callback.html?code=…&site_id=…` (your domain).
2. That static page forwards the same browser to `http://<your-home-assistant>:8123/api/solaredge_v2/callback?…`.
   This only works from a device on your home network. Home Assistant does not need to be reachable from the internet.
3. The integration has its own callback view, ties the redirect to the running setup through `external_id` and uses PKCE.

The one-time code appears once in your web server's logs. It is short-lived and useless without your client secret and the PKCE verifier.

## Installation

### 1. Relay page

Put `web/solaredge-callback.html` on your own HTTPS domain, for example `https://example.com/solaredge-callback.html`.
Edit `HA_BASE` at the top to the address you use to open Home Assistant (no trailing slash).

### 2. Install the integration

**Through the Marketplace** (Home Assistant 2026.11 and newer, formerly HACS): go to **Settings → Marketplace → Add from link**,
paste the URL of this repository and install the integration. The Marketplace needs a one-time GitHub link through device sign-in.
Older Home Assistant versions use HACS: **Custom repositories → Integration**.

**Manually:** copy the folder `custom_components/solaredge_v2` to `/config/custom_components/` and restart Home Assistant.

### 3. SolarEdge developer app

Log in at https://developer.solaredge.com with the **mySolarEdge homeowner** account (not an installer account) and create an app:

- Service: **Monitoring API**, Access type: **Site Access**
- **Origin URL:** `https://example.com`
- **Redirect URI** and **Returned URL:** `https://example.com/solaredge-callback.html`
- **Scopes:** `SITE_DATA` and `DEVICE_DATA`
- Save the Client ID and Client Secret (the secret is shown only once).

### 4. Add the integration

**Settings → Devices & services → Add integration → SolarEdge Monitoring API v2.**
Enter the Client ID and secret, replace the example Redirect URI with your own relay address, choose **Log in automatically** and approve access.
If the redirect step does not work, choose **Log in manually** and paste the address of the tab after approving.

SolarEdge replaces the refresh token on every use; the integration stores the new token immediately.
Do not use the same token in `probe.py` or a second integration at the same time.

## Entities

One sensor per value in the V2 response, with clear names for the main ones:

| Entity | Source | Note |
|---|---|---|
| **Solar power** | `/power` | newest *filled* quarter hour (SolarEdge runs 15-30 min behind; the time is in the `data_timestamp` attribute) |
| Production today | `/overview?from=<today 00:00>&to=now` | Wh |
| Energy this month / this year | `/energy?resolution=MONTH` | Wh |
| Lifetime energy | `/lifetime-energy` | on-board counter |
| Inverter: AC power, energy, voltage, current, frequency, consumed AC | `/inverters/telemetry` | separate device per inverter |
| Battery / meter | `/storage/...`, `/meters/...` | only if the inventory (`/devices`) reports them |
| Open alerts, peak power, last update, device details | `/alerts`, `/sites/{id}`, `/devices` | many text fields are disabled by default |

## Credits and polling

Every call costs 1 credit; the free tier is 2,000 per month and 10 per minute. SolarEdge itself only has new data every 15 minutes, so polling more often than that is pointless.

* **Live power** (`/power`) is polled during daylight; **production today** every 2x that interval; **inverter telemetry** every 4x.
* **Daylight** = sun above the horizon (`sun.sun` entity) + 45 minutes. Nothing is fetched at night (option *Poll during daylight only*).
* **Slow data** (site, monthly/yearly energy, lifetime, alerts) every 12 hours, devices every 24 hours.
* Interval 0 = **automatic**, calculated from the budget (default 1,800 per cycle). With the defaults this is about every 25 minutes.
* An endpoint that returns 4xx is skipped temporarily, with the SolarEdge message in the log.
* Values are stored, so a restart does not cost credits.

## Real time?

The cloud API works per quarter hour. For live power you can use local Modbus TCP (LAN only, not Wi-Fi, according to the
SolarEdge SunSpec technical note), for example with the community integration *SolarEdge Modbus Multi*.

## Good to know

* Unofficial project, tested on one residential installation without battery or meter.
* The formats of `/lifetime-energy`, `/alerts` and the meter/battery responses have not been verified with real data from multiple installations; the sensors appear automatically once values exist.
* Optimizer-level data and live power-flow fall under SolarEdge Advanced Monitoring and are not part of the free tier.
* No backfill into long-term statistics yet.
* `tools/probe.py` shows exactly what SolarEdge returns.

## Tests

```
pip install pytest-homeassistant-custom-component
pytest            # in the project folder
```
