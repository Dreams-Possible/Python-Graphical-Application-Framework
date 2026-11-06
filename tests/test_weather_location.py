"""当前天气与搜索天气的状态、请求和取消完全隔离。"""
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from src.features.location.service import LocationFix
from src.features.weather.models import Location
from src.features.weather.view_model import WeatherViewModel
from src.shared.paths import resource_path


class Configuration(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.values = json.loads(resource_path('defaults/weather.json').read_text(encoding='utf-8'))['values']

    def get(self, key):
        return self.values.copy()

    def update(self, key, **changes):
        self.values.update(changes)
        self.changed.emit(key)


class Tasks(QObject):
    completed = Signal(str, int, object, object, bool)
    activity_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.sequence, self.jobs, self.cancelled = 0, {}, []

    def submit(self, key, work):
        self.sequence += 1
        self.jobs[key] = (self.sequence, work)
        return self.sequence

    def is_active(self, key):
        return key in self.jobs

    def cancel(self, key):
        self.cancelled.append(key)


class WeatherLocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.configuration, self.tasks = Configuration(), Tasks()
        self.provider = Mock()
        providers = Mock()
        providers.get.return_value = self.provider
        self.timer = patch('src.features.weather.view_model.QTimer.singleShot').start()
        self.addCleanup(patch.stopall)
        self.model = WeatherViewModel(self.configuration, self.tasks, providers)
        self.addCleanup(self.model.stop)
        self.fix = LocationFix('Unified location', 29.5, 106.5, 'Asia/Shanghai', 'CN')

    def test_waits_for_unified_location_then_fetches_without_overwriting_manual_config(self):
        self.model.refresh()
        self.assertFalse(self.tasks.jobs)
        self.assertEqual(self.model.state.status.key, 'weather.state.waiting_location')
        original = self.configuration.values.copy()
        self.model.set_current_location(self.fix)
        self.model._try_pending()
        self.tasks.jobs['weather.fetch'][1](Event())
        values = self.provider.fetch.call_args.args[0]
        self.assertEqual((values['location_name'], values['latitude'], values['longitude']), (self.fix.name, self.fix.latitude, self.fix.longitude))
        self.assertEqual(self.configuration.values, original)

    def test_search_selection_does_not_change_current_location_or_configuration(self):
        self.model.set_current_location(self.fix)
        original = self.configuration.values.copy()
        self.model._set_search(locations=(Location('Search city', 10, 20),))
        self.model.select_location(0)
        self.assertEqual(self.configuration.values, original)
        self.tasks.jobs['weather.preview'][1](Event())
        values = self.provider.fetch.call_args.args[0]
        self.assertEqual((values['location_name'], values['latitude'], values['longitude']), ('Search city', 10, 20))
        self.model.set_current_location(LocationFix('Other', 30, 110, 'Asia/Shanghai', 'CN'))
        self.assertEqual(self.model.search_state.locations[0].name, 'Search city')
        self.assertEqual(self.model._preview_location.name, 'Search city')

    def test_location_loss_cancels_old_request_and_ignores_stale_result(self):
        self.model.set_current_location(self.fix)
        self.model.refresh()
        generation = self.tasks.jobs['weather.fetch'][0]
        self.model.set_current_location(None)
        self.assertIn('weather.fetch', self.tasks.cancelled)
        self.tasks.completed.emit('weather.fetch', generation, SimpleNamespace(hourly=(), daily=(), history=()), '', False)
        self.assertIsNone(self.model.state.report)
        self.assertFalse(self.model.state.busy)
        self.assertEqual(self.model.state.status.key, 'weather.state.waiting_location')

    def test_auto_refresh_off_requires_manual_refresh_even_after_location_update(self):
        self.configuration.update('weather', auto_refresh=False)
        self.model.set_current_location(self.fix)
        self.model._try_pending()
        self.assertFalse(self.tasks.jobs)
        self.model.refresh()
        self.assertIn('weather.fetch', self.tasks.jobs)

    def test_results_errors_and_cancellation_are_separate_between_panels(self):
        self.model.set_current_location(self.fix)
        self.model.refresh()
        self.model._set_search(locations=(Location('Search city', 10, 20),))
        self.model.select_location(0)
        current_generation = self.tasks.jobs['weather.fetch'][0]
        preview_generation = self.tasks.jobs['weather.preview'][0]
        current = SimpleNamespace(location='Current', hourly=(), daily=(), history=())
        preview = SimpleNamespace(location='Search', hourly=(), daily=(), history=())
        self.tasks.completed.emit('weather.fetch', current_generation, current, '', False)
        self.tasks.completed.emit('weather.preview', preview_generation, preview, '', False)
        self.assertIs(self.model.state.report, current)
        self.assertIs(self.model.search_state.report, preview)
        self.tasks.completed.emit('weather.preview', preview_generation, None, 'Search failed', False)
        self.assertEqual(self.model.search_state.error, 'Search failed')
        self.assertEqual(self.model.state.error, '')
        self.assertIs(self.model.state.report, current)
        self.tasks.cancelled.clear()
        self.model.cancel_current()
        self.assertEqual(self.tasks.cancelled, ['weather.fetch'])
        self.tasks.cancelled.clear()
        self.model.cancel_search()
        self.assertEqual(self.tasks.cancelled, ['weather.search', 'weather.preview'])
        self.tasks.completed.emit('weather.preview', preview_generation, None, 'Late failure', False)
        self.assertIs(self.model.search_state.report, preview)
        self.assertEqual(self.model.search_state.error, 'Search failed')

    def test_view_renders_each_panel_from_its_own_report(self):
        from datetime import datetime, timezone
        from src.features.weather.models import WeatherReport
        from src.features.weather.view import WeatherView
        from src.shared.localization import Localization
        current = WeatherReport('Current', 20, 0, 50, 1, datetime.now(timezone.utc), 'UTC', (), (), (), 'test')
        preview = replace(current, location='Search', temperature=5)
        self.model._set(report=current)
        self.model._set_search(report=preview)
        view = WeatherView(self.model, Localization(mode='zh-CN'))
        self.model.set_active(True)
        try:
            self.assertIs(view.details._report, current)
            self.assertIs(view.search_details._report, preview)
            updated = replace(current, temperature=30)
            self.model._set(report=updated)
            self.assertIs(view.details._report, updated)
            self.assertIs(view.search_details._report, preview)
            self.model.set_current_location(self.fix)
            self.assertIs(view.search_details._report, preview)
        finally:
            view.close()
            view.deleteLater()
