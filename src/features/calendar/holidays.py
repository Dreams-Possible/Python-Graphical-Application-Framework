"""中国大陆节假日：后台下载年度公开数据，缓存用于断网回退。"""

from src.shared.errors import error_message

from src.shared.errors import ui_error
import json
from src.shared.messages import message
from dataclasses import dataclass
from urllib.error import HTTPError
from PySide6.QtCore import QObject, Signal
from src.shared.http import get_json
from src.shared.tasks import check_cancelled


@dataclass(frozen=True)
class Holiday:
    name: str
    off: bool


def parse_days(document, year):
    if document.get("year") != year or not isinstance(document.get("days"), list):
        raise ui_error(ValueError, "errors.holiday_year")
    from datetime import date
    result = {}
    for entry in document["days"]:
        key = entry["date"]
        date.fromisoformat(key)
        if not isinstance(entry.get("name"), str) or type(entry.get("isOffDay")) is not bool:
            raise ui_error(ValueError, "errors.holiday_record")
        result[key] = Holiday(entry["name"], entry["isOffDay"])
    return result


def parse_international(document, year, country):
    if not isinstance(document, list):
        raise ui_error(ValueError, "errors.public_holiday")
    from datetime import date
    result = {}
    for entry in document:
        key = entry["date"]
        if date.fromisoformat(key).year != year or entry.get("countryCode") != country:
            raise ui_error(ValueError, "errors.holiday_country")
        # 不把某个州或省的假日错误应用到全国。
        if not entry.get("global") or "Public" not in entry.get("types", []):
            continue
        name = entry.get("localName") or entry.get("name")
        if not isinstance(name, str) or not name:
            raise ui_error(ValueError, "errors.holiday_name")
        previous = result.get(key)
        result[key] = Holiday(previous.name + " / " + name if previous else name, True)
    return result


class HolidayService(QObject):
    changed = Signal()

    def __init__(self, tasks, cache, settings):
        super().__init__()
        self.tasks, self.cache, self.settings = tasks, cache / "calendar", settings
        self.data, self.messages, self.requests = {}, {}, {}
        self.country = ""
        self.location_name = ""
        self.timezone = ""
        self._epoch = 0
        tasks.completed.connect(self._completed)

    def set_location(self, fix):
        country = fix.country_code if fix else ""
        self.location_name = fix.name if fix else ""
        self.timezone = fix.timezone if fix else ""
        if country != self.country:
            for key in self.requests:
                self.tasks.cancel(key)
            self._epoch += 1
            self.requests.clear()
            self.data.clear()
            self.messages.clear()
            self.country = country
        self.changed.emit()

    def today(self):
        from PySide6.QtCore import QDate, QDateTime, QTimeZone
        if self.timezone:
            return QDateTime.currentDateTimeUtc().toTimeZone(QTimeZone(self.timezone.encode())).date()
        return QDate.currentDate()

    def _parse(self, doc, year, country):
        if doc.get("country") != country:
            raise ui_error(ValueError, "errors.holiday_cache")
        if country != "CN":
            return parse_international(doc["base"], year, country)
        records = parse_days(doc["base"], year)
        if doc.get("next"):
            records.update(parse_days(doc["next"], year + 1))
        return records

    def ensure(self, year):
        if not self.country or year in self.messages:
            return
        country = self.country
        cached = self.cache / f"{country.lower()}-{year}.json"
        try:
            doc = json.loads(cached.read_text(encoding="utf-8"))
            self.data[year] = self._parse(doc, year, country)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.messages[year] = message("calendar.loading_cached" if year in self.data else "calendar.loading")
        values = self.settings.get("calendar")
        def fetch(stop):
            following, note = None, ""
            if country == "CN":
                base = get_json(values["holiday_url"].format(year=year), {}, values["timeout_seconds"], stop)
                parse_days(base, year)
                try:
                    following = get_json(values["holiday_url"].format(year=year + 1), {}, values["timeout_seconds"], stop)
                    parse_days(following, year + 1)
                except HTTPError as error:
                    if error.code != 404:
                        raise
                    note = message("calendar.next_unpublished")
            else:
                base = get_json(values["international_url"].format(year=year, country=country), {}, values["timeout_seconds"], stop, allow_list=True)
                parse_international(base, year, country)
                note = message("calendar.national_only")
            check_cancelled(stop)
            return {"country": country, "base": base, "next": following}, note
        key = f"calendar.holidays.{country}.{year}.{self._epoch}"
        try:
            generation = self.tasks.submit(key, fetch)
            self.requests[key] = (year, generation, country)
        except RuntimeError as error:
            self.messages[year] = error_message(error)

    def retry(self, year):
        if not any(request[0] == year for request in self.requests.values()):
            self.messages.pop(year, None)
            self.ensure(year)
            self.changed.emit()

    def _completed(self, key, generation, result, error, cancelled):
        if key not in self.requests or self.requests[key][1] != generation:
            return
        year, _, country = self.requests.pop(key)
        if country != self.country:
            return
        if error or cancelled:
            self.messages[year] = message("calendar.failed_cached" if year in self.data else "calendar.failed")
        else:
            document, note = result
            self.data[year] = self._parse(document, year, country)
            self.messages[year] = message("calendar.updated", note=note)
            try:
                self.cache.mkdir(parents=True, exist_ok=True)
                target = self.cache / f"{country.lower()}-{year}.json"
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
                temporary.replace(target)
            except OSError:
                self.messages[year] = message("calendar.cache_failed", status=self.messages[year])
        self.changed.emit()

    def status(self, year):
        if not self.country:
            return message("calendar.location_unknown")
        source = "holiday-cn" if self.country == "CN" else "Nager.Date"
        return message("calendar.source", location=self.location_name, country=self.country, source=source, status=self.messages.get(year, message("calendar.not_loaded")))

    def event(self, day):
        return self.data.get(day.year(), {}).get(day.toString("yyyy-MM-dd"))

    def label(self, day):
        entry = self.event(day)
        if not entry:
            return ""
        if self.country == "CN":
            return message("calendar.off" if entry.off else "calendar.work", name=entry.name)
        return message("calendar.public", name=entry.name)

    def text(self, day):
        label = self.label(day)
        if label:
            return label
        if day.year() not in self.data:
            return message("calendar.not_loaded")
        return message("calendar.no_special" if self.country == "CN" else "calendar.no_national")
