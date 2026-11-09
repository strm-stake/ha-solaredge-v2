# Installation guide: SolarEdge Monitoring API v2 for Home Assistant

🇳🇱 [Nederlandse versie](INSTALLATIE.md)

This integration reads your SolarEdge installation into Home Assistant through the new Monitoring API v2 (OAuth 2.0).
Plan for about 30 minutes and four steps. The old V1 API with a site key was retired on 3 November 2026.

## Before you start

You need five things. The fourth is the one people underestimate: SolarEdge only accepts an HTTPS address with a domain name as redirect, so you need some web space of your own.

| What | Details |
| --- | --- |
| Home Assistant | A recent version (OS, Container or Core), reachable on your home network. You must be able to reach the `/config` folder |
| SolarEdge account | The mySolarEdge account of the **homeowner**. An installer account cannot grant Site Access |
| Developer portal | Access to developer.solaredge.com with that same account |
| Your own HTTPS domain | One static page on a domain you control, for example your own website, GitHub Pages or Netlify |
| A device on your home network | You do the linking from a computer or phone on the same network as Home Assistant |

## How it works

After you log in, SolarEdge sends you back to an HTTPS address, but Home Assistant usually runs on an `http://` address inside your network. A small relay page on your domain bridges the gap.

1. You start the setup in Home Assistant and click **Log in automatically**.
2. A SolarEdge tab opens. You log in and approve access.
3. SolarEdge sends your browser to your relay page, with a one-time `code` in the address.
4. The relay page immediately forwards the same browser to Home Assistant on your home network. That is why you must work from a device on that network.
5. The integration exchanges the code for tokens (using PKCE), fetches your site details and creates the connection.

Home Assistant therefore does not need to be reachable from the internet. The relay page stores nothing and contains only a few lines of JavaScript.

## Step 1: place the relay page

Take the file [`web/solaredge-callback.html`](../web/solaredge-callback.html) from this repository and put it on your own domain, for example at `https://yourdomain.com/solaredge-callback.html`.
Change only the `HA_BASE` line to the address you use to open Home Assistant, without a trailing slash (for example `http://192.168.1.50:8123`).
That address must be reachable from the browser you log in with.

Then check in your browser that `https://yourdomain.com/solaredge-callback.html` loads. You will see a message that the page is called by SolarEdge.
Write this address down, you need it in steps 3 and 4. It must be exactly the same in both.

## Step 2: install the integration

You can install the integration in two ways: through the Home Assistant Marketplace (the repository is on GitHub), or manually.

**Through the Marketplace** (Home Assistant 2026.11 and newer, the successor of HACS):

1. Open **Settings → Marketplace** and accept the warning about community projects.
2. Choose **Add from link** and enter the URL of this GitHub repository. You link GitHub once through device sign-in, without entering a password in Home Assistant.
3. Install **SolarEdge Monitoring API v2**. Installing does not need a restart, updates do.

On an older Home Assistant version use HACS: **Custom repositories**, type *Integration*.

**Manually:** copy the folder `custom_components/solaredge_v2` from this repository into the `custom_components` folder of your Home Assistant configuration. It must look like this:

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

Create the `custom_components` folder if it does not exist. You can place the files in one of these ways:

- **Samba share** (add-on *Samba share*): drag the folder to the network share `config`.
- **File editor** or **Studio Code Server** (add-ons): create the folder and files in the browser.
- **SSH** (add-on *Terminal & SSH*): copy with `scp` or `cp`.

Then restart through **Settings → System → Restart**. Without a restart Home Assistant does not know the integration yet, and *SolarEdge Monitoring API v2* will not appear in the list in step 4.

## Step 3: create the SolarEdge developer app

Log in at developer.solaredge.com with the homeowner account and create a new app. Use the values below. Menu names in the portal may differ slightly, the field names stay the same.

| Field | Value |
| --- | --- |
| Service | Monitoring API |
| Access type | **Site Access** |
| Origin URL | `https://yourdomain.com` (domain only, no path) |
| Redirect URI | `https://yourdomain.com/solaredge-callback.html` |
| Returned URL | Exactly the same address as the Redirect URI |
| Scopes | `SITE_DATA` and `DEVICE_DATA` |

After creating the app, save the **Client ID** and the **Client Secret**. You see the secret only once. If you lose it, create a new secret or a new app.

The Redirect URI and the Returned URL must match, character for character, the address you enter in step 4. A difference of one slash or one capital letter gives an error when logging in.

## Step 4: add and log in

Work from a device on the same network as Home Assistant.

1. Go to **Settings → Devices & services → Add integration** and choose **SolarEdge Monitoring API v2**.
2. Enter the **Client ID** and the **Client secret** from step 3.
3. For **Redirect URI** enter your relay address (the field contains an example address you must replace), for example `https://yourdomain.com/solaredge-callback.html`.
4. Leave **Extra authorize parameters** at the default `scope=SITE_DATA DEVICE_DATA` and submit the form.
5. Choose **Log in automatically**. A SolarEdge tab opens.
6. Log in with the homeowner account and approve access for your site.
7. You are sent back to Home Assistant through your relay page. The tab reports that the connection is ready. Close the tab and return to Home Assistant.

The result is an integration named *SolarEdge* followed by the name of your site. The first values appear within a few minutes.

Does the redirect step not work, for example because you are not on your home network? Then choose **Log in manually**: after approving, copy the full address of the tab (it contains `code=`) and paste it in the field in Home Assistant. Logging in automatically is the recommended route, manual is only a fallback.

## What you get

The integration creates a sensor for every value in the API response. Many text fields (such as firmware versions) are disabled by default; enable them yourself if you want to see them. The main sensors:

| Sensor | Source | Note |
| --- | --- | --- |
| Solar power | `/power` | Latest filled quarter hour in W. SolarEdge runs 15 to 30 minutes behind. The time is in the `data_timestamp` attribute |
| Production today | `/overview` | Wh since midnight |
| Energy this month / this year | `/energy` | Monthly and yearly total in Wh |
| Lifetime energy | `/lifetime-energy` | Inverter counter |
| Inverter: AC power, energy, voltage, current, frequency | `/inverters/telemetry` | Separate device per inverter. Only with telemetry on |
| Battery and meter | `/storage`, `/meters` | Only if the inventory (`/devices`) reports them |
| Open alerts, peak power, last update | `/alerts`, `/sites/{id}` | Site details and alerts |
| Credits (used and remaining) | Internal counter | Per billing period |

The values are not real time. The API works per quarter hour. See the real-time section if you need live data.

## Credits and polling

Every API call costs one credit. The free tier gives 2,000 credits per month and at most 10 calls per minute. SolarEdge itself only has new data every 15 minutes, so polling more often than every 15 minutes gains nothing. The integration therefore calculates the interval automatically from your budget. With the default settings that is about every 25 minutes during daylight.

Open **Settings → Devices & services → SolarEdge Monitoring API v2 → Configure** to change this:

| Option | Default | Effect |
| --- | --- | --- |
| Read telemetry of inverter, meter and battery | On | Fetches power, voltage and current per inverter. Turn off to save credits |
| Minutes between power updates | 0 (automatic) | 0 lets the integration choose the interval. The minimum is 15 minutes |
| Credits per billing period | 1,800 | Your budget, with a margin below 2,000 |
| Day on which credits reset | 1 | The day your billing period starts |
| Poll during daylight only | On | Sun above the horizon plus 45 minutes. Saves about half of the credits |

The remaining data is much cheaper: site details, monthly and yearly totals, lifetime energy and alerts every 12 hours, the device list every 24 hours. A call that keeps returning an error (4xx) is skipped temporarily and the SolarEdge message appears in the log. Values are stored, so restarting Home Assistant does not cost credits.

## Need real time?

Through the cloud API you cannot get below a quarter hour. If you want the current power per second, use **Modbus TCP** locally on your inverter, without credits, next to this integration.
The community integration [SolarEdge Modbus Multi](https://github.com/WillCodeForCats/solaredge-modbus-multi/wiki/Configuration) does that for Home Assistant.

Note: according to the [SolarEdge SunSpec technical note](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf), Modbus TCP only works over a **LAN cable**, not over Wi-Fi.
It is off by default and you enable it in the inverter menu or in SetApp, often with installer rights. Only one Modbus connection at a time is allowed.

## Troubleshooting

| What you see | Most likely cause | Fix |
| --- | --- | --- |
| *Invalid redirect_uri* or authorization refused | The Redirect URI, the Returned URL and the field in Home Assistant are not exactly equal | Make all three identical, including slash and capitals. SolarEdge's message is shown literally in the error |
| Page not found (404) on `/api/solaredge_v2/callback` or *Setup could not continue* | Home Assistant was not restarted after copying, or you chose Log in manually and the browser still reached the callback | Restart Home Assistant and start again with Log in automatically |
| Nothing happens in Home Assistant after approving | You are not on your home network, or `HA_BASE` in the relay page is wrong | Check `HA_BASE`. Otherwise use Log in manually and paste the full address with `code=` |
| You see no site or get no access | You are using an installer account | Log in with the homeowner account. Site Access only works with that |
| The value is a quarter hour or more behind | SolarEdge delivers per quarter hour with 15 to 30 minutes delay | This is normal. Use Modbus locally for live data |
| Many sensors are disabled | Text fields and details are off by default | Enable them in the entity settings of the sensor |
| *SolarEdge API limit reached* | Your credits or the limit of 10 calls per minute are used up | Turn off telemetry and keep Poll during daylight only on. Wait until the billing period resets |
| Home Assistant asks to log in again | The token expired or was revoked | Follow the notification and go through step 4 again. Do not use the same token in another tool at the same time, because SolarEdge replaces it on every use |

Want to see more? Open **Settings → System → Logs** and filter on `solaredge_v2`. On the integration page you can also **Download diagnostics**.
That export contains no client ID, secret, tokens or site ID and is suitable to attach to a question.

## Privacy, updating and removing

- **Where does your data go?** The integration only talks to SolarEdge (`monitoringapi.solaredge.com` and `connect.solaredge.com`). The client secret and tokens are stored in the configuration of your own Home Assistant.
- **The relay page.** It stores nothing and sends no referrer. The one-time code does appear in your web host's access log. That code is short-lived and useless without your client secret.
- **Updating.** Replace the `solaredge_v2` folder with the new version and restart Home Assistant (or update through the Marketplace). Your settings are kept.
- **Removing.** Remove the integration under *Devices & services*, then the `solaredge_v2` folder, and finally the app in the SolarEdge developer portal, so the token is no longer valid.

## Limitations and status

This is an unofficial community project and is not affiliated with SolarEdge. It was built and tested on one residential installation with one inverter, without battery or meter.

- The response formats for lifetime energy, alerts, meters and batteries are based on SolarEdge's documentation and have not yet been verified with real data from multiple installations. The sensors appear automatically once values exist.
- Per-optimizer data and live power-flow fall under SolarEdge Advanced Monitoring and are not part of the free tier.
- The integration does not backfill Home Assistant's long-term statistics.
- SolarEdge may change the V2 API. After a SolarEdge update, check that the sensors still show values and report deviations with the diagnostics export.
