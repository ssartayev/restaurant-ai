# CV evaluation report: split `heldout`

> **Synthetic data only.** These numbers check the zone, filter and matching logic against scripted traces. They are NOT evidence of accuracy on real footage. Replace the manifest sessions with labelled recordings (AGENTS.md section 8).

Sessions: 6 · table-hours: 36.0 · filter: enter 20s at 70%, exit 75s at 10%

| Metric | Value | Count | Target | Met |
|---|---|---|---|---|
| Missed departures | 12.5% | 10 of 80 | ≤ 10% | NO |
| False clearing alerts per table-hour | 0.0833 | 3 | ≤ 0.2 | yes |
| Departure delay, median (s) | 67.2 |  | ≤ 90 | yes |
| Departure delay, p90 (s) | 67.5 |  | ≤ 150 | yes |
| Missed arrivals | 1.2% | 1 of 80 | ≤ 5% | yes |
| False occupancy per table-hour | 0.0556 | 2 | ≤ 0.1 | yes |
| Arrival delay, median (s) | 14.0 |  | ≤ 30 | yes |
| Arrival delay, p90 (s) | 15.7 |  | ≤ 60 | yes |

## By tag

| Tag | Table-hours | Missed departures | False clearing / table-hour | Departure delay median (s) | False occupancy / table-hour |
|---|---|---|---|---|---|
| brief_stand | 6.0 | 0 of 12 | 0.0 | 67.3 | 0.0 |
| clearing | 6.0 | 8 of 15 | 0.0 | 67.0 | 0.0 |
| low_light | 6.0 | 0 of 14 | 0.0 | 66.0 | 0.0 |
| plain | 6.0 | 0 of 13 | 0.0 | 67.3 | 0.0 |
| solo_absence | 6.0 | 1 of 14 | 0.1667 | 67.2 | 0.0 |
| staff_pass | 6.0 | 0 of 12 | 0.0 | 67.3 | 0.0 |
| table_setting | 6.0 | 1 of 12 | 0.3333 | 67.3 | 0.3333 |
