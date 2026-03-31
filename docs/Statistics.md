# Project Statistics

Statistics are pre-computed server-side after every project mutation (add/remove activities, create/update/delete segments, reorder items) and cached in `DBProject.stats_json`. The stats page loads instantly because it reads the cached value; if the cache is empty (e.g. on first open of an older project) the server computes it on-demand before returning.

---

## Overview

| Stat | Description |
|------|-------------|
| **Total distance** | Sum of `distance` (metres) across all activities in the project, displayed in km. |
| **Moving time** | Sum of `moving_time` (seconds) across all activities, displayed as `Xd Xh Xm`. |
| **Elevation gain** | Sum of `total_elevation_gain` (metres) across all activities of every type. |

---

## Counts

### Activities
Count of activities grouped by Strava activity type (e.g. `Ride`, `Walk`, `Run`). The type string comes directly from Strava and is stored lower-cased in the DB. `Ride` is shown first; remaining types are sorted alphabetically.

### Transportation segments
Count of connecting segments grouped by segment type: `Flight`, `Train`, `Bus`, `Boat`. Only types that are actually present in the project are shown.

---

## Ride highlights

Shown only when the project contains at least one `Ride` activity.

| Stat | Description |
|------|-------------|
| **Days with rides** | Number of distinct calendar days (local timezone) on which at least one Ride activity took place. |
| **Average distance per day** | Total ride distance ÷ number of ride days. Gives the typical cycling day length, unaffected by rest days. |
| **Total elevation gain** | Sum of `total_elevation_gain` for Ride activities only (excludes walks, runs, etc.). |
| **Best day — distance** | Highest single-day total ride distance (all Ride activities on that day summed), with the date shown. |
| **Best day — elevation** | Highest single-day total ride elevation gain (all Ride activities on that day summed), with the date shown. |

Day grouping uses `start_date_local` (the local-timezone timestamp stored by Strava), so a ride that starts just before midnight counts on the correct local day.

---

## Distance by mode (pie chart)

Total distance covered by each transport mode, shown as a donut pie chart with percentage labels and an absolute-km legend. Modes with zero distance are omitted.

| Mode | Source |
|------|--------|
| **Ride** | Sum of `distance` for all `Ride` activities. |
| **Flight** | Haversine great-circle distance between the start and end `SegmentEndpoint` of each Flight connecting segment, summed. |
| **Train** | Same as Flight but for Train segments. |
| **Bus** | Same as Flight but for Bus segments. |
| **Boat** | Same as Flight but for Boat segments. |

> Segment distances are approximations (straight-line great-circle), not the actual route taken. They are suitable for a high-level trip overview but not for precise mileage.

---

## Implementation notes

- **Computed in**: `src/project/project_repo._compute_stats(project)`
- **Cached in**: `DBProject.stats_json` (TEXT column, JSON-serialised dict)
- **Cache invalidated by**: any write to `add_activities`, `delete_item`, `reorder_items`, `create_segment`, `update_segment`, `delete_segment`, `refresh_activity` — all schedule `_refresh_stats_background` as a FastAPI `BackgroundTask`.
- **API endpoint**: `GET /api/projects/{name}/stats` — returns cached JSON, or triggers on-demand compute if `stats_json` is `NULL`.
