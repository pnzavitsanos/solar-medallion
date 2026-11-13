import pandas as pd

MISSING = ["", "NULL", "N/A"]


def to_number(text):
    text = text.str.replace(",", ".", regex=False)
    text = text.mask(text.isin(MISSING))
    return pd.to_numeric(text)


def clean_device_id(ids):
    return ids.str.strip().str.lower()


def drop_resent_duplicates(readings):
    readings = readings.sort_values("source_file")
    return readings.drop_duplicates(subset=["device_hash_id", "ts"], keep="last")


def flag_impossible_values(readings):
    readings = readings.copy()
    readings["bad_temperature"] = readings["temperature_c"] > 100
    readings["bad_counter"] = readings["energy_total_kwh"] == 0
    readings["too_much_power"] = readings["ac_power_kw"] > readings["max_power"] * 2
    readings["bad_energy_today"] = readings["energy_today_kwh"] > readings["max_power"] * 24
    return readings