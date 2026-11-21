"""
File: Cully/modules/web/tests/check_settings.py
Description: Checks Settings to_dict, update, save and validation on a temp settings file, never the
real one.

Run from Cully/modules with either venv:
    python -m web.tests.check_settings
Author: Miguel Macias
Date: 2026-11-16
"""

from pathlib import Path
import json
import tempfile

from config.settings import DEFAULT_SETTINGS, Settings


def fresh(folder: str) -> Settings:
    return Settings(path=Path(folder) / "settings.json")


def raises(settings: Settings, values: dict) -> bool:
    """True if update raises ValueError and leaves the settings unchanged."""
    before = settings.to_dict()
    try:
        settings.update(values)
    except ValueError:
        return settings.to_dict() == before
    return False


def test_defaults_round_trip():
    with tempfile.TemporaryDirectory() as folder:
        settings = fresh(folder)
        assert settings.to_dict() == DEFAULT_SETTINGS
        on_disk = json.loads(settings.path.read_text())
        assert on_disk == DEFAULT_SETTINGS


def test_to_dict_is_a_copy():
    with tempfile.TemporaryDirectory() as folder:
        settings = fresh(folder)
        settings.to_dict()["ranking"]["eye_gate"] = 0.6
        assert settings.ranking["eye_gate"] == DEFAULT_SETTINGS["ranking"]["eye_gate"]


def test_update_save_reload():
    with tempfile.TemporaryDirectory() as folder:
        settings = fresh(folder)
        settings.update({"ranking": {"eye_gate": 0.5, "eye_check": False}, "object_threshold": 60})
        settings.save()
        assert not settings.path.with_suffix(".tmp").exists()
        loaded = fresh(folder)
        assert loaded.ranking["eye_gate"] == 0.5
        assert loaded.ranking["eye_check"] is False
        # Keys not in the update are kept
        assert loaded.ranking["ear_floor"] == DEFAULT_SETTINGS["ranking"]["ear_floor"]
        assert loaded.object_threshold == 60


def test_types_are_kept():
    with tempfile.TemporaryDirectory() as folder:
        settings = fresh(folder)
        # An int is fine for a float setting, and is stored as a float
        settings.update({"ranking": {"eye_gate": 1, "max_candidates": 3}})
        assert isinstance(settings.ranking["eye_gate"], float)
        assert isinstance(settings.ranking["max_candidates"], int)
        assert raises(settings, {"ranking": {"max_candidates": 3.0}})  # a float is not fine for an int


def test_bad_values_raise_and_change_nothing():
    with tempfile.TemporaryDirectory() as folder:
        settings = fresh(folder)
        bad = [
            {"nope": 1},  # unknown key
            {"ranking": {"nope": 1}},  # unknown sub-key
            {"ranking": 0.5},  # a group needs a dict
            {"ranking": {"eye_gate": 1.5}},  # out of range
            {"ranking": {"eye_gate": 0.5, "ear_floor": -1}},  # second value bad, first must not stick
            {"detection": {"object_scale": 0}},
            {"grouping": {"burst_gap_seconds": 0}},
            {"ranking": {"max_candidates": -1}},
            {"ranking": {"max_candidates": 2.5}},  # an int setting
            {"ranking": {"eye_check": "true"}},  # a bool needs a bool
            {"object_threshold": "70"},  # a number needs a number
            {"object_threshold": True},
            {"hardware": {"device": "gpu"}},
        ]
        for values in bad:
            assert raises(settings, values), values


def test_bad_file_raises():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "settings.json"
        values = json.loads(json.dumps(DEFAULT_SETTINGS))
        values["ranking"]["candidate_margin"] = 2
        path.write_text(json.dumps(values))
        try:
            Settings(path=path)
            raise AssertionError("candidate_margin 2 should raise")
        except ValueError:
            pass


if __name__ == "__main__":
    tests = [value for name, value in dict(globals()).items() if name.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as e:  # a missing method shows as a failure, not a crash
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
