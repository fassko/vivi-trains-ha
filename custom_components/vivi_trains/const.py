"""Constants for the Vivi Trains integration."""

DOMAIN = "vivi_trains"

# Config entry keys
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_DEPARTURES_COUNT = "departures_count"

# Defaults
DEFAULT_DEPARTURES_COUNT = 5
DEFAULT_SCAN_INTERVAL = 60  # seconds

# Schedule data bundled with integration
SCHEDULE_DATA_FILE = "vivi_schedule.json"

# Sensor
ATTR_NEXT_DEPARTURES = "next_departures"
ATTR_MINUTES_UNTIL = "minutes_until"
ATTR_DESTINATION = "destination"
ATTR_ORIGIN = "origin"
ATTR_PLATFORM = "platform"
ATTR_ROUTE_COLOR = "route_color"
ATTR_SERVICE_DAYS = "service_days"

# Day names for display
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES_LV = ["P", "O", "T", "C", "Pk", "S", "Sv"]
