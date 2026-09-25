"""
Tests for src.com_write: COM-safe dates, save policy, batched calc, lookups.

Expected values come from the Project type library and live probes, not from the code
under test.
"""

import datetime
from unittest.mock import MagicMock

import pytest

from src.com_write import (
    parse_iso, to_com_date, minutes_per_day, commit, batch_calc, resolve_resource,
    resolve_calendar, validate_rag, invoke_positional, TIMESCALES, LINK_TYPES,
)

UTC = datetime.timezone.utc


def _proj(start=(8, 0), finish=(17, 0), path="C:\\x.mpp", hours=8.0):
    proj = MagicMock()
    proj.DefaultStartTime = datetime.datetime(1899, 12, 30, *start)
    proj.DefaultFinishTime = datetime.datetime(1899, 12, 30, *finish)
    proj.Path = path
    proj.FullName = path
    proj.HoursPerDay = hours
    return proj


class TestDates:
    def test_date_only_start_uses_default_start_time_and_utc(self):
        # pywin32 shifts naive datetimes by the local UTC offset; UTC-aware ones are kept.
        d = to_com_date(_proj(), "2031-06-01")
        assert d == datetime.datetime(2031, 6, 1, 8, 0, tzinfo=UTC)

    def test_date_only_finish_is_end_of_working_day(self):
        # "finish 2031-06-05" must not mean midnight at the start of that day.
        d = to_com_date(_proj(), "2031-06-05", end_of_day=True)
        assert d == datetime.datetime(2031, 6, 5, 17, 0, tzinfo=UTC)

    def test_explicit_time_is_kept(self):
        assert to_com_date(_proj(), "2031-06-05T13:30").hour == 13

    def test_project_default_times_are_used(self):
        d = to_com_date(_proj(start=(7, 30)), "2031-06-01")
        assert (d.hour, d.minute) == (7, 30)

    @pytest.mark.parametrize("bad", ["06/10/2031", "2031-13-01", "", "tomorrow"])
    def test_bad_dates_raise_value_error_naming_the_field(self, bad):
        with pytest.raises(ValueError, match="start"):
            to_com_date(_proj(), bad, field="start")

    def test_parse_iso_reports_whether_time_was_given(self):
        assert parse_iso("2031-06-01")[1] is False
        assert parse_iso("2031-06-01 09:00")[1] is True


class TestMinutesPerDay:
    def test_uses_hours_per_day(self):
        # Project has no MinutesPerDay property; a 10-hour day is 600 minutes.
        assert minutes_per_day(_proj(hours=10)) == 600

    def test_falls_back_to_480(self):
        proj = MagicMock()
        type(proj).HoursPerDay = property(lambda self: (_ for _ in ()).throw(Exception("x")))
        assert minutes_per_day(proj) == 480


class TestCommit:
    def test_saves_titled_active_project(self, monkeypatch):
        monkeypatch.delenv("MSPROJECT_AUTOSAVE", raising=False)
        app = MagicMock()
        proj = _proj()
        app.ActiveProject = proj
        assert commit(app, proj) is True
        app.FileSave.assert_called_once()

    def test_never_saves_untitled_project(self, monkeypatch):
        # FileSave on an untitled project opens Backstage Save As and blocks COM.
        monkeypatch.delenv("MSPROJECT_AUTOSAVE", raising=False)
        app = MagicMock()
        proj = _proj(path="")
        app.ActiveProject = proj
        assert commit(app, proj) is False
        app.FileSave.assert_not_called()

    @pytest.mark.parametrize("value", ["0", "false", "OFF"])
    def test_autosave_can_be_disabled(self, monkeypatch, value):
        monkeypatch.setenv("MSPROJECT_AUTOSAVE", value)
        app = MagicMock()
        app.ActiveProject = _proj()
        assert commit(app) is False
        app.FileSave.assert_not_called()

    def test_saves_non_active_project_and_restores_active(self, monkeypatch):
        monkeypatch.delenv("MSPROJECT_AUTOSAVE", raising=False)
        app = MagicMock()
        active, other = _proj(path="C:\\a.mpp"), _proj(path="C:\\b.mpp")
        app.ActiveProject = active
        active.Name, other.Name = "a.mpp", "b.mpp"
        projects = {"a.mpp": active, "b.mpp": other}

        def window_activate(WindowName):
            app.ActiveProject = projects[WindowName]
        app.WindowActivate.side_effect = window_activate
        commit(app, other)
        assert [c.kwargs["WindowName"] for c in app.WindowActivate.call_args_list] == ["b.mpp", "a.mpp"]
        app.FileSave.assert_called_once()
        assert app.ActiveProject is active


class TestBatchCalc:
    def test_restores_user_mode_and_recalculates_once(self):
        # never leave Project in Manual, never force a Manual user to Automatic.
        app = MagicMock()
        modes = [-1]
        type(app).Calculation = property(lambda self: modes[-1], lambda self, v: modes.append(v))
        with batch_calc(app):
            assert app.Calculation == 0
        assert app.Calculation == -1
        app.CalculateProject.assert_called_once()

    def test_manual_user_stays_manual_without_recalc(self):
        app = MagicMock()
        modes = [0]
        type(app).Calculation = property(lambda self: modes[-1], lambda self, v: modes.append(v))
        with batch_calc(app):
            pass
        assert app.Calculation == 0
        app.CalculateProject.assert_not_called()


class TestLookups:
    def _named(self, *names):
        items = []
        for i, n in enumerate(names, 1):
            m = MagicMock()
            m.Name, m.UniqueID = n, i
            items.append(m)
        return items

    def test_resolve_resource_is_case_insensitive_exact(self):
        proj = MagicMock()
        proj.Resources = self._named("Team", "Team Lead")
        assert resolve_resource(proj, "team").Name == "Team"

    def test_resolve_resource_rejects_ambiguous_names(self):
        proj = MagicMock()
        proj.Resources = self._named("Bob", "bob")
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_resource(proj, "BOB")

    def test_resolve_calendar_missing_lists_available(self):
        proj = MagicMock()
        proj.BaseCalendars = self._named("Standard")
        with pytest.raises(ValueError, match="Standard"):
            resolve_calendar(proj, "24 Hours")

    @pytest.mark.parametrize("value,expected", [("red", "Red"), (" Amber ", "Amber"), ("GREEN", "Green")])
    def test_validate_rag(self, value, expected):
        assert validate_rag(value) == expected

    def test_validate_rag_rejects_other_values(self):
        with pytest.raises(ValueError):
            validate_rag("purple")


class TestConstants:
    def test_timescales_match_pjtimescaleunit(self):
        # PjTimescaleUnit: Months=2, Weeks=3, Days=4.
        assert TIMESCALES == {"daily": 4, "weekly": 3, "monthly": 2}

    def test_link_types_match_pjtasklinktype(self):
        assert LINK_TYPES == {"FF": 0, "FS": 1, "SF": 2, "SS": 3}


class TestInvokePositional:
    def test_none_becomes_arg_not_found(self):
        pythoncom = pytest.importorskip("pythoncom")
        obj = MagicMock()
        obj._oleobj_.GetIDsOfNames.return_value = 42
        invoke_positional(obj, "FileSaveAs", "x.xml", None, "MSProject.XML")
        args = obj._oleobj_.Invoke.call_args[0]
        assert args[0] == 42
        assert args[4:] == ("x.xml", pythoncom.ArgNotFound, "MSProject.XML")
