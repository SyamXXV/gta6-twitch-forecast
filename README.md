# GTA VI launch-day Twitch forecast

A forecaster for `gta6-twitch-ccu-forecast-01`: from the first hour's Twitch
viewer count of Grand Theft Auto VI's release day (2026-11-19 UTC), it predicts
the viewer count in each of hours 2–24 as five quantiles (5%, 25%, 50%, 75%,
95%).

## Method

Past big launches ramp through a release day in a similar shape once you
divide by their first hour: `r_h = viewers(hour h) / viewers(hour 1)`. The
program takes every comparable launch in the case file, builds its ratio
curve, and for each hour h forecasts the case's hour-1 print times the
distribution of those ratios — in log space, the weighted mean and weighted
standard deviation of the ratios, weighted by how close the comparable's
hour-1 magnitude is to the case's (Gaussian weight, sigma 1.0 in log units:
a 20k-viewer launch ramps differently from an 800k one). Quantiles are the
weighted mean plus the standard-normal z-scores times the spread, with the
spread shrunk by 0.8: the raw cross-launch spread is slightly too wide
(coverage 0.98 on the practice cases at 1.0; 0.8 lands near 0.92).

A comparable missing an hour simply does not vote for it. If fewer than five
comparables vote for an hour, that hour falls back to persistence (hour 1's
print, spread widening with the square root of hours elapsed).

## Running

```sh
python3 main.py   # reads $MAKEFUN_INPUT_DIR (default /input),
                  # writes $MAKEFUN_OUTPUT_DIR (default /output)
```

Python 3.13, standard library only, no network, deterministic: the same
input always yields the same output.
