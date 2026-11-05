"""天气原始值的展示转换；图表计算始终使用原始数值。"""
CODES = frozenset((0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99))


def condition(texts, code):
    return texts.get(f"weather.condition.{code}" if code in CODES else "weather.condition.unknown")


def measurement(texts, value, unit):
    if value is None:
        return texts.get("common.unavailable")
    return texts.get(f"weather.unit.{unit}", value=texts.number(value))


def forecast_row(point, hourly, texts):
    if hourly:
        return (texts.short_date(point.when.date()) + " " + texts.time(point.when, seconds=False), condition(texts, point.weather_code),
                measurement(texts, point.temperature, "temperature"), measurement(texts, point.apparent, "temperature"),
                measurement(texts, point.humidity, "percent"), measurement(texts, point.precipitation_probability, "percent"),
                measurement(texts, point.precipitation, "mm"), measurement(texts, point.wind, "wind"))
    return (texts.date(point.when.date()), condition(texts, point.weather_code),
            measurement(texts, point.minimum, "temperature"), measurement(texts, point.maximum, "temperature"),
            measurement(texts, point.precipitation_probability, "percent"), measurement(texts, point.precipitation, "mm"),
            measurement(texts, point.wind, "wind"))
