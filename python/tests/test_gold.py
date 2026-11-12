from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data" / "gold"
if not GOLD.exists():
    pytest.skip("data/gold not found: build the pipeline or download the data first",
                allow_module_level=True)


@pytest.fixture(scope="module")
def daily():
    return pd.read_parquet(GOLD / "fact_daily_energy.parquet")


@pytest.fixture(scope="module")
def dim_station():
    return pd.read_parquet(GOLD / "dim_station.parquet")


def test_all_gold_tables_exist():
    expected = ["dim_date", "dim_device", "dim_station", "dim_state",
                "fact_readings", "fact_daily_energy"]
    missing = [t for t in expected if not (GOLD / f"{t}.parquet").exists()]
    assert missing == [], f"Missing gold tables: {missing}"


def test_daily_energy_is_never_negative(daily):
    assert (daily["energy_kwh"] >= 0).all()


def test_daily_energy_is_below_physical_limit(daily):
    assert daily["energy_kwh"].max() <= 55*24


def test_one_row_per_device_per_day(daily):
    assert not daily.duplicated(["date_key", "device_hash_id"]).any()


def test_every_row_belongs_to_a_known_station(daily, dim_station):
    assert daily["station_hash_id"].isin(dim_station["station_hash_id"]).all()


def test_solis_station_1_may_2025(daily, dim_station):
    station = dim_station.loc[dim_station["name"] == "SOLIS Station 1", "station_hash_id"].iloc[0]
    may = daily[(daily["station_hash_id"] == station) & (daily["date_key"] // 100 == 202505)]
    assert may["energy_kwh"].sum() == pytest.approx(271033, abs=1)