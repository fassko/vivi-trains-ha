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

For each configured station, one sensor is created:

| Entity | State | Attributes |
|--------|-------|------------|
| `sensor.vivi_<station>_next_departure` | `HH:MM` next departure | `minutes_until`, `destination`, `route_color`, `service_days`, `next_departures` (list) |

## Schedule data

The bundled `vivi_schedule.json` is pre-processed from the official Vivi GTFS open data feed (vivi.lv). It covers all 141 stations and 394 trips, including through-trains (e.g. Skulte → Rīga trains stopping at Carnikava).

To refresh the data, replace `vivi_schedule.json` with a freshly generated file (see the project repository for the generation script) and restart HA.

## Notes

- The integration runs entirely **local** — no internet connection required after setup.
- Schedule data is updated every 60 seconds in memory but the underlying GTFS data only needs refreshing seasonally (Vivi publishes new GTFS files with each timetable change).
- Times past midnight are represented as `24:MM`, `25:MM` etc. in the raw GTFS data and are handled correctly.
