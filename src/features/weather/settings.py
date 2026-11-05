from src.shared.configuration import SettingField as Field, SettingsSection


def section(provider_choices: tuple[tuple[str, str], ...]) -> SettingsSection:
    return SettingsSection("weather", "settings.weather.title", "settings.weather.description", (
        Field("provider", "settings.weather.provider.label", "choice", choices=provider_choices),
        Field("forecast_url", "settings.weather.forecast_url.label"),
        Field("geocoding_url", "settings.weather.geocoding_url.label"),
        Field("location_name", "settings.weather.location_name.label"),
        Field("latitude", "settings.weather.latitude.label", "float", -90, 90),
        Field("longitude", "settings.weather.longitude.label", "float", -180, 180),
        Field("forecast_days", "settings.weather.forecast_days.label", "int", 10, 16),
        Field("history_days", "settings.weather.history_days.label", "int", 0, 7, hint_key="settings.weather.history_days.hint"),
        Field("refresh_minutes", "settings.weather.refresh_minutes.label", "int", 5, 1440),
        Field("timeout_seconds", "settings.weather.timeout_seconds.label", "int", 2, 30),
        Field("auto_refresh", "settings.weather.auto_refresh.label", "bool"),
        Field("search_query", "settings.weather.search_query.label"),
    ))
