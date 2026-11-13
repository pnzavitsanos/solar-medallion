# Fault injection

The two vendor files published with the SolarMagix paper
(`fusionsolar_energy_production.csv` and `solis_energy_production.csv`)
were already half-cleaned by the authors. This folder turns them back into
what the vendor APIs most likely delivered, so our own Bronze, Silver and
Gold layers have real work to do, and every problem has a known answer.

## How to run

From the SOLAR folder, with the virtual environment active:

```powershell
python fault_injection/inject_faults.py
```

It takes about a minute. It is safe to run again: the seed is fixed, so it
produces exactly the same files every time, and it clears its own output
folders first.

## Where things go

```
SOLAR/
├── fault_injection/
│   ├── README.md            this file
│   └── inject_faults.py     the script
└── data/                    (ignored by git, rebuilt by scripts)
    ├── raw/v2/              untouched Mendeley download (python/src/ingest.py)
    ├── landing/             messy vendor exports  <- Bronze reads this
    │   ├── fusionsolar/     fusionsolar_YYYY-MM-DD.csv, one per day
    │   └── solis/           solis_YYYY-MM-DD.csv, one per day
    └── answer_key/          what was broken       <- only for grading Silver
        ├── faults_log.csv   one line per damaged row
        ├── file_faults.csv  faults that affect a whole file
        ├── removed_rows.csv rows deleted to create gaps
        ├── authors_flags.csv rows the authors flagged as bad (natural problems)
        └── summary.csv      counts per fault type
```

`data/raw` is never modified. Don't open `answer_key` while you build the
Silver layer; use it afterwards to score how many faults you caught.

## What the vendor documentation would tell you

This is the knowledge a data engineer would normally get from the vendors'
API docs. It is fair to use while building Bronze and Silver.

| | FusionSolar | Solis |
| --- | --- | --- |
| Files | one CSV per UTC day | one CSV per local day |
| Device id column | `device_id` | `inverter_id` |
| Time column | `collect_time`, epoch **milliseconds**, UTC | `timestamp`, local time **UTC+01:00**, no offset written |
| AC power | `active_power`, kW | `total_ac_power`, kW |
| DC power | `dc_power`, kW | `dc_power`, kW |
| Efficiency | `efficiency`, % | not provided |
| Energy today (running total) | `day_cap`, kWh | `eToday`, kWh |
| Lifetime energy | `total_cap`, kWh | `eTotal`, kWh |
| Inverter temperature | `temperature`, °C | `temperature`, °C |
| State code | `inverter_state` (see mapping table) | `state` (see mapping table) |
| Reading interval | about 5 minutes | irregular |

Neither vendor sends the energy produced per reading. Like the authors,
we have to calculate it from the running totals.

## The faults (spoilers)

Each fault copies a problem the paper reports for these vendors, or a common
problem with vendor exports.

| Fault | What happens | Where the idea comes from |
| --- | --- | --- |
| Vendor schema | Vendor column names; the authors' derived columns (`prev_*`, `data_status`, `produced_energy`, Solis `efficiency`) are removed | Paper §4.1.4, Table 8 |
| Different time formats | FusionSolar epoch ms in UTC, Solis local time UTC+01:00 | Paper §4.1.2.1 |
| Daily files | One file per vendor per day, like daily API batches | Paper §4.1 (daily incremental loads) |
| Gaps | 1% of device-days lose a 1 to 4 hour block | Paper §4.1.3.1.1 (missing data) |
| Late-arriving re-sends | 30% of files repeat each device's last 2 hours of readings from the previous file | Paper §4.1.2 (overlapping fetches) |
| Preliminary values | 5% of re-sent readings had a wrong `ac_power` in the first delivery; the re-send is correct | Paper §4.1.2 (source-side corrections) |
| Duplicates in a file | 0.2% of rows appear twice in the same file | Common |
| Missing values | 0.3% of rows lose one measurement: empty cell (FusionSolar), `NULL` or `N/A` (Solis) | Common |
| Sensor overflow | 0.02% of rows show temperature 6553.5 | Common (0xFFFF / 10) |
| Counter glitch | 0.03% of rows show the lifetime counter as 0 | Paper §4.1.3.1.2 (counter consistency) |
| Unknown state | 0.05% of rows have a state code not in the mapping table | Common |
| Messy device ids | 0.2% of ids have extra spaces (FusionSolar) or upper case (Solis) | Common |
| Unknown device | A FusionSolar device that is not in `devices.csv` appears for a few days | Common |
| Watts instead of kW | One FusionSolar station sends power in W for one month | Common (API change) |
| European number format | 5% of Solis files use `;` as separator and `,` as decimal mark | Common (locale export) |
| Day-first dates | 5% of Solis files write dates as dd/mm/yyyy | Common |
| Row order | Rows inside every file are shuffled | Common |

The files also contain the natural problems that were already in the data,
such as efficiency above 100%, negative power or a Solis temperature of
3276.7. Those are not in `faults_log.csv`, because we did not create them.
`authors_flags.csv` lists the rows the authors themselves flagged as bad
(their `data_status = 1`), so you can compare your Silver checks with theirs.

## Changing the faults

All rates are in the `RATES` dictionary at the top of `inject_faults.py`.
Change a number and run the script again. Change `SEED` to get a different
but still reproducible set of faults.
