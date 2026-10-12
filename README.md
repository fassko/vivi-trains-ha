# Vivi Trains — Home Assistant Integration

Monitor Latvian train (Vivi / Pasažieru vilciens) departures from any station directly in Home Assistant.

## What's included

```
custom_components/vivi_trains/   ← drop into config/custom_components/
```

## Installation

### HACS custom repository

1. In HACS, open **Custom repositories**.
2. Add this repository URL as type **Integration**.
3. Install **Vivi Trains**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration**, search for **Vivi Trains**, and choose a station.

Then add the dashboard resource:

| URL | Type |
|-----|------|
| `/vivi_trains_frontend/vivi-trains-card.js` | JavaScript module |

### Manual installation

#### Step 1 — Copy files

Copy the integration folder to your HA `config/` directory so the structure looks like:

```
config/
├── custom_components/
│   └── vivi_trains/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── schedule.py
│       ├── gtfs.py
│       ├── button.py
│       ├── sensor.py
│       ├── strings.json
│       ├── translations/en.json
│       ├── vivi_schedule.json      ← bundled schedule data
│       ├── brand/
│       │   └── icon.png
│       └── frontend/
│           └── vivi-trains-card.js
```

#### Step 2 — Restart Home Assistant

Restart HA so it picks up the new integration.

#### Step 3 — Add integration

Go to **Settings → Devices & Services → Add Integration**, search for **Vivi Trains**, and select your station from the dropdown (all 141 stations are listed).

#### Step 4 — Add Lovelace resource

In **Settings → Dashboards → (three-dot menu) → Resources**, add:

| URL | Type |
|-----|------|
| `/vivi_trains_frontend/vivi-trains-card.js` | JavaScript module |

#### Step 5 — Add card to dashboard

Edit your dashboard and add a **Manual card** with:

```yaml
type: custom:vivi-trains-card
entity: sensor.vivi_carnikava_next_departure   # replace with your station
title: "Carnikava → Rīga"                      # optional custom title
max_departures: 5                              # optional (default: 5)
direction: towards_riga                        # optional: all, towards_riga, from_riga
show_route_color: true                         # optional (default: true)
```

Use `direction: towards_riga` to show trains whose route ends in Rīga, for example `Skulte - Rīga`.
Use `direction: from_riga` to show trains whose route starts from Rīga, for example `Rīga - Skulte`.
The filter applies to the departures already exposed by the sensor, so increase the integration's departures count if you want the card to reliably show several matching departures.
When more matching departures are available than `max_departures`, the card shows Previous/Next controls.

## Local testing

To test before installing with HACS:

1. Copy `custom_components/vivi_trains` to `<ha-config>/custom_components/vivi_trains`.
2. Restart Home Assistant.
3. Add the integration from **Settings → Devices & Services**.
4. Open `/vivi_trains_frontend/vivi-trains-card.js` from your HA base URL while logged in. It should return JavaScript.
5. Add the Lovelace resource and card YAML above.

## Troubleshooting

### `Custom element doesn't exist: vivi-trains-card`

Home Assistant shows this when the dashboard has not loaded the card JavaScript module.

1. Confirm the integration is installed and Home Assistant has been restarted.
2. Open `/vivi_trains_frontend/vivi-trains-card.js` from your Home Assistant base URL while logged in. It should display JavaScript.
3. In **Settings → Dashboards → Resources**, confirm this resource exists:

   | URL | Type |
   |-----|------|
   | `/vivi_trains_frontend/vivi-trains-card.js` | JavaScript module |

4. Hard-refresh the Home Assistant browser tab after adding or changing the resource.

To run the unit tests:

```bash
python3 -m unittest discover -s tests
```

## Entities created

For each configured station, a sensor and a **Check schedule now** button are created:

| Entity | State | Attributes |
|--------|-------|------------|
| `sensor.vivi_<station>_next_departure` | `HH:MM` next departure | `minutes_until`, `destination`, `route_color`, `service_days`, `next_departures` (list) |
| `button.vivi_<station>_check_schedule_now` | Last pressed time | Press to check Vivi's GTFS feed immediately |

## Schedule data

The bundled `vivi_schedule.json` is pre-processed from [Vivi's official GTFS feed](https://vivi.lv/lv/sadarbiba/atvertie-dati/). The current bundle contains 141 stations and 349 trips (feed dated 12 October 2026).

When Home Assistant starts, the integration checks whether the last successful feed check was at least seven days ago. It checks again each day and downloads the feed when seven days have passed. A changed feed is saved in Home Assistant's `.storage` directory and applied to all configured station sensors without a restart. If the download fails, the last saved or bundled schedule stays in use and the next daily check retries.

Press **Check schedule now** on any Vivi station device to check immediately. The button reports download errors in Home Assistant. All station devices share the same schedule, so pressing one button updates them all. The sensor attributes `schedule_checked_at` and `schedule_updated_at` show the last successful check and the last changed feed.

To regenerate the bundled fallback for a release, download Vivi's `GTFS.zip` and run `python3 scripts/update_schedule.py /path/to/GTFS.zip`.

## Notes

- Departures are computed locally every 60 seconds. The weekly schedule check needs internet access; departures continue to work from saved data while offline.
- Times past midnight are represented as `24:MM`, `25:MM` etc. in the raw GTFS data and are handled correctly.
