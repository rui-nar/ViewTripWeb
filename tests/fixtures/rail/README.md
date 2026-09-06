# Rail fixture

`luxembourg-rail.osm.pbf` (373 KB) is a real rail-only extract, standing in for
what Phase 1 of issue #345 publishes per region. Luxembourg is the smallest
European country whose data exercises all three lookups at once: 1,167 railway
ways, 109 route relations and 66 stations carrying a `uic_ref`.

It was cut from `https://download.geofabrik.de/europe/luxembourg-latest.osm.pbf`
(2026-09-05) with the tag selection the Overpass queries in
`src/services/overpass_service.py` use today — `railway` in
(`rail`, `narrow_gauge`, `light_rail`) without `service`, `route` in
(`train`, `railway`, `light_rail`), and `station`/`halt` nodes with a `uic_ref` —
keeping the nodes and member ways those reference, i.e.

    osmium tags-filter -o luxembourg-rail.osm.pbf luxembourg-latest.osm.pbf \
        w/railway=rail,narrow_gauge,light_rail r/route=train,railway,light_rail \
        n/railway=station,halt

filtered further to ways without a `service` tag and nodes with a `uic_ref`.
Refresh it only if the selection itself changes: a bigger or newer fixture makes
`tests/test_rail_store.py` slower without testing anything more.
