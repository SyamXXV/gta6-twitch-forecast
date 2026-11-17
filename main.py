#!/usr/bin/env python3
"""Forecast Twitch viewers for a big game launch's release day, hour by hour.

Method: for every past launch in the case's `comparables`, take its release-day
ratio curve r_h = viewers(hour h) / viewers(hour 1) for h = 2..24.  For the case
at hand, the forecast for hour h is the case's own hour-1 print multiplied by
the distribution of those ratios across comparable launches, weighted by how
close each comparable's hour-1 magnitude is to the case's (a launch of 20k
viewers in hour 1 ramps differently from one of 800k).  In log space the
weighted mean and weighted standard deviation of the ratios give the five
quantiles directly.  When a comparable lacks an hour, it simply does not vote
for that hour; when too few comparables vote, that hour falls back to the
persistence forecast (hour 1's print, spread widening with the square root of
the hours elapsed).

Standard library only.  No network, no randomness, no clock: the same input
file always produces the same output bytes.
"""

import json
import math
import os
import sys
from datetime import datetime

# Standard-normal quantiles at the five required levels.
Z_SCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722)
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)

# A comparable whose hour-1 print is this many log units away from the case's
# still votes, but with a Gaussian weight that fades with the distance.
MAGNITUDE_SIGMA = 1.0

# Minimum number of voting comparables for an hour before we trust the ratio
# distribution; below that the hour uses the persistence fallback.
MIN_DONORS = 5

# Spread of the persistence fallback, in log units per sqrt(hour - 1).
PERSISTENCE_SPREAD = 0.15

# A ratio distribution never collapses to a point: keep a small floor on the
# log spread so the five quantiles stay distinct and honest.
MIN_LOG_SPREAD = 0.05

# The raw cross-launch spread is a little too wide: at a factor of 1.0 the
# 90% band covered 98% of practice hours and 92% of leave-one-out hours.
# Shrinking it to 0.8 brings coverage to about 0.92 on the practice cases and
# 0.88 leave-one-out, and lowers the pinball loss on both.
SPREAD_SHRINK = 0.8

MAX_VIEWERS = 1.0e9


def parse_time(text):
    """Parse an ISO-8601 UTC timestamp into a datetime (naive, UTC)."""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment


def hour_one_print(case):
    """Hour 1's viewer print, from `known` (a list with one row, or a dict)."""
    known = case.get("known")
    rows = known if isinstance(known, list) else [known]
    for row in rows:
        if not isinstance(row, dict):
            continue
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            return float(viewers)
    # Fall back to the last whole-hour mean before the checkpoint.
    hourly = case.get("history_hourly") or []
    for row in reversed(hourly):
        viewers = row.get("viewers") if isinstance(row, dict) else None
        if isinstance(viewers, (int, float)) and viewers > 0:
            return float(viewers)
    return 1.0


def comparable_curves(case):
    """Release-day viewer curves of the comparables.

    Returns a list of (hour_1_viewers, {hour: viewers}) with hours 1..24
    measured from each comparable's own day_start.  A comparable whose
    release day has no hour-1 point (for example the GTA VI category's own
    pre-release history, which ends before its release day) is skipped.
    """
    curves = []
    for comp in case.get("comparables") or []:
        try:
            day_start = parse_time(comp["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        by_hour = {}
        for point in comp.get("hourly") or []:
            try:
                moment = parse_time(point["from"])
                viewers = float(point["viewers"])
            except (KeyError, TypeError, ValueError):
                continue
            if viewers <= 0:
                continue
            delta_hours = (moment - day_start).total_seconds() / 3600.0
            hour = int(delta_hours) + 1
            if 1 <= hour <= 24 and hour not in by_hour:
                by_hour[hour] = viewers
        if 1 in by_hour:
            curves.append((by_hour[1], by_hour))
    curves.sort(key=lambda item: item[0])
    return curves


def weighted_mean_sd(pairs):
    """Weighted mean and population standard deviation of (value, weight)."""
    total_weight = sum(w for _, w in pairs)
    mean = sum(v * w for v, w in pairs) / total_weight
    variance = sum(w * (v - mean) ** 2 for v, w in pairs) / total_weight
    return mean, math.sqrt(max(variance, 0.0))


def persistence_row(hour, print_one):
    """House-style fallback: every hour stays at the hour-1 print."""
    spread = PERSISTENCE_SPREAD * math.sqrt(hour - 1)
    return [print_one * math.exp(z * spread) for z in Z_SCORES]


def forecast_case(case):
    """Build the 23 forecast rows for one case."""
    print_one = max(hour_one_print(case), 1.0)
    donors = comparable_curves(case)
    log_print_one = math.log(print_one)

    rows = []
    for hour in range(2, 25):
        votes = []
        for donor_one, by_hour in donors:
            hour_viewers = by_hour.get(hour)
            if hour_viewers is None:
                continue
            log_ratio = math.log(hour_viewers) - math.log(donor_one)
            distance = abs(log_print_one - math.log(donor_one))
            weight = math.exp(-0.5 * (distance / MAGNITUDE_SIGMA) ** 2)
            votes.append((log_ratio, weight))
        if len(votes) < MIN_DONORS:
            quantiles = persistence_row(hour, print_one)
        else:
            centre, spread = weighted_mean_sd(votes)
            spread = max(spread, MIN_LOG_SPREAD) * SPREAD_SHRINK
            quantiles = [print_one * math.exp(centre + z * spread)
                         for z in Z_SCORES]
        # Clamp to the allowed range and keep the row non-decreasing after
        # rounding to two decimals (rounding alone could tie neighbours).
        cleaned = []
        previous = 0.0
        for value in quantiles:
            value = min(max(value, 1.0), MAX_VIEWERS)
            value = round(value, 2)
            if value < previous:
                value = previous
            cleaned.append(value)
            previous = value
        rows.append({"hour": hour, "q": cleaned})
    return {"hours": rows}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(output_dir, exist_ok=True)

    names = sorted(name for name in os.listdir(input_dir)
                   if name.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        forecast = forecast_case(case)
        stem = name[:-3]
        out_path = os.path.join(output_dir, stem + ".out")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(forecast, handle, separators=(",", ":"))
            handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
