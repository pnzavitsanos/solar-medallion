import pandas as pd
import pytest

from src.silver_rules import to_number, clean_device_id, drop_resent_duplicates, flag_impossible_values


def test_to_number_handles_commas_and_missing_markers():
    result = to_number(pd.Series(["32,6", "NULL", "N/A", "", "7"]))
    assert result.iloc[0] == 32.6
    assert result.iloc[1:4].isna().all()
    assert result.iloc[4] == 7


def test_to_number_stops_on_unexpected_text():
    with pytest.raises(ValueError):
        to_number(pd.Series(["12", "abc"]))


def test_clean_device_id_removes_spaces_and_capitals():
    result = clean_device_id(pd.Series(["  94AEDD81 ", "abc"]))
    assert list(result) == ["94aedd81", "abc"]


def test_resent_reading_keeps_latest_file():
    readings = pd.DataFrame({
        "device_hash_id": ["inv1", "inv1", "inv2"],
        "ts": ["10:00", "10:00", "10:00"],
        "ac_power_kw": [5.0, 6.0, 7.0],
        "source_file": ["day_2025-01-02.csv", "day_2025-01-01.csv", "day_2025-01-01.csv"],
    })
    result = drop_resent_duplicates(readings)
    assert len(result) == 2
    kept = result[result["device_hash_id"] == "inv1"]
    assert kept["ac_power_kw"].item() == 5.0


def test_flags_catch_each_impossible_value():
    readings = pd.DataFrame({
        "temperature_c":    [40.0, 6553.5, 40.0, 40.0, 40.0],
        "energy_total_kwh": [1000, 1000, 0, 1000, 1000],
        "ac_power_kw":      [30.0, 30.0, 30.0, 55000, 30.0],
        "energy_today_kwh": [200, 200, 200, 200, 39086239],
        "max_power":        [50.0, 50.0, 50.0, 50.0, 50.0],
    })
    result = flag_impossible_values(readings)
    assert list(result["bad_temperature"]) == [False, True, False, False, False]
    assert list(result["bad_counter"]) == [False, False, True, False, False]
    assert list(result["too_much_power"]) == [False, False, False, True, False]
    assert list(result["bad_energy_today"]) == [False, False, False, False, True]