"""Locally-held rail data (issue #345, Phase 2).

``builder`` turns a filtered rail-only ``.osm.pbf`` into a per-region SQLite
store; ``store`` reads it. Nothing here talks to the network, and nothing here
knows about the resolver — wiring the store into ``get_rail_geometry`` is
Phase 3.
"""
