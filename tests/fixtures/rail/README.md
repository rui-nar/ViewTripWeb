# Rail fixture

`luxembourg-rail.osm.pbf` (365 KB) is a real rail-only extract, standing in for
what Phase 1 of issue #345 publishes per region. Luxembourg is the smallest
European country whose data exercises all three lookups at once: 1,167 railway
ways, 989 further ways carried because a relation references them, 109 route
relations, 101 nodes carrying a `uic_ref` — 66 of them stations — and 8 pairs of
UIC codes that share a relation, which is what strategy A asks about.

It was cut from `https://download.geofabrik.de/europe/luxembourg-latest.osm.pbf`
(2026-09-05) with the selection table in `docs/LOCAL_RAIL_DATA_PLAN.md`, i.e.
what `osmium tags-filter` produces for

    w/railway=rail,narrow_gauge,light_rail  (without a service tag)
    r/route=train,railway,light_rail
    n/uic_ref
    nwr/railway=station,halt + uic_ref

plus the ways those relations reference. Note what the country does *not*
contain: no station is mapped as a way or a relation here, and 8,744 of the
10,669 ways its route relations reference lie across a border and so cannot be
in a Luxembourg extract at all. `tests/test_rail_store.py` covers those shapes
with a synthetic extract it writes itself.

Refresh this file only if the selection changes: a bigger or newer fixture makes
the tests slower without testing anything more, and the counts asserted in
`test_store_holds_the_three_kinds_of_data_the_resolver_asks_for` will move.
