"""
Fault injection for the SOLAR project.

The two "raw" vendor files published with the SolarMagix paper were already
half-cleaned by the authors: renamed columns, UTC timestamps, no duplicates,
and four extra columns they calculated themselves. This script turns them
back into what the vendor APIs most likely delivered: messy daily exports.

    Input  (never modified):
        data/raw/v2/fusionsolar_energy_production.csv
        data/raw/v2/solis_energy_production.csv

    Output:
        data/landing/fusionsolar/fusionsolar_YYYY-MM-DD.csv   one file per day
        data/landing/solis/solis_YYYY-MM-DD.csv               one file per day
        data/answer_key/...                                   what was broken

Bronze reads data/landing. The answer key is only for grading Silver later,
so don't look at it while you build the cleaning logic.

Run it from the SOLAR folder:
    python fault_injection/inject_faults.py

Every fault is described in fault_injection/README.md.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

SEED = 700  # same seed = same faults on every run

# __file__ is the path of this script, so ROOT is found no matter which
# folder you run it from: fault_injection/ -> one level up = SOLAR
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "v2"
LANDING_DIR = ROOT / "data" / "landing"
ANSWER_DIR = ROOT / "data" / "answer_key"

# How often each fault happens (share of rows, files or device-days)
RATES = {
    "gap_device_days": 0.01,       # device-days that lose a 1-4 hour block
    "resend_files": 0.30,          # daily files that repeat the previous day's last 2 hours
    "resend_hours": 2,
    "preliminary_values": 0.05,    # of re-sent rows: first delivery had a wrong value
    "in_file_duplicates": 0.002,   # rows that appear twice in the same file
    "null_values": 0.003,          # rows with one measurement missing
    "sensor_overflow": 0.0002,     # temperature reads 6553.5 (0xFFFF / 10)
    "counter_glitch": 0.0003,      # lifetime counter drops to 0 for one reading
    "unknown_state": 0.0005,       # state code that is not in the mapping table
    "messy_device_id": 0.002,      # extra spaces or upper case in the device id
    "solis_comma_decimal": 0.05,   # Solis files exported with ; and decimal comma
    "solis_day_first_dates": 0.05, # Solis files with dd/mm/yyyy timestamps
}

ORPHAN_DEVICE_ID = "0000deadbeef0000deadbeef00000000"  # not in devices.csv
ORPHAN_DAYS = 3
SOLIS_UTC_OFFSET = pd.Timedelta(hours=1)  # Solis returns local time, UTC+01:00

# The authors' own columns: no vendor sends these, so they are removed
DERIVED_COLUMNS = ["prev_cumsum_today", "prev_measured_ts", "prev_ts",
                   "data_status", "produced_energy"]

# Vendor column names, from paper Table 8 (our name -> vendor name)
VENDOR_NAMES = {
    "fusionsolar": {
        "device_hash_id": "device_id",
        "measured_ts": "collect_time",
        "ac_power": "active_power",
        "cumsum_today": "day_cap",
        "cumsum_total": "total_cap",
        "state": "inverter_state",
    },
    "solis": {
        "device_hash_id": "inverter_id",
        "measured_ts": "timestamp",
        "ac_power": "total_ac_power",
        "cumsum_today": "eToday",
        "cumsum_total": "eTotal",
    },
}

MEASURES = ["ac_power", "dc_power", "efficiency", "cumsum_today",
            "cumsum_total", "temperature"]

rng = np.random.default_rng(SEED)
fault_log = []   # small tables of row-level faults
file_log = []    # one dict per file-level fault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log_rows(rows, vendor, fault_type, column, original, injected):
    """Write one answer-key entry per affected row."""
    if len(rows) == 0:
        return
    fault_log.append(pd.DataFrame({
        "vendor": vendor,
        "file": rows["_file"].to_numpy(),
        "device_hash_id": rows["_true_id"].to_numpy(),
        "measured_ts_utc": rows["_true_ts"].to_numpy(),
        "fault_type": fault_type,
        "column": column,
        "original_value": list(original),
        "injected_value": list(injected),
    }))


def pick(index, share):
    """Pick a random share of an index (at least 0 rows)."""
    n = int(round(len(index) * share))
    return rng.choice(index, size=n, replace=False) if n else index[:0]


# ---------------------------------------------------------------------------
# Fault steps (each step works on one vendor table)
# ---------------------------------------------------------------------------

def remove_gaps(df, vendor):
    """Delete a 1-4 hour block for some device-days: data that never arrived."""
    df["_day"] = df["_ts"].dt.floor("D")
    device_days = df[["device_hash_id", "_day"]].drop_duplicates()
    chosen = device_days.sample(frac=RATES["gap_device_days"], random_state=SEED)

    drop_idx = []
    for _, dd in chosen.iterrows():
        start = dd["_day"] + pd.Timedelta(hours=int(rng.integers(5, 15)))
        end = start + pd.Timedelta(hours=int(rng.integers(1, 5)))
        mask = ((df["device_hash_id"] == dd["device_hash_id"])
                & (df["_ts"] >= start) & (df["_ts"] < end))
        drop_idx.extend(df.index[mask])

    removed = df.loc[drop_idx].assign(vendor=vendor)
    return df.drop(index=drop_idx).drop(columns="_day"), removed


def add_orphan_device(df, vendor):
    """Copy a few days of one real inverter under an id that is not registered."""
    source_id = df["device_hash_id"].iloc[0]
    days = sorted(df.loc[df["device_hash_id"] == source_id, "_ts"].dt.floor("D").unique())
    start = pd.Timestamp(days[len(days) // 2])
    end = start + pd.Timedelta(days=ORPHAN_DAYS)
    copy = df[(df["device_hash_id"] == source_id)
              & (df["_ts"] >= start) & (df["_ts"] < end)].copy()
    copy["device_hash_id"] = ORPHAN_DEVICE_ID
    copy["_true_id"] = "(not a real device)"
    copy["_orphan"] = True
    return pd.concat([df, copy], ignore_index=True), source_id, start, end


def assign_files(df, vendor):
    """Each row goes into the daily file of its (vendor-local) date."""
    local = df["_ts"] + (SOLIS_UTC_OFFSET if vendor == "solis" else pd.Timedelta(0))
    df["_file_day"] = local.dt.floor("D")
    df["_file"] = vendor + "_" + df["_file_day"].dt.strftime("%Y-%m-%d") + ".csv"
    return df


def add_resends(df, vendor):
    """Late-arriving data: the fetcher asks for a window that overlaps the
    previous delivery, so some files repeat each device's last hours from the
    previous file (a per-device look-back: counted from that device's last
    reading, because inverters sleep at night).
    For a few re-sent rows the FIRST delivery was preliminary (wrong) and the
    re-send carries the correct value, so 'latest file wins' is the right rule."""
    days = sorted(df["_file_day"].unique())
    chosen_days = pick(np.array(days[1:]), RATES["resend_files"])
    device_last = df.groupby(["_file_day", "_true_id"])["_ts"].transform("max")
    cutoff = device_last - pd.Timedelta(hours=RATES["resend_hours"])
    copies = []
    for day in chosen_days:
        day = pd.Timestamp(day)
        prev_day = day - pd.Timedelta(days=1)
        mask = (df["_file_day"] == prev_day) & (df["_ts"] > cutoff) & (~df["_orphan"])
        c = df[mask].copy()
        c["_file_day"] = day
        c["_file"] = vendor + "_" + day.strftime("%Y-%m-%d") + ".csv"
        c["_resend"] = True
        copies.append(c)
    resent = pd.concat(copies) if copies else df.iloc[:0]

    # log the duplicates
    log_rows(resent, vendor, "duplicate_resend", "(whole row)",
             ["previous day's file"] * len(resent), ["repeated in this file"] * len(resent))

    # preliminary values: change ac_power in the ORIGINAL (earlier) row
    originals = df.index[df.set_index(["_true_id", "_true_ts"]).index.isin(
        resent.set_index(["_true_id", "_true_ts"]).index)]
    prelim_idx = pick(originals, RATES["preliminary_values"])
    old = df.loc[prelim_idx, "ac_power"]
    factor = rng.uniform(0.80, 0.95, size=len(prelim_idx))
    new = (old * factor).round(3)
    df.loc[prelim_idx, "ac_power"] = new
    log_rows(df.loc[prelim_idx], vendor, "preliminary_value", "ac_power", old, new)

    return pd.concat([df, resent], ignore_index=True)


def inject_values(df, vendor):
    """Row-level value faults on first deliveries of real devices."""
    target = df.index[~df["_resend"] & ~df["_orphan"]]
    measures = [m for m in MEASURES if m in df.columns]
    df[measures + ["state"]] = df[measures + ["state"]].astype(object)

    # missing values: one random measurement per chosen row
    idx = pick(target, RATES["null_values"])
    cols = rng.choice(measures, size=len(idx))
    for col in measures:
        rows = idx[cols == col]
        if vendor == "fusionsolar":
            markers = [""] * len(rows)               # FusionSolar: empty cell
        else:
            markers = list(rng.choice(["NULL", "NULL", "N/A"], size=len(rows)))
        log_rows(df.loc[rows], vendor, "missing_value", col, df.loc[rows, col],
                 [m or "(empty)" for m in markers])
        df.loc[rows, col] = markers

    # sensor overflow
    idx = pick(target, RATES["sensor_overflow"])
    log_rows(df.loc[idx], vendor, "sensor_overflow", "temperature",
             df.loc[idx, "temperature"], [6553.5] * len(idx))
    df.loc[idx, "temperature"] = 6553.5

    # lifetime counter drops to zero
    idx = pick(target, RATES["counter_glitch"])
    log_rows(df.loc[idx], vendor, "counter_glitch", "cumsum_total",
             df.loc[idx, "cumsum_total"], [0] * len(idx))
    df.loc[idx, "cumsum_total"] = 0

    # unknown state code
    bad_state = 9999 if vendor == "fusionsolar" else 4
    idx = pick(target, RATES["unknown_state"])
    log_rows(df.loc[idx], vendor, "unknown_state", "state",
             df.loc[idx, "state"], [bad_state] * len(idx))
    df.loc[idx, "state"] = bad_state

    # messy device ids
    idx = pick(target, RATES["messy_device_id"])
    old = df.loc[idx, "device_hash_id"]
    new = [f"  {v} " if vendor == "fusionsolar" else v.upper() for v in old]
    log_rows(df.loc[idx], vendor, "messy_device_id", "device_hash_id", old, new)
    df.loc[idx, "device_hash_id"] = new
    return df


def add_in_file_duplicates(df, vendor):
    """The same reading twice inside one file."""
    idx = pick(df.index[~df["_resend"]], RATES["in_file_duplicates"])
    dups = df.loc[idx].copy()
    log_rows(dups, vendor, "duplicate_in_file", "(whole row)",
             ["once"] * len(dups), ["twice"] * len(dups))
    return pd.concat([df, dups], ignore_index=True)


def watts_instead_of_kilowatts(df, devices):
    """FusionSolar: one station reports power in W instead of kW for a month."""
    fs_stations = devices.loc[devices["device_hash_id"].isin(df["_true_id"]), "station_hash_id"]
    station = sorted(fs_stations.unique())[int(rng.integers(0, fs_stations.nunique()))]
    station_devices = devices.loc[devices["station_hash_id"] == station, "device_hash_id"]
    months = sorted(df["_file_day"].dt.to_period("M").unique())
    month = months[len(months) // 2]

    mask = df["_true_id"].isin(station_devices) & (df["_file_day"].dt.to_period("M") == month)
    for col in ["ac_power", "dc_power"]:
        numeric = pd.to_numeric(df.loc[mask, col], errors="coerce")
        df.loc[mask, col] = (numeric * 1000).round(1).where(numeric.notna(), df.loc[mask, col])
    for f in sorted(df.loc[mask, "_file"].unique()):
        file_log.append({"vendor": "fusionsolar", "file": f, "fault_type": "watts_not_kilowatts",
                         "detail": f"rows of station {station}: active_power and dc_power in W"})
    return df


# ---------------------------------------------------------------------------
# Formatting and writing
# ---------------------------------------------------------------------------

def format_timestamps(df, vendor):
    if vendor == "fusionsolar":
        # FusionSolar API: collectTime in epoch milliseconds (UTC)
        df["measured_ts"] = (df["_ts"] - pd.Timestamp("1970-01-01")) // pd.Timedelta(milliseconds=1)
    else:
        # Solis: local time UTC+01:00, with no offset written in the file
        df["measured_ts"] = (df["_ts"] + SOLIS_UTC_OFFSET).dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def write_files(df, vendor):
    out_dir = LANDING_DIR / vendor
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.csv"):   # start clean on every run
        old.unlink()

    files = sorted(df["_file"].unique())
    comma_files = set(pick(np.array(files), RATES["solis_comma_decimal"])) if vendor == "solis" else set()
    dayfirst_files = set(pick(np.array(files), RATES["solis_day_first_dates"])) if vendor == "solis" else set()

    keep = [c for c in df.columns if not c.startswith("_")]
    for name, part in df.groupby("_file"):
        part = part.sample(frac=1, random_state=SEED)[keep]  # APIs don't promise row order
        sep = ","
        if name in dayfirst_files:
            ts = pd.to_datetime(part["measured_ts"])
            part = part.assign(measured_ts=ts.dt.strftime("%d/%m/%Y %H:%M:%S"))
            file_log.append({"vendor": vendor, "file": name, "fault_type": "day_first_dates",
                             "detail": "timestamps written as dd/mm/yyyy HH:MM:SS"})
        if name in comma_files:
            measure_cols = [VENDOR_NAMES[vendor].get(c, c) for c in MEASURES if c in df.columns]
            part = part.rename(columns=VENDOR_NAMES[vendor])
            for c in measure_cols:
                part[c] = part[c].astype(str).str.replace(".", ",", regex=False).replace("nan", "")
            sep = ";"
            file_log.append({"vendor": vendor, "file": name, "fault_type": "comma_decimal",
                             "detail": "separator ; and decimal comma (European locale export)"})
        else:
            part = part.rename(columns=VENDOR_NAMES[vendor])
        part.to_csv(out_dir / name, index=False, sep=sep)
    return len(files)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(vendor, devices):
    print(f"\n=== {vendor} ===")
    df = pd.read_csv(RAW_DIR / f"{vendor}_energy_production.csv")
    print(f"raw rows: {len(df):,}")

    # keep the authors' own quality flags (data_status = 1) as a reference
    # for the natural problems that were already in the data
    flagged = df.loc[df["data_status"] == 1, ["device_hash_id", "measured_ts"]]
    flagged = flagged.assign(vendor=vendor)

    df = df.drop(columns=[c for c in DERIVED_COLUMNS if c in df.columns])
    if vendor == "solis":
        df = df.drop(columns=["efficiency"])  # Solis does not send it; the authors derived it
    file_log.append({"vendor": vendor, "file": "(all files)", "fault_type": "vendor_schema",
                     "detail": "vendor column names; authors' derived columns removed"})

    df["_true_id"] = df["device_hash_id"]
    df["_true_ts"] = df["measured_ts"]
    df["_ts"] = pd.to_datetime(df["measured_ts"], utc=True).dt.tz_localize(None)
    df["_orphan"] = False
    df["_resend"] = False

    df, removed = remove_gaps(df, vendor)
    print(f"rows removed as gaps: {len(removed):,}")

    df = assign_files(df, vendor)
    if vendor == "fusionsolar":
        df, src, start, end = add_orphan_device(df, vendor)
        df = assign_files(df, vendor)
        orphan_files = sorted(df.loc[df["_orphan"], "_file"].unique())
        for f in orphan_files:
            file_log.append({"vendor": vendor, "file": f, "fault_type": "unknown_device",
                             "detail": f"device {ORPHAN_DEVICE_ID} is not in devices.csv "
                                       f"(copy of {src})"})

    df = add_resends(df, vendor)
    df = inject_values(df, vendor)
    df = add_in_file_duplicates(df, vendor)
    if vendor == "fusionsolar":
        df = watts_instead_of_kilowatts(df, devices)

    df = format_timestamps(df, vendor)
    n_files = write_files(df, vendor)
    print(f"landing rows: {len(df):,} in {n_files} daily files")
    return removed, flagged


def main():
    devices = pd.read_csv(RAW_DIR / "devices.csv")
    results = [process(v, devices) for v in ["fusionsolar", "solis"]]
    removed = [r[0] for r in results]
    flagged = pd.concat([r[1] for r in results], ignore_index=True)

    ANSWER_DIR.mkdir(parents=True, exist_ok=True)
    faults = pd.concat(fault_log, ignore_index=True)
    faults.insert(0, "fault_id", range(1, len(faults) + 1))
    faults.to_csv(ANSWER_DIR / "faults_log.csv", index=False)
    pd.DataFrame(file_log).to_csv(ANSWER_DIR / "file_faults.csv", index=False)
    flagged.to_csv(ANSWER_DIR / "authors_flags.csv", index=False)

    removed = pd.concat(removed)
    keep = [c for c in removed.columns if not c.startswith("_")]
    removed[keep].to_csv(ANSWER_DIR / "removed_rows.csv", index=False)

    summary = pd.concat([
        faults.groupby(["vendor", "fault_type"]).size().reset_index(name="count")
              .assign(counted_in="rows"),
        removed.groupby("vendor").size().reset_index(name="count")
               .assign(fault_type="gap_removed", counted_in="rows"),
        pd.DataFrame(file_log).groupby(["vendor", "fault_type"]).size()
          .reset_index(name="count").assign(counted_in="files"),
    ], ignore_index=True).sort_values(["vendor", "counted_in", "fault_type"])
    summary.to_csv(ANSWER_DIR / "summary.csv", index=False)
    print("\n=== summary ===")
    print(summary.to_string(index=False))
    print(f"\nLanding files: {LANDING_DIR}")
    print(f"Answer key:    {ANSWER_DIR}")


if __name__ == "__main__":
    main()
