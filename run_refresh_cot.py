"""Refresh the NQ COT input actually consumed by Quant Lab 2.

The old workflow downloaded ZIPs but never rebuilt cot_weekly.csv. Preserve
published rows, append validated observations by stable CFTC contract code,
and leave the prior file intact on failure. Survey dates are not release dates.
"""
import io
import json
from pathlib import Path
import zipfile

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
CONTRACT = "20974+"  # NASDAQ-100 Consolidated; verified against the CFTC archive
COLUMNS = {"As of Date in Form YYYY-MM-DD": "date", "Open Interest (All)": "oi",
           "Noncommercial Positions-Long (All)": "nc_long",
           "Noncommercial Positions-Short (All)": "nc_short",
           "Commercial Positions-Long (All)": "c_long",
           "Commercial Positions-Short (All)": "c_short"}


def parse_archive(content, now):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith((".txt", ".csv"))]
        if len(members) != 1:
            raise ValueError("Expected one CFTC data member")
        frame = pd.read_csv(archive.open(members[0]), low_memory=False,
                            dtype={"CFTC Contract Market Code": str})
    frame.columns = frame.columns.str.strip()
    frame = frame.loc[frame["CFTC Contract Market Code"].str.strip() == CONTRACT, list(COLUMNS)].rename(columns=COLUMNS)
    if frame.empty:
        raise ValueError("NQ consolidated contract absent from CFTC archive")
    frame["date"] = pd.to_datetime(frame.date)
    frame["sym"] = "NQ"
    for column in ("oi", "nc_long", "nc_short", "c_long", "c_short"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if frame[column].isna().any() or (frame[column] < 0).any():
            raise ValueError("Invalid COT position count")
    if (frame.oi <= 0).any() or frame.date.duplicated().any():
        raise ValueError("Invalid COT open interest or duplicate dates")
    today = pd.Timestamp(now).tz_localize(None).normalize()
    if (frame.date > today).any():
        raise ValueError("Future-dated COT observation")
    return frame.sort_values("date")


def main(root=ROOT, now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    path = root / "data/external/cot_weekly.csv"
    old = pd.read_csv(path, parse_dates=["date"])
    last = old.loc[old.sym == "NQ", "date"].max()
    additions = []
    for year in range(last.year, now.year + 1):
        url = f"https://www.cftc.gov/files/dea/history/deacot{year}.zip"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        additions.append(parse_archive(response.content, now))
    latest = pd.concat(additions, ignore_index=True)
    latest = latest[latest.date > last]
    updated = pd.concat([old, latest], ignore_index=True).sort_values(["sym", "date"])
    if updated.duplicated(["sym", "date"]).any():
        raise ValueError("Duplicate symbol/date in COT input")
    temp = path.with_suffix(".tmp")
    updated.to_csv(temp, index=False)
    temp.replace(path)
    end = updated.loc[updated.sym == "NQ", "date"].max()
    result = {"checked_utc": now.isoformat(), "added": len(latest),
              "latest_survey_date": str(end.date()), "contract_code": CONTRACT,
              "release_dates_verified": False}
    (root / "research/cot_feed.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if (now.tz_localize(None) - end).days <= 25 else 1


if __name__ == "__main__":
    raise SystemExit(main())
