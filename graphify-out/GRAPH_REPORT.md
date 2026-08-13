# Graph Report - ViewTripWeb  (2026-07-30)

## Corpus Check
- 536 files · ~382,491 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 10521 nodes · 26980 edges · 366 communities (281 shown, 85 thin omitted)
- Extraction: 65% EXTRACTED · 35% INFERRED · 0% AMBIGUOUS · INFERRED: 9441 edges (avg confidence: 0.57)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `770266c4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app_router.dart
- Memory
- Activity
- activity_panel.dart
- people.py
- .json
- poster_renderer.py
- APIError
- DBProjectMember
- save
- .project
- recompute_track_metrics
- overpass_service.py
- ViewTripWeb Application
- backup_db
- FilterCriteria
- get_logger
- test_memory_translations.py
- db.py
- project_stats_timeseries.dart
- Multi-Select / Bulk Export Screen
- project_stats_counters.dart
- Activity List Panel
- Add Transportation Dialog
- Strava Import Dialog
- project_stats_body.dart
- CLAUDE.md Project Instructions
- d5b1c0a2e3f4_prune_orphaned_split_tail_activities.py
- a26e2eea9f01_merge_group_id_and_e2ee_heads.py
- b8c9d0e1f2a3_set_memory_public_id_not_null.py
- d3e4f5a6b7c8_merge_memory_fk_and_journal_heads.py
- DBProject
- DBMemory
- ProjectItem
- map_panel.dart
- DBProjectItem
- project_notifier.dart
- welcome_screen.dart
- project_settings_screen.dart
- version.py
- .to_dict
- .to_dict
- .to_dict
- project_io.py
- config/config.json â€” Strava + Google Credentials
- Python Dependencies (Production/Docker)
- encryption_service_test.dart
- OverpassError
- day_meta_editor.dart
- memory_detail_modal.dart
- resolve_project
- .current_token
- AuthNotifier
- social_share_dialog.dart
- package:flutter/material.dart
- activity_editor_page.dart
- .to_strava_dict
- TestDataclassRoundTrips
- admin_screen.dart
- app_screen.dart
- .get
- project_stats_screen.dart
- ../api/client.dart
- Strava activity row — shared across all projects that reference it.      Uses
- project_notifier_members_test.dart
- ProjectIO
- A person met on a trip (issue #40) — owner-only, per-project.      All identit
- A like on a memory — posted by an authenticated user.
- State
- ProjectNotifier
- A like on a memory — posted by an authenticated user.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- A like on a memory — posted by an authenticated user.
- A cached translation of a memory's name and description.
- stale_shared_ref_test.dart
- package:flutter_test/flutter_test.dart
- project_memory_crud_mixin.dart
- .get
- memory_dialog.dart
- e2ee_crypto.dart
- settings_screen.dart
- Raise RuntimeError if DBProject columns diverge from the registry.      Called
- Per-project auto-sync configuration and last-synced timestamps.
- Strava activity row — shared across all projects that reference it.      Uses
- A private, owner-only journal entry attached to a project and a specific date.
- One ordered entry in a project — either an activity ref, segment, memory, or jou
- One visitor record for a shared-project link.      Keyed on (project_id, token
- Map
- Meeting a person or group on a given day/place (issue #40, #56) — owner-only, pe
- One ordered entry in a project — an activity ref, segment, memory, journal, or e
- One visitor record for a shared-project link.      Keyed on (project_id, token
- people_screen.dart
- journal_detail_modal.dart
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- A cached translation of a memory's name and description.
- A memory's name/description re-encrypted under a per-share content key     (iss
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- A user's per-device X25519 public key and the CMK wrapped to it.      A new de
- The CMK wrapped under a user-chosen recovery method (issue #26).      method="
- A cached translation of a memory's name and description.
- A like on a memory — posted by an authenticated user.
- A cached translation of a memory's name and description.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- A user's per-device X25519 public key and the CMK wrapped to it.      A new de
- The CMK wrapped under a user-chosen recovery method (issue #26).      method="
- Convert a Unix timestamp or ISO-8601 string to YYYY-MM-DD.
- Slim down a Polarsteps trip dict for the API response.
- Slim down a Polarsteps step dict for the API response.
- project_stats_counters.dart
- share_asset_source_impl.dart
- ConfigurationError
- projects_screen.dart
- Create an Activity instance from Strava API response data.
- test_tile_stitcher.py
- One visitor record for a shared-project link.      Keyed on (project_id, token
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- One visitor record for a shared-project link.      Keyed on (project_id, token
- photo_upgrade_screen_test.dart
- One ordered entry in a project — an activity ref, segment, memory, journal, or e
- poster_config_dialog_test.dart
- share_client
- A cached translation of a memory's name and description.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- segment_dialog.dart
- encryption_service.dart
- shared_project_screen.dart
- photo_match.dart
- CustomPainter
- share_strategy.dart
- A like on a memory — posted by an authenticated user.
- A cached translation of a memory's name and description.
- _TsMetric
- _TsOp
- _ProjectStatsScreenState
- SegmentDialog
- A like on a memory — posted by an authenticated user.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- .token_rotated
- Meeting a person on a given day/place (issue #40) — owner-only, per-project.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- One visitor record for a shared-project link.      Keyed on (project_id, token
- view_screen.dart
- Scalar API reference UI.
- Version this image was built from (the git tag baked in at build time).      T
- Serve the Flutter web build; fall back to index.html for SPA routing.
- e2ee_spike.dart
- google_button_web.dart
- _BulkTagDialog
- Map an optimistic-lock conflict to 409 so clients can refetch and retry.
- FilterSheet
- Serve the Flutter web build; fall back to index.html for SPA routing.
- One visitor record for a shared-project link.      Keyed on (project_id, token
- ManageMapPanel
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- A cached translation of a memory's name and description.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- MapPanel
- Timestamps older than WINDOW_SECONDS should not count toward usage.
- render_invite_email
- dart:math
- Serve the Flutter web build; fall back to index.html for SPA routing.
- share_strategy.dart
- main
- PinSpec
- One visitor record for a shared-project link.      Keyed on (project_id, token
- TestVrHafas
- A like on a memory — posted by an authenticated user.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- project_filter_mixin.dart
- recover_screen.dart
- TestUniqueStepIdIndex
- _TsMetric
- _TsOp
- encounter_dialog.dart
- test_quota_enforcement.py
- enable_encryption_screen.dart
- recover_screen.dart
- jwt_secret
- Serve the Flutter web build; fall back to index.html for SPA routing.
- DBPosterJob
- register_screen.dart
- plan_picker.dart
- A cached translation of a memory's name and description.
- plan_name
- A cached translation of a memory's name and description.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- project_notifier_members_test.dart
- test_android_release_config.py
- stale_shared_ref_test.dart
- manage_devices_screen.dart
- great_circle.dart
- billing_section.dart
- .start
- project_stats_timeseries.dart
- version_code
- test_encounters_api.py
- settings_service.dart
- project_stats_counters.dart
- share_asset_source_impl.dart
- test_assetlinks.py
- One visitor record for a shared-project link.      Keyed on (project_id, token
- run-android.ps1
- TestSmtpCounters
- main
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- datetime
- upgrade_sheet.dart
- test_migration_split_parent_id.py
- project_stats_body.dart
- image_export.dart
- .to_strava_dict
- Return steps for a trip, sorted chronologically.          Draft (unpublished) st
- TestPriceLookupKeys
- _cache_control_for
- Return steps for a trip, sorted chronologically.
- draw_logo
- List
- merge
- String?
- polyline_decoder.dart
- dart:typed_data
- design_tokens.dart
- .delete
- social_share_controller.dart
- get_current_user
- auth_notifier.dart
- activity_editor_page_test.dart
- billing/__init__.py
- project_stats_screen_test.dart
- return
- photo_source.dart
- social_share_controller_test.dart
- .set
- strava_import_screen.dart
- test_strava_client.py
- tile_renderer.py
- photo_upgrade_screen.dart
- polarsteps_import_screen.dart
- test_admin.py
- polarsteps_import_notifier.dart
- strava_import_notifier.dart
- encounter_dialog_test.dart
- _compute_stats
- POST a query to Overpass, with retry + mirror fallback.      The public ``over
- Real deployments keep the generic message — no detail leakage.
- elevation_chart.dart
- location_picker_dialog.dart
- poster_config_dialog.dart
- Extract a single clean start→end polyline from a train route relation.      Tr
- Return [[lon, lat], …] polyline from stops[0] to stops[-1].      *stops* is a
- One ordered entry in a project — either an activity ref, segment, or memory.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- day_meta_editor_test.dart
- A like on a memory — posted by an authenticated user.
- Return the project as a REST-API-ready dict (same contract as ProjectIO.to_dict)
- Nearest OSM railway station within radius_m metres.     Returns {lat, lon, uic}
- A private, owner-only journal entry attached to a project and a specific date.
- One ordered entry in a project — either an activity ref, segment, memory, or jou
- One visitor record for a shared-project link.      Keyed on (project_id, token
- Return the project as a REST-API-ready dict (same contract as ProjectIO.to_dict)
- social_share_modal_test.dart
- Intercept NOTIFY_DEBUGGER_ABOUT_RX_PAGES and touch the pages.
- client_geo_builder_test.dart
- One visitor record for a shared-project link.      Keyed on (project_id, token
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- Return the project as a REST-API-ready dict (same contract as ProjectIO.to_dict)
- src/exceptions/errors.py â€” Custom Exception Hierarchy
- test_photo_replace_api.py
- One visitor record for a shared-project link.      Keyed on (project_id, token
- A cached translation of a memory's name and description.
- Per-user cache of the raw Strava activity list.      One row per user; the ent
- test_resolve_route_async.py
- TestLowResGeoAndFullLoadDoNotCrash
- admin.py
- perf_timing.dart
- basemaps.dart
- add_speed_dial.dart
- api/journal.py
- project_shares.py
- admin_screen_test.dart
- theme.dart
- device_key_store.dart
- sync_import_dialog.dart
- client_geo_builder.dart
- version_gate.dart
- downsample_elevation
- great_circle_points
- repo_activities.py
- logging.py
- _build_comment_tree
- settings_service.dart
- test_journal_per_user.py
- haversine_km
- main
- test_segments_api.py
- download_web.dart
- viewtrip_client
- Phase 1 crypto spike — results & locked stack (issue #26)
- panel_resize.dart
- TestRowToActivityThreading
- 024698e63236_add_share_memory_content_table.py
- 124a1d7b0d32_add_group_id_to_encounter.py
- 1604d06d464d_add_e2ee_columns_and_key_tables.py
- 316b7dd1374b_add_memories.py
- 40655974e9f7_add_project_tables.py
- 42178952db14_add_trip_end_to_project.py
- 50c0de5f6a7b_add_person_groups.py
- 754049cd2430_add_counters_json_to_project.py
- 8439d6b26a02_add_poster_job_table.py
- 88d31b1f3613_.py
- a1b2c3d4e5f6_add_memory_likes_comments.py
- a3f8c2d1e9b5_add_day_meta_to_project.py
- a7b8c9d0e1f2_add_public_id_to_memory.py
- a9c4e7f2b8d1_add_project_members_and_invites.py
- b1c2d3e4f5a6_add_role_to_projectinvite.py
- b2c3d4e5f6a7_add_memory_translations.py
- b7e4f1c3d2a6_add_low_res_geo_to_project.py
- b97eab3d11cf_add_type_styles_to_project.py
- c1e2f3a4b5d6_drop_localauthsession_add_memory_fk.py
- c2d3e4f5a6b7_add_journal_entries.py
- c3d4e5f6a7b8_add_track_secondary_color.py
- c7d2e9a4f1b3_add_user_to_journal_entry.py
- c9d0e1f2a3b4_unique_polarsteps_step_id_per_project.py
- d4e5f6a7b8c9_add_elevation_chart_style.py
- e5f6a7b8c9d0_add_polarsteps_step_id_to_memory.py
- e7f8a9b0c1d2_add_activity_edit_columns.py
- ea002876cb8d_add_stats_json_to_project.py
- ecb730945e37_add_trip_start_to_project.py
- f40e0c0de001_add_people_and_encounters.py
- flutter_client/lib/main.dart â€” App Entry Point
- entrypoint.sh
- return_to.dart
- version_reload_stub.dart
- projects_notifier.dart â€” Project List State
- DateTime?
- Exception
- Image?
- Object?
- segment_dialog.dart â€” Add/Edit Connecting Segment Dialog
- strava_import_screen.dart â€” Strava Activity Browser + Import

## God Nodes (most connected - your core abstractions)
1. `DBProject` - 661 edges
2. `UserInfo` - 628 edges
3. `DBProjectItem` - 466 edges
4. `Activity` - 316 edges
5. `DBMemory` - 314 edges
6. `DBActivity` - 306 edges
7. `Project` - 300 edges
8. `ProjectIO` - 281 edges
9. `ProjectItem` - 232 edges
10. `ProjectRepo` - 228 edges

## Surprising Connections (you probably didn't know these)
- `Backup management endpoints — list and restore SQLite backups.` --uses--> `UserInfo`  [INFERRED]
  api/backup.py → models/user.py
- `Return all available daily SQLite backups, newest-first.      Each entry is ``{d` --uses--> `UserInfo`  [INFERRED]
  api/backup.py → models/user.py
- `Restore the database to the backup taken on *date* (YYYY-MM-DD).      Overwrites` --uses--> `UserInfo`  [INFERRED]
  api/backup.py → models/user.py
- `FastAPI dependencies — JWT Bearer authentication for the REST API.  Flutter (a` --uses--> `UserInfo`  [INFERRED]
  api/deps.py → models/user.py
- `REST project item-ordering endpoints — delete/reorder/sort timeline items.  Ro` --uses--> `ProjectIO`  [INFERRED]
  api/project_items.py → src/project/project_io.py

## Import Cycles
- None detected.

## Communities (366 total, 85 thin omitted)

### Community 0 - "app_router.dart"
Cohesion: 0.04
Nodes (50): ../admin/admin_screen.dart, ../auth/auth_notifier.dart, ../auth/forced_change_password_screen.dart, ../auth/login_screen.dart, ../auth/register_screen.dart, ../auth/verify_email_screen.dart, ../auth/welcome_screen.dart, AppScreen (+42 more)

### Community 1 - "Memory"
Cohesion: 0.08
Nodes (172): BaseModel, Returned by the async resolve-route trigger (HTTP 202)., ResolveRouteRequest, RouteResolvedOut, RouteResolveTriggered, SegmentIDOut, DBJournalEntry, DBMemoryComment (+164 more)

### Community 2 - "Activity"
Cohesion: 0.04
Nodes (48): AppScreen, authRedirectTarget, saveLastOpenedProject, saveLastOpenedProject, clearLastOpenedProject, saveLastOpenedProject, ProjectRef, recoverFromStaleSharedRef (+40 more)

### Community 3 - "activity_panel.dart"
Cohesion: 0.02
Nodes (113): activity_editor_page.dart, AlertDialog, Column, Container, Dismissible, Function, InkWell, ListenableBuilder (+105 more)

### Community 4 - "people.py"
Cohesion: 0.05
Nodes (61): _apply_person_fields(), _avatar_dir(), create_person(), delete_avatar(), _delete_avatar_files(), delete_person(), _encounter_out(), _get_owned_person() (+53 more)

### Community 5 - ".json"
Cohesion: 0.09
Nodes (20): ABC, ConsoleEmailService, EmailService, get_email_service(), Transactional email — provider-agnostic SMTP transport (issue #113).  ``EmailS, Logs the email instead of sending it. Never raises — the safe default     for d, Sends via SMTP (aiosmtplib) — works with any provider's relay., The process-wide EmailService, lazily selected on first use. (+12 more)

### Community 6 - "poster_renderer.py"
Cohesion: 0.10
Nodes (47): Co-owner+ removes an editor/viewer; a member may remove only themself     (leav, remove_member(), assert_project_access(), _caller_role(), effective_role(), _is_member(), require_role(), resolve_project() (+39 more)

### Community 7 - "APIError"
Cohesion: 0.03
Nodes (225): Run migrations in 'offline' mode.      This configures the context with just a, Run migrations in 'online' mode.      In this scenario we need to create an En, run_migrations_offline(), run_migrations_online(), ChangePasswordRequest, GoogleTokenRequest, OkOut, BaseModel (+217 more)

### Community 8 - "DBProjectMember"
Cohesion: 0.09
Nodes (31): _projects_dir(), create_share_link(), create_share_link_no_memories(), _delete_share_memory_content(), get_share_info(), get_share_visitors(), Depends, OwnerParam (+23 more)

### Community 9 - "save"
Cohesion: 0.10
Nodes (12): ActivityCache, Disk-backed cache for Strava Activity objects., Persists Activity objects to a JSON file in cache_dir.      Serialisation roun, Return cached activities sorted newest-first, or [] if no cache., Overwrite the cache with *activities* (sorted newest-first)., Merge *new_activities* into the cache, deduplicate by id.          Returns the, UTC datetime of the last save/merge, or None if no cache., start_date of the newest cached activity, for incremental sync. (+4 more)

### Community 10 - ".project"
Cohesion: 0.03
Nodes (97): GeoJSON endpoints — converts a project's tracks and segments to GeoJSON.  Rout, Recompute and cache the full-res GeoJSON for a project.      Called from backg, Return a GeoJSON FeatureCollection for *name*.      Each activity feature has, Invalidate the full-res GeoJSON cache entry for this project., Build the full-resolution GeoJSON features for *project*.      Activities with, Return a GeoJSON FeatureCollection for *name*.      Each activity LineString h, Activity data model for Strava activities., Encounter data model — meeting a person or group on a given day/place (issue #40 (+89 more)

### Community 11 - "recompute_track_metrics"
Cohesion: 0.08
Nodes (24): canEditContent, canManageTrip, copyWith, fromJson, hashCode, isOwn, isOwner, isSharedWithMe (+16 more)

### Community 12 - "overpass_service.py"
Cohesion: 0.10
Nodes (20): _compute_segment_geometry(), Any, Run the (slow) HAFAS + Overpass lookups for a segment.      Returns ``(polylin, get_bus_geometry(), get_ferry_geometry(), Return [[lon, lat], …] polyline following OSM ferry route geometry., Return [[lon, lat], …] polyline following OSM bus route geometry., _empty_overpass() (+12 more)

### Community 13 - "ViewTripWeb Application"
Cohesion: 0.06
Nodes (39): flutter_bootstrap.js â€” Flutter Engine Bootstrap, flutter_client/web/index.html â€” Flutter Web Entry Point, Google Sign-In Client ID Meta Tag, web_client/index.html â€” Web Client Entry Point (deployed build), Alembic Database Migrations, api/auth.py â€” Auth Endpoints, api/deps.py â€” JWT Dependency, api/geo.py â€” GeoJSON Builder (+31 more)

### Community 14 - "backup_db"
Cohesion: 0.08
Nodes (44): get_backups(), Backup management endpoints — list and restore SQLite backups., Return all available daily SQLite backups, newest-first.      Each entry is ``{d, Restore the database to the backup taken on *date* (YYYY-MM-DD).      Overwrites, restore_backup(), _make_engine(), Create the app engine with a connection pool sized for the client's     paralle, backup_db() (+36 more)

### Community 15 - "FilterCriteria"
Cohesion: 0.12
Nodes (35): apply(), extract_activity_types(), FilterCriteria, Activity filtering logic for ViewTrip., Criteria for filtering activities.      None on any field means no constraint, Return True if no filters are active., Return a sorted list of unique activity types present in the list., Filter components for ViewTrip. (+27 more)

### Community 16 - "get_logger"
Cohesion: 0.08
Nodes (41): billing_me(), BillingMeOut, CheckoutBody, CheckoutOut, create_checkout(), create_portal(), list_plans(), PlanOut (+33 more)

### Community 17 - "test_memory_translations.py"
Cohesion: 0.05
Nodes (43): _bullet(), Change, _classify(), _git(), git_log(), main(), parse_commits(), polish() (+35 more)

### Community 18 - "db.py"
Cohesion: 0.26
Nodes (6): _deserialise_item(), _serialise_item(), Session, _make_journal_item(), TestProjectIOHelpers, _segment_json()

### Community 19 - "project_stats_timeseries.dart"
Cohesion: 0.15
Nodes (18): _apply_group_fields(), create_group(), delete_group(), get_group(), _get_owned_group(), _get_project_id(), _group_out(), _loads_list() (+10 more)

### Community 20 - "Multi-Select / Bulk Export Screen"
Cohesion: 0.21
Nodes (15): Activity List Item (with icon, name, date, distance), Activity List Panel (Left), Activity Detail Panel (Right), Elevation Profile Chart, Export Options Bar (Merge / Timestamps / Elevation), Route Map View (OpenStreetMap), Preview / Export Tab, View Project Tab (+7 more)

### Community 21 - "project_stats_counters.dart"
Cohesion: 0.06
Nodes (24): fake_email(), _FakeEmailService, _invite(), Pending invites addressed to an email (issue #110).  Before this, emailing som, Stored lowercased, or it would never match the recipient's account., Otherwise an unconfirmed address can mail strangers from our domain., The copy-a-link flow is untouched by all of this., The caller asked to email someone, not to be handed that person's         priva (+16 more)

### Community 22 - "Activity List Panel"
Cohesion: 0.22
Nodes (14): Activity Detail Panel, Activity List Panel, Ride Activity Type, Train Activity Type, GetTracks Application (Voyage 2026), Elevation Profile Chart, Export Options Bar, OpenStreetMap Route Map (+6 more)

### Community 23 - "Add Transportation Dialog"
Cohesion: 0.19
Nodes (13): Boat Transport Option, Bus Transport Option, Cancel Button, Add Transportation Dialog, Distance Display (Great Circle), End Coordinates (Lat/Lon), Flight Transport Option, Insert After Dropdown (+5 more)

### Community 24 - "Strava Import Dialog"
Cohesion: 0.33
Nodes (12): Strava Activity Entry (Ride/Snowboard/AlpineSki), Activity Type Filter, Add Button, Available from Strava List, Date Range Filter, Import Selection Button, In Project Activities List, Remove Button (+4 more)

### Community 25 - "project_stats_body.dart"
Cohesion: 0.06
Nodes (32): AlertDialog, Padding, SizedBox, TextField, build, createState, dispose, _email (+24 more)

### Community 26 - "CLAUDE.md Project Instructions"
Cohesion: 0.29
Nodes (7): Graphify Knowledge Graph Rule, CLAUDE.md Project Instructions, Current Stack: FastAPI + Flutter (web/android/iOS), Testing Rule: Tests for Every Feature, Versioning Rule: x.y.z with GitHub Actions Docker, Docker + GitHub Actions CI/CD, Graphify Knowledge Graph (graphify-out/)

### Community 27 - "d5b1c0a2e3f4_prune_orphaned_split_tail_activities.py"
Cohesion: 0.33
Nodes (5): downgrade(), prune orphaned split-tail activities (issue #45 follow-up)  A pre-fix bug in ", Delete orphaned local (negative-id) activity rows., No-op: deleted orphans carry no recoverable state and were never valid     data, upgrade()

### Community 31 - "DBProject"
Cohesion: 0.05
Nodes (36): ProjectRef, GeoPoint, acceptInvite, _api, avatarUrl, createdAt, CreatedInvite, createInvite (+28 more)

### Community 34 - "DBMemory"
Cohesion: 0.03
Nodes (76): Dismissible, Scaffold, User, main, notifierWithOneActivity, pumpPanel, called, changePasswordError (+68 more)

### Community 35 - "ProjectItem"
Cohesion: 0.07
Nodes (129): ActivityMixin, ActivitiesAddedOut, ActivityFieldsUpdate, AddActivitiesRequest, BaseModel, REST activity endpoints — add/refresh/edit/split activities within a project., SplitRequest, TrackEditRequest (+121 more)

### Community 36 - "map_panel.dart"
Cohesion: 0.01
Nodes (162): Center, Column, Container, Function, Icon, LatLng, LayoutBuilder, MarkerLayer (+154 more)

### Community 39 - "DBProjectItem"
Cohesion: 0.05
Nodes (36): d, Exception, r, addSegment, clearSegmentOverlay, _decodePolyline, deleteSegment, error (+28 more)

### Community 40 - "project_notifier.dart"
Cohesion: 0.01
Nodes (152): class ProjectNotifier extends, client_geo_builder.dart, Color get, Exception, ShareContentGenerator, activeDayKey, alternatingTrackColors, apiBaseUrl (+144 more)

### Community 41 - "welcome_screen.dart"
Cohesion: 0.02
Nodes (142): CustomPainter, Center, Color, Column, Container, Padding, Row, Scaffold (+134 more)

### Community 42 - "project_settings_screen.dart"
Cohesion: 0.02
Nodes (130): Center, Column, Container, Divider, Function, Icon, InkWell, Padding (+122 more)

### Community 44 - ".to_dict"
Cohesion: 0.04
Nodes (45): @immutable, brand_mark.dart, atY, _blurb, _blurbColour, _cell, child, _controller (+37 more)

### Community 45 - ".to_dict"
Cohesion: 0.06
Nodes (31): AlertDialog, SizedBox, SnackBar, Stack, build, createState, _customLat, _customLon (+23 more)

### Community 46 - ".to_dict"
Cohesion: 0.20
Nodes (7): Return steps for a trip, sorted chronologically.          Draft (unpublished), _client_returning(), Issue #86: an encounter's Polarsteps track showed an incomplete track.  `forma, TestAllStepsFallback, _client_returning(), Issue #23: Polarsteps import must surface published steps, not drafts.  A step's, TestDraftFiltering

### Community 47 - "project_io.py"
Cohesion: 0.05
Nodes (141): Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'online' mode.      In this scenario we need to create an Engi, BroadcastEmailRequest, BroadcastEmailResponse, OkResponse, BaseModel, Admin dashboard REST endpoints (issue #25).  All routes require an admin calle, ResetPasswordResponse (+133 more)

### Community 50 - "encryption_service_test.dart"
Cohesion: 0.02
Nodes (116): ../crypto/share_crypto.dart, shareKeyFromBase64, EncryptionService, EncryptionStatus, EncryptionService, EncryptionStatus, FilledButton, SecureStorageDeviceKeyStore (+108 more)

### Community 52 - "OverpassError"
Cohesion: 0.21
Nodes (17): _find_trip_id(), get_stop_sequence(), _name_matches(), _nearest_stop(), HAFAS-based train schedule service.  Queries public transport REST APIs (Deuts, Fetch and cache VR station metadata from rata.digitraffic.fi., Return an ordered stop list using the rata.digitraffic.fi open API., Return an ordered list of stops [{name, lat, lon, uic}, …] start→end.     Raise (+9 more)

### Community 53 - "day_meta_editor.dart"
Cohesion: 0.02
Nodes (107): Column, Container, DecoratedBox, Dialog, DraggableScrollableSheet, Function, IconButton, InkWell (+99 more)

### Community 54 - "memory_detail_modal.dart"
Cohesion: 0.02
Nodes (103): Center, ClipRRect, Column, Container, Dialog, Function, GestureDetector, Icon (+95 more)

### Community 55 - "resolve_project"
Cohesion: 0.07
Nodes (70): add_activities(), delete_local_activity(), edit_activity_track(), _enrich_activities_background(), _enrich_pending_background(), get_activity_track(), _project_contains_activity(), BackgroundTasks (+62 more)

### Community 56 - ".current_token"
Cohesion: 0.04
Nodes (36): What the reader sees — the author's line if they wrote one., APScheduler listener recording run counts, duration and last success.      Reg, record_job_event(), metric(), Read a Prometheus sample by name + labels, 0.0 if the series is absent.      T, The in-memory pool used by tests has no checkedout()/overflow(); a         scra, WAL growth is the only visible symptom of checkpoint_wal having         stopped, Pool exhaustion is what took production down in #35 — it has to be         both (+28 more)

### Community 57 - "AuthNotifier"
Cohesion: 0.12
Nodes (20): Billing models — subscription state and per-user storage usage (issue #121)., Running total of bytes stored under ``data/users/{id}/`` for one user., UserUsage, bytes_of(), Path, Per-user storage accounting for quota checks (issue #121).  The admin dashboar, Nightly job: re-walk every user's tree and correct the counters.      A no-op, Total size of the given files, skipping any that are missing. (+12 more)

### Community 58 - "social_share_dialog.dart"
Cohesion: 0.02
Nodes (83): Column, Container, Function, GestureDetector, InkWell, Opacity, Padding, SingleChildScrollView (+75 more)

### Community 60 - "package:flutter/material.dart"
Cohesion: 0.06
Nodes (32): MaterialApp, activityById, activityItem, main, segmentItem, acts, build, controller (+24 more)

### Community 61 - "activity_editor_page.dart"
Cohesion: 0.03
Nodes (70): Center, DecoratedBox, Material, PopupMenuDivider, Scaffold, SizedBox, activity, ActivityEditorPage (+62 more)

### Community 62 - ".to_strava_dict"
Cohesion: 0.15
Nodes (9): plan_from_subscription(), Pure mapping from stored provider state to the plan in force right now.      A, True while the provider still considers the subscription running.      Distinc, subscription_is_live(), A failed renewal starts a provider retry window; locking the account         ou, Live" is not the same question as "which plan is in force" (issue #163)., The distinction the whole helper exists for: nothing will renew it,         so, TestPlanFromSubscription (+1 more)

### Community 63 - "TestDataclassRoundTrips"
Cohesion: 0.15
Nodes (12): env(), _find_act(), The edit-track response is discarded by the client (it immediately     re-fetch, Same rationale as test_edit_track_reload_defers_full_elevation_profile,     for, test_edit_track_reload_defers_full_elevation_profile(), test_get_activity_track_returns_editor_payload(), test_get_activity_track_unknown_activity_is_404(), test_get_activity_track_unknown_project_is_404() (+4 more)

### Community 64 - "admin_screen.dart"
Cohesion: 0.02
Nodes (80): admin_service.dart, Card, Center, Column, Container, DataRow, Divider, Icon (+72 more)

### Community 65 - "app_screen.dart"
Cohesion: 0.02
Nodes (83): ../core/perf_timing.dart, download_stub.dart, AlertDialog, Function, IconButton, LinearProgressIndicator, MaterialBanner, MouseRegion (+75 more)

### Community 66 - ".get"
Cohesion: 0.06
Nodes (31): _nominatim_search(), Raw Nominatim search for *q* (extracted so tests can stub the upstream)., Regression (issue #67): the client never re-logs in after a forced         chan, TestAdminEmailsPromotion, TestTokenAndMeFields, test_shared_meta_excludes_people_and_encounters(), test_shared_view_excludes_people_and_encounters(), TestJournalCreate (+23 more)

### Community 67 - "project_stats_screen.dart"
Cohesion: 0.03
Nodes (77): a, _active, activeSeries, color, _counterPalette, counterStats, Card, Center (+69 more)

### Community 68 - "../api/client.dart"
Cohesion: 0.08
Nodes (26): ../billing/billing_service.dart, QuotaError, quotaError, recordQuotaRefusal, takeQuotaError, clearQuotaError, create, ApiException (+18 more)

### Community 69 - "Strava activity row — shared across all projects that reference it.      Uses"
Cohesion: 0.05
Nodes (48): ImageFont, CardLayout, A fully positioned card: ops are in card-local coordinates., covers(), _find_face_file(), FontStack, _glyph_signature(), load_emoji_face() (+40 more)

### Community 70 - "project_notifier_members_test.dart"
Cohesion: 0.03
Nodes (84): dart:convert, dart:io, Scaffold, ProjectRef, PosterJobNotifier, decryptTextWithKey, Exception, _FakeMembersService (+76 more)

### Community 71 - "ProjectIO"
Cohesion: 0.04
Nodes (47): Duration, ProjectRef, _api, bytes, downloadPath, error, fetchPosterPreview, hasWarning (+39 more)

### Community 72 - "A person met on a trip (issue #40) — owner-only, per-project.      All identit"
Cohesion: 0.08
Nodes (40): _Cursor, _ellipsize(), layout_card(), _line_ops(), measure_text(), _photo_grid(), PhotoOp, Any (+32 more)

### Community 74 - "State"
Cohesion: 0.06
Nodes (32): AlertDialog, CheckboxListTile, SizedBox, Spacer, build, _createPerson, createState, dispose (+24 more)

### Community 75 - "ProjectNotifier"
Cohesion: 0.02
Nodes (104): ../core/last_opened_project.dart, Center, FilterChip, ListTile, Padding, SafeArea, Scaffold, SizedBox (+96 more)

### Community 76 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.04
Nodes (45): BillingService, checkoutCalls, checkoutUrl, _FakeBilling, main, payload, plans, portalCalls (+37 more)

### Community 77 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.03
Nodes (61): ../crypto/encryption.dart, createJournal, deleteJournal, deleteJournalPhoto, error, errorMessage, items, projectRef (+53 more)

### Community 78 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.10
Nodes (43): delete_account(), me(), Return the current user's profile decoded from the JWT.      ``email_verified`, Permanently delete the current user's account and all associated data., get_optional_current_user(), FastAPI dependency — returns the decoded JWT payload if a valid Bearer     toke, _delete_comment_subtree(), Delete a comment and all its descendants (BFS). (+35 more)

### Community 79 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.18
Nodes (9): _group_from_dict(), _group_to_dict(), load(), Any, save(), _make_activity(), TestMerge, TestSaveLoad (+1 more)

### Community 80 - "A cached translation of a memory's name and description."
Cohesion: 0.09
Nodes (33): _candidate_rect(), CardPlacement, PinSpec, place_cards(), Deterministic, non-overlapping placement of memory cards on a trip poster.  Pa, The point on this rectangle's border nearest to (x, y).          Leader lines, Result of trying to place a card for one pin.      ``placed=True`` means ``car, Card rectangle centred at (pin + radius * direction). (+25 more)

### Community 81 - "stale_shared_ref_test.dart"
Cohesion: 0.06
Nodes (30): build, createState, _customLat, _customLon, AlertDialog, SizedBox, SnackBar, Stack (+22 more)

### Community 82 - "package:flutter_test/flutter_test.dart"
Cohesion: 0.03
Nodes (45): MaterialApp, main, main, main, main, _params, _salt, main (+37 more)

### Community 83 - "project_memory_crud_mixin.dart"
Cohesion: 0.08
Nodes (20): Point, Segment, _on_segment(), _orientation(), Spatial index for testing whether a rectangle covers the trip's track.  Poster, Standard orientation-test segment intersection, including collinear touching., Uniform-grid index over the projected route's line segments., True if any route segment enters the given rectangle. (+12 more)

### Community 84 - ".get"
Cohesion: 0.05
Nodes (40): Google Translate helper used by memory translation endpoints., Translate *text* to *target_lang* via the Google Translate v2 REST API.      R, translate_text(), Unofficial Polarsteps API client using remember_token cookie auth.  Requires P, _db_file_size(), ExternalCall, install_db_metrics(), instrument_http() (+32 more)

### Community 85 - "memory_dialog.dart"
Cohesion: 0.10
Nodes (10): Drop characters no face in the stack has a glyph for.      Kept as the single, strip_unsupported(), Emoji are *rendered*, not suppressed, when an emoji face is available.      Pi, Graceful degradation: with no emoji face, dropping them still beats         pri, A fixed-strike bitmap face renders at 109px; without the per-run         scale, A space swept into an emoji run would be measured at the emoji         face's n, U+2744 has a monochrome glyph in DejaVu, so the text face would         claim i, Regression: strip_unsupported runs *before* split_runs, and no face         has (+2 more)

### Community 86 - "e2ee_crypto.dart"
Cohesion: 0.03
Nodes (61): FormatException, SecretKey, _aead, argon2, Argon2Params, blob, box, bytes (+53 more)

### Community 87 - "settings_screen.dart"
Cohesion: 0.03
Nodes (61): ../auth/auth_service.dart, ../billing/billing_section.dart, ../core/version_reload_stub.dart, ../crypto/enable_encryption_screen.dart, ../crypto/manage_devices_screen.dart, ../crypto/recover_screen.dart, AuthService, Card (+53 more)

### Community 88 - "Raise RuntimeError if DBProject columns diverge from the registry.      Called"
Cohesion: 0.06
Nodes (30): Protocol, BillingGateway, get_gateway(), Payment-gateway seam (issue #121).  Everything above this line is provider-agn, The three provider operations the app needs., Start a subscription purchase. Returns ``{"url", "customer_id"}``., Open the provider's billing portal. Returns ``{"url"}``., Verify the signature and return the event dict. Raises on mismatch. (+22 more)

### Community 89 - "Per-project auto-sync configuration and last-synced timestamps."
Cohesion: 0.13
Nodes (13): KeyedRateLimiter, Allows *max_events* per *window_seconds* for each key independently., Record an event against *key*. False if that would exceed the limit., Events still allowed for *key* in the current window., Forget every key. For tests — instances are module-level, so without         th, _Clock, KeyedRateLimiter (issue #110).  Driven by an injected clock rather than real t, A fixed-bucket limiter would let 2N through across a boundary. (+5 more)

### Community 90 - "Strava activity row — shared across all projects that reference it.      Uses"
Cohesion: 0.13
Nodes (15): cached_user_storage(), dir_size(), Path, Per-user storage accounting for the admin dashboard.  The filesystem walk is d, Sum ``st_size`` of every regular file under ``path`` (recursive).      A missi, Return the user's storage in bytes, using the TTL cache when fresh.      ``now, Bust the storage cache — for one user, or all users if ``user_id`` is None., refresh_storage_cache() (+7 more)

### Community 91 - "A private, owner-only journal entry attached to a project and a specific date."
Cohesion: 0.08
Nodes (18): Keyed, non-blocking sliding-window rate limiter (issue #110).  Used for the ac, Clear the shared mail limiter. For tests., reset_rate_limits(), _FakeMailer, mailer(), Email verification (issue #110).  Verification is what turns the self-declared, A broken relay must not fail a registration that otherwise         succeeded —, The token proves control of the address it was issued for. If the         accou (+10 more)

### Community 92 - "One ordered entry in a project — either an activity ref, segment, memory, or jou"
Cohesion: 0.14
Nodes (22): _enable_encryption_body(), _join(), test_accept_creates_membership_and_is_idempotent(), test_editor_can_create_person_in_shared_project(), test_editor_can_leave_but_not_remove_others(), test_editor_can_list_members_with_owner_param(), test_editor_can_update_trip_dates_but_not_rename(), test_editor_can_write_day_meta() (+14 more)

### Community 93 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.08
Nodes (24): ApiException, TranslationUnavailableException, descCt, _encryptedMemory, fetchComments, fetchLikes, key, main (+16 more)

### Community 94 - "Map"
Cohesion: 0.08
Nodes (25): buildPickedPhoto, writeDms, _asymmetricQuadrantImage, _buildExifBytes, bytes, _checkerboardPngBytes, dtBytes, exifIfdOffset (+17 more)

### Community 95 - "Meeting a person or group on a given day/place (issue #40, #56) — owner-only, pe"
Cohesion: 0.07
Nodes (19): _configured_token(), metrics(), Request, Prometheus scrape endpoint (issue #125).  Not under ``/api`` — ``/metrics`` is, Read METRICS_TOKEN at request time, not import time, so a deployment can     be, Expose the process' metrics in Prometheus text format.      Returns 404 when `, Response, The /metrics scrape endpoint and its HTTP instrumentation (issue #125).  Exerc (+11 more)

### Community 96 - "One ordered entry in a project — an activity ref, segment, memory, journal, or e"
Cohesion: 0.05
Nodes (31): Any, Get configuration value using dot notation.          Args:             key: C, from_dict(), from_dict(), from_dict(), _person_from_dict(), _person_to_dict(), _mk_user() (+23 more)

### Community 97 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.12
Nodes (37): accept_invite(), create_invite(), _display_name(), _get_invite(), InviteAcceptedOut, InviteCreateBody, InvitePreviewOut, InviteTokenOut (+29 more)

### Community 98 - "people_screen.dart"
Cohesion: 0.03
Nodes (66): CircleAvatar, Column, Divider, Flexible, Function, Icon, InkWell, LayoutBuilder (+58 more)

### Community 99 - "journal_detail_modal.dart"
Cohesion: 0.04
Nodes (57): Column, Container, Dialog, Divider, Function, GestureDetector, Row, showDialog (+49 more)

### Community 100 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.09
Nodes (38): _build_full_geo_features(), _geo_cache_get(), _geo_cache_store(), _geo_generation(), _gzip_geo(), _legacy_path(), _linestring(), _place_label() (+30 more)

### Community 101 - "A cached translation of a memory's name and description."
Cohesion: 0.08
Nodes (24): dart:ui, _activity, BrandMark, build, _destination, _feeder, _fillTriangle, _hollow (+16 more)

### Community 102 - "A memory's name/description re-encrypted under a per-share content key     (iss"
Cohesion: 0.13
Nodes (14): _alembic(), migrated(), Path, The #110 migration's data backfill (revision c8f1a2b3d4e5).  Runs the real mig, Nothing ever checked that a local account's address was real —         which is, Own DB — this mutates schema, and the shared fixture is read-only., Populate a DB at *_PREVIOUS* with the three account shapes that exist     in th, A seeded DB upgraded through #110.      Module-scoped and read-only for its co (+6 more)

### Community 103 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.07
Nodes (29): Container, Divider, Scaffold, SizedBox, Text, build, createState, dispose (+21 more)

### Community 104 - "A user's per-device X25519 public key and the CMK wrapped to it.      A new de"
Cohesion: 0.09
Nodes (22): Client, jsonDecode, api, baseUrl, body, clearToken, _client, delete (+14 more)

### Community 105 - "The CMK wrapped under a user-chosen recovery method (issue #26).      method=""
Cohesion: 0.13
Nodes (20): REST transport-segment endpoints — create/update/delete + async route resolution, HafasError, Exception, RailGeometry, Result of a rail-geometry resolution.      Carries *how* the polyline was obta, Tests for VR (Finnish Railways) HAFAS support and the two-endpoint train route-r, IC 3' is normalised to '3' before the API call., Empty schedule list raises HafasError. (+12 more)

### Community 107 - "A cached translation of a memory's name and description."
Cohesion: 0.16
Nodes (12): align_points(), points_to_elevation_profile(), points_to_polyline(), Re-derive ``(distances_km, elevations_m)`` from an ordered point list.      Re, Align a polyline and an elevation profile into one ordered point list.      El, Re-encode an ordered point list to a Google-encoded polyline string., _low_res_ep_json(), _parse_ep() (+4 more)

### Community 108 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.12
Nodes (21): GPXProcessor, _make_point(), merge_with_segments(), GPX processing: merge tracks and export to GPX format., Controls how tracks are merged and what data is written.      Attributes:, Merges Track objects and exports them as a GPX document., Combine tracks into one GPX document.          Args:             tracks: Sour, Track and TrackPoint models for full-resolution GPS data. (+13 more)

### Community 109 - "A cached translation of a memory's name and description."
Cohesion: 0.05
Nodes (54): _decoded(), env(), _items(), _points_body(), #104: dropping the boundary point leaves the tail starting one point later,, A cut made on top of unsaved edits compounds with them (issue #127)., An index valid for the stored track but out of range for the shorter     edited, Omitting points keeps the pre-#127 behaviour — the split is taken from     the (+46 more)

### Community 110 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.05
Nodes (37): ProjectService, _ViewProjectService, _SharedProjectService, _activity, detailsActivities, detailsCalls, detailsError, _fast (+29 more)

### Community 111 - "A user's per-device X25519 public key and the CMK wrapped to it.      A new de"
Cohesion: 0.07
Nodes (27): Column, SizedBox, Spacer, applyPaste, build, controller, _copy, NoteFieldActions (+19 more)

### Community 112 - "The CMK wrapped under a user-chosen recovery method (issue #26).      method=""
Cohesion: 0.04
Nodes (43): double?, RangeError, deleteLocalActivity, getActivityTrack, getDetails, getDetailsMeta, getGeo, getLowResGeo (+35 more)

### Community 113 - "Convert a Unix timestamp or ISO-8601 string to YYYY-MM-DD."
Cohesion: 0.22
Nodes (14): _enable_body(), enc_env(), _make_app(), FastAPI, test_approve_unknown_device_404(), test_enable_rejects_unknown_recovery_method(), test_enable_stores_wraps_and_flips_flag(), test_enable_twice_conflicts() (+6 more)

### Community 114 - "Slim down a Polarsteps trip dict for the API response."
Cohesion: 0.11
Nodes (16): _, actIds, activityById, dayRoutePoints, features, lastDate, points, segIds (+8 more)

### Community 115 - "Slim down a Polarsteps step dict for the API response."
Cohesion: 0.12
Nodes (13): env(), API tests for the poster job endpoints (issue #14, Unit A)., With no MAPBOX_TOKEN configured, the job must end 'failed' with an     error me, A job created by one user is invisible (404, not leaked) to another., A preview render failure must return a 500 whose detail carries the     underly, POST creates a job and returns a job_id; the row starts 'pending' until     the, _seed(), test_create_job_returns_id_and_stays_pending_until_run() (+5 more)

### Community 116 - "project_stats_counters.dart"
Cohesion: 0.08
Nodes (26): _as_float(), _as_int(), _customer_id(), _period_end(), _plan_from_metadata(), _price_object(), Pure translation of provider webhook events into subscription state (#121).  N, Read the period end, tolerating both Stripe payload generations.      ``curren (+18 more)

### Community 117 - "share_asset_source_impl.dart"
Cohesion: 0.09
Nodes (19): Function, performOffscreenExport, _, fetchPhotos, notifier, renderMapImage, createShareCapabilities, notifier (+11 more)

### Community 118 - "ConfigurationError"
Cohesion: 0.08
Nodes (58): android_assetlinks(), _android_cert_fingerprints(), app_version(), _auth_error_handler(), _quota_handler(), Combines all REST API sub-routers into a single FastAPI app., Cache-Control policy for a Flutter-web asset path.      Flutter does NOT content, Serve the Flutter web build; fall back to index.html for SPA routing. (+50 more)

### Community 119 - "projects_screen.dart"
Cohesion: 0.03
Nodes (75): ../auth/verify_email_banner.dart, ../billing/upgrade_sheet.dart, Column, Padding, Scaffold, SizedBox, TextSpan, Card (+67 more)

### Community 120 - "Create an Activity instance from Strava API response data."
Cohesion: 0.13
Nodes (26): _build_rail_graph(), _clean_uic(), _dijkstra(), _enrich_uic(), _find_station_near(), _find_uic_near(), _get_route_geometry(), _nearest_node() (+18 more)

### Community 121 - "test_tile_stitcher.py"
Cohesion: 0.06
Nodes (65): crop_rect_for_bounds(), _default_tile_fetcher(), lonlat_to_pixel(), _mapbox_token(), MapboxTileClient, Image, TileFetcher, Web Mercator tile math + Mapbox raster-tile stitching for poster basemaps (issu (+57 more)

### Community 124 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.24
Nodes (4): share_client(), TestSharedGetTranslationRejectsEncrypted, TestSharedProjectMetaStripsCiphertext, TestSharedProjectStripsCiphertext

### Community 125 - "photo_upgrade_screen_test.dart"
Cohesion: 0.07
Nodes (27): Container, main, _clearJpgHash, _day, _decorationOf, _FakeNotifier, _fakeThumbnailHash, _farHash (+19 more)

### Community 126 - "One ordered entry in a project — an activity ref, segment, memory, journal, or e"
Cohesion: 0.08
Nodes (24): ../core/return_to.dart, Container, ElevatedButton, Scaffold, SizedBox, _confirmCtrl, createState, dispose (+16 more)

### Community 127 - "poster_config_dialog_test.dart"
Cohesion: 0.13
Nodes (11): change_password(), Change password — local (email) accounts only. Returns 403 for Google accounts., hash_password(), Idempotent bootstrap of the default admin account.  Called from the FastAPI li, Create the default admin account if no ``admin`` LocalUser exists., seed_admin(), Admin bootstrap + auth-wiring tests (issue #25).  Covers seeded admin creation, TestForcedChange (+3 more)

### Community 128 - "share_client"
Cohesion: 0.23
Nodes (11): strava_callback(), OAuth2Session, Any, Configuration management for ViewTrip., DummyConfig, Unit tests for OAuth2Session., test_authorization_url_contains_required_params(), test_exchange_code_failure() (+3 more)

### Community 129 - "A cached translation of a memory's name and description."
Cohesion: 0.24
Nodes (16): _create_encounter(), _create_group(), env(), The person sheet edits encounters in place (issue #175), so each row has     to, _seed(), test_create_group_appears_in_project(), test_delete_group_ungroups_members(), test_get_group_members_empty_then_set() (+8 more)

### Community 130 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.08
Nodes (25): add track_style columns to project  Revision ID: f1a2b3c4d5e6 Revises: e5f6a7b8c, upgrade(), add share_token_no_memories and sharevisit table  Revision ID: f3a1d8e2c749 Revi, upgrade(), downgrade(), add lock_version to project  Adds an optimistic-lock counter to the project tabl, upgrade(), downgrade() (+17 more)

### Community 131 - "segment_dialog.dart"
Cohesion: 0.04
Nodes (55): AlertDialog, Column, Divider, Duration, Function, SizedBox, Spacer, Text (+47 more)

### Community 132 - "encryption_service.dart"
Cohesion: 0.04
Nodes (53): StateError, answers, _api, approveDevice, _argonFrom, _cmk, decryptText, deviceApproved (+45 more)

### Community 133 - "shared_project_screen.dart"
Cohesion: 0.04
Nodes (52): AnimatedMapController, anonymous_id.dart, Center, Column, ListTile, load, Material, Row (+44 more)

### Community 134 - "photo_match.dart"
Cohesion: 0.04
Nodes (51): double? memoryLon,
  double, ambiguityMargin, bounds, candidateIndex, capturedAt, classifyDayGeoMatch, confidence, contains (+43 more)

### Community 135 - "CustomPainter"
Cohesion: 0.18
Nodes (11): @visibleForTesting, effectiveSegmentDate, computeSelectionStats, frameRectFor, memoArcMidpoint, memoCoordsToLatLng, SelectionStatsData, effectiveDayTags (+3 more)

### Community 136 - "share_strategy.dart"
Cohesion: 0.19
Nodes (12): get_rail_geometry(), OverpassError, Exception, Resolve [[lon, lat], …] rail geometry from stops[0] to stops[-1].      *stops*, Reject self-overlapping / wrong-relation geometry that is implausibly long     f, Point-1 observability: rail must self-report when it silently fell back to     a, Every Overpass call raises (network down/blocked) → strategies A/B/C         all, Overpass reachable but returns no rail elements → no graph → straight         ch (+4 more)

### Community 137 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.05
Nodes (39): adminOverride, _api, billingEnabled, cancelAtPeriodEnd, canManage, checkoutUrl, covers, currentPeriodEnd (+31 more)

### Community 138 - "A cached translation of a memory's name and description."
Cohesion: 0.47
Nodes (3): _counts(), _insert_memory(), TestCreateMemoryDedup

### Community 139 - "_TsMetric"
Cohesion: 0.05
Nodes (49): create_access_token(), decode_token(), jwt_secret(), The session signing key. Raises when it is not safely configured.      There i, Create a signed JWT for the given UserInfo.      ``password_change_required``, Decode and verify a JWT. Raises HTTPException on failure., _check_schema_contract(), Raise RuntimeError if DBProject columns diverge from the registry.      Called (+41 more)

### Community 140 - "_TsOp"
Cohesion: 0.11
Nodes (9): Admin dashboard support: bootstrap seeding, storage accounting, tiers., API client modules for ViewTrip., Authentication helpers for Strava API., Configuration management for ViewTrip., Custom exceptions for ViewTrip., ViewTrip - build and share trip maps from Strava, Polarsteps and more., Models package for ViewTrip., Poster generation package (issue #14): high-resolution A0 trip posters. (+1 more)

### Community 141 - "_ProjectStatsScreenState"
Cohesion: 0.30
Nodes (5): project_day_bounds(), Earliest and latest date this trip touches, from every dated thing in it., _memory(), A trip declared to start earlier than its first activity is that long         —, TestProjectDayBounds

### Community 142 - "SegmentDialog"
Cohesion: 0.24
Nodes (8): _FakeResp, Gracious Polarsteps token-expiry handling.  Polarsteps' unofficial API authentic, _stored_token(), test_client_captures_rotated_cookie(), test_client_no_rotation_leaves_token_unchanged(), test_expired_token_raises_detectable_401(), test_trips_persists_rotated_token(), test_trips_unchanged_token_not_rewritten()

### Community 143 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.18
Nodes (10): Find OSM route=train/railway relations that pass through *both* endpoint     ar, _via_train_relations_endpoints(), _make_relation(), Build a fake Overpass relation element., Strategy B returns geometry for a relation near both endpoints., No intersection → OverpassError, not a 2-point chord., Relation found but its geometry doesn't match the query endpoints., get_rail_geometry falls through to Strategy B when UIC enrichment fails. (+2 more)

### Community 144 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.20
Nodes (9): AdminService, broadcastEmail, deleteUser, getStats, refreshStorage, resetPassword, searchUsers, setAdmin (+1 more)

### Community 145 - ".token_rotated"
Cohesion: 0.11
Nodes (13): How many days the trip would span once ``extra_dates`` are part of it., trip_days_used(), bounds(), normalise(), Reduce a stored date to ``YYYY-MM-DD``, or None if it isn't one.      Dates ar, (earliest, latest) of the parseable dates, or (None, None) if there are none., Inclusive day count between two dates. 0 when either end is unknown., Inclusive day count covering every date in ``values``. (+5 more)

### Community 148 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.23
Nodes (13): description_for(), env_var(), lookup_key(), main(), product_id(), Ensure a price with the right amount exists. Returns (price_id, report)., Delegates to plans.py — one definition, shared with the server., The environment variable the server reads this price id from. (+5 more)

### Community 149 - "view_screen.dart"
Cohesion: 0.04
Nodes (49): activity_panel.dart, ../core/stale_shared_ref.dart, Center, ChangeNotifierProvider, Column, Function, IconButton, load (+41 more)

### Community 150 - "Scalar API reference UI."
Cohesion: 0.27
Nodes (6): Add ``delta_bytes`` (may be negative) to a user's counted storage.      Never, record_delta(), A double-counted delete must not hand the account infinite headroom., An upload that already hit disk must not 500 because of bookkeeping., TestRecordDelta, _usage()

### Community 151 - "Version this image was built from (the git tag baked in at build time).      T"
Cohesion: 0.16
Nodes (13): new(), env(), _jpeg_bytes(), _seed(), test_avatar_upload_serve_delete(), test_cannot_access_another_users_person(), test_create_person_and_appears_in_project(), test_create_person_without_name_is_allowed() (+5 more)

### Community 152 - "Serve the Flutter web build; fall back to index.html for SPA routing."
Cohesion: 0.22
Nodes (11): _parse_ps_username(), Extract a Polarsteps username from a stored handle or profile URL.      Accept, env(), _FakeClient, _seed(), test_handle_parsing(), test_lists_trip_steps(), test_lists_trips() (+3 more)

### Community 153 - "e2ee_spike.dart"
Cohesion: 0.04
Nodes (48): SecretKey, _aead, argon2, Argon2Params, blob, box, bytes, ciphertext (+40 more)

### Community 154 - "google_button_web.dart"
Cohesion: 0.02
Nodes (125): ProjectRef, LatLng, LatLng, Exception, buildGoogleSignInButton, buildGoogleSignInButton, SizedBox, changePasswordError (+117 more)

### Community 155 - "_BulkTagDialog"
Cohesion: 0.10
Nodes (29): Per-user subscription state, as last reported by the payment provider., Subscription, apply_update(), _by_customer(), get_or_create(), get_subscription(), Applying provider events to stored subscription state (issue #121).  Webhooks, Grant or clear an operator-granted plan (``""`` clears it). (+21 more)

### Community 157 - "FilterSheet"
Cohesion: 0.14
Nodes (13): BaseException, _configure_sqlite(), Tune SQLite for concurrent access.      Without this, SQLite runs with journal, db_error_kind(), Classify a database failure, or return None if it isn't one.      Application, file_engine(), Database metrics — query volume/latency, pool saturation, file growth and error, A failed login raises HTTPException from inside a get_session()         block; (+5 more)

### Community 158 - "Serve the Flutter web build; fall back to index.html for SPA routing."
Cohesion: 0.27
Nodes (7): _extract_relation_geometry(), Extract a single clean start→end polyline from a route relation.      Route re, _path_len(), Regression for the Helsinki→Rovaniemi self-overlapping polyline.      A train ro, A 1.0°-long north-bound main line with a dead-end siding branching         east, TestTrainRelationGraphExtraction, _way()

### Community 160 - "ManageMapPanel"
Cohesion: 0.33
Nodes (6): ManageMapPanel, ManageMapPanelState, MapPanel, _MapPanelState, _PolarstepsOverlayFit, T

### Community 162 - "A cached translation of a memory's name and description."
Cohesion: 0.04
Nodes (28): GatewayError, Exception, A call to the payment provider failed., Install a gateway (tests inject a fake). ``None`` restores the default., set_gateway(), _checkout_event(), client(), engine() (+20 more)

### Community 163 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.29
Nodes (3): _register(), TestDisplayName, TestEmailIsRequired

### Community 164 - "MapPanel"
Cohesion: 0.12
Nodes (15): dart:async, dart:js_interop, blob, downloadPngImpl, url, connect, dispose, _messageHandler (+7 more)

### Community 165 - "Timestamps older than WINDOW_SECONDS should not count toward usage."
Cohesion: 0.21
Nodes (7): haversine_km(), Great-circle path computation using SLERP on unit ECEF vectors., Great-circle distance in kilometres (Haversine formula)., Tests for great_circle.py — no Qt required., Paris → London is roughly 340 km., NYC → Tokyo is roughly 10 800 km., TestHaversineKm

### Community 166 - "render_invite_email"
Cohesion: 0.15
Nodes (12): PosterConfigOptions, cancel, _defaults, fieldsByTitle, main, _openAndConfirm, pumpAndSettle, pumpWidget (+4 more)

### Community 167 - "dart:math"
Cohesion: 0.09
Nodes (17): plan_for_lookup_key(), price_lookup_key(), Stable, account-independent handle for a paid plan's provider price.      Prov, Inverse of :func:`price_lookup_key`; None when the key is not one of ours., plan_for_price_object(), Map a price *object* from a webhook payload to the plan it grants.      Prefer, Prices resolve by lookup key, not by an account-scoped id (issue #154)., Fake SDK recording how many lookups were actually performed. (+9 more)

### Community 169 - "share_strategy.dart"
Cohesion: 0.35
Nodes (4): Return a list of warning strings; empty list means the file is valid., validate(), One valid track + one 1-point track → warning for the short one only., TestGPXProcessorValidate

### Community 170 - "main"
Cohesion: 0.18
Nodes (10): add_speed_dial.dart, day_meta_editor.dart, AddSpeedDial, SnackBar, encounter_dialog.dart, buildProjectAddFab, openDay, useSheet (+2 more)

### Community 171 - "PinSpec"
Cohesion: 0.05
Nodes (82): ImageDraw, ProgressFn, card_width_px(), mm_to_px(), assemble_card_content(), _compose_poster_image(), _draw_card(), _draw_card_chrome() (+74 more)

### Community 172 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.33
Nodes (5): Forget every recorded request. For tests — the shared limiters are         proc, Clear both shared windows. For tests., reset_rate_limiters(), Clear the process-wide Strava quota windows around every test.      The limite, _reset_strava_rate_limiters()

### Community 173 - "TestVrHafas"
Cohesion: 0.80
Nodes (4): api_headers(), delete_memory(), get_project(), main()

### Community 174 - "A like on a memory — posted by an authenticated user."
Cohesion: 0.14
Nodes (15): _add_journal(), _add_memory(), _enforcing(), env(), The per-trip day limit, end to end through the real app (issue #121).  Free tr, Two memories 20 days apart are a 20-day trip, not a 2-day one., Clearing can only shrink the span, so it must never be refused —         includ, A trip that was already longer than the limit when enforcement was     switched (+7 more)

### Community 176 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.25
Nodes (4): Delete all cache files., Number of activities in the cache (fast — reads metadata only)., TestClear, client()

### Community 177 - "project_filter_mixin.dart"
Cohesion: 0.04
Nodes (44): bool get, dynamic get, activeFilterCount, activities, activityTypeFilter, best, clearAllFilters, dayHasOwnTags (+36 more)

### Community 178 - "recover_screen.dart"
Cohesion: 0.05
Nodes (39): ../api/client.dart, ../core/project_ref.dart, ../crypto/e2ee_crypto.dart, device_key_store.dart, EncryptionStatus, RecoveryWrapData, shareKeyToBase64, encryption_api_http.dart (+31 more)

### Community 179 - "TestUniqueStepIdIndex"
Cohesion: 0.29
Nodes (5): The /api/version probe the web client uses to detect a stale cached bundle., Issue #179: reading a log file must tell you which build produced it., test_startup_logs_running_version(), test_version_defaults_to_dev_without_env(), test_version_reports_baked_app_version()

### Community 180 - "_TsMetric"
Cohesion: 0.39
Nodes (5): _get(), _keep_layer(), main(), _post(), TestTranslateCounters

### Community 181 - "_TsOp"
Cohesion: 0.39
Nodes (3): Pure mapping from (enabled, method) to an encryption tier string.      Disable, tier_from(), TestTierFrom

### Community 182 - "encounter_dialog.dart"
Cohesion: 0.04
Nodes (46): ../core/current_location.dart, AlertDialog, Icon, SizedBox, SnackBar, afterPeriod, buffer, build (+38 more)

### Community 183 - "test_quota_enforcement.py"
Cohesion: 0.15
Nodes (13): _enforcing(), env(), _jpeg_bytes(), _memory(), Plan limits, end to end through the real app (issue #121).  What these pin dow, The landing page promises unlimited projects when you run it yourself., Photos on a shared trip live in the owner's tree, so they are the         owner, In-memory DB + the real app, authenticated as user 1 (owner of "Trip 1"). (+5 more)

### Community 184 - "enable_encryption_screen.dart"
Cohesion: 0.05
Nodes (44): Center, Column, Container, EncryptionMigration, Icon, ListView, Opacity, QnaChoice (+36 more)

### Community 185 - "recover_screen.dart"
Cohesion: 0.05
Nodes (39): e2ee_crypto.dart, Center, Icon, ListView, Scaffold, SizedBox, Text, SecretKey (+31 more)

### Community 186 - "jwt_secret"
Cohesion: 0.33
Nodes (6): _crow_km(), _polyline_km(), _rail_length_ok(), Straight-line distance in km (equirectangular; same approx as _dijkstra)., Total length in km of a [[lon, lat], …] polyline., True if *poly* is a plausible rail path for *stops* — i.e. not a     self-overl

### Community 188 - "DBPosterJob"
Cohesion: 0.14
Nodes (30): BoundsIn, create_poster_job(), download_poster(), _get_owned_job(), get_poster_job_status(), JobIdOut, JobStatusOut, _poster_dir() (+22 more)

### Community 190 - "plan_picker.dart"
Cohesion: 0.08
Nodes (24): PlanInfo, because, _billing, build, busy, _busyPlan, _buy, cheapestPlanCovering (+16 more)

### Community 192 - "plan_name"
Cohesion: 0.04
Nodes (42): plan_display_name(), Name to show for a plan id — falls back sanely for an unknown one., catalogue(), cheapest_plan_with(), _env_int(), features_for(), _format_bytes(), is_at_least() (+34 more)

### Community 193 - "A cached translation of a memory's name and description."
Cohesion: 0.07
Nodes (23): _enrich_activities(), Fetch streams for each activity, enriching summary_polyline and elevation_profil, RateLimitError, Raised when the app's own Strava quota window is full.      A subclass of APIE, _client(), DummyConfig, Strava rate limiting is per *application*, not per request (issue #130).  The, The point of a limiter: the call never reaches Strava. The 429 retry         pa (+15 more)

### Community 194 - "Per-user cache of the raw Strava activity list.      One row per user; the ent"
Cohesion: 0.09
Nodes (23): build, createState, _kGoogleServerClientId, main, _router, ViewTripApp, _ViewTripAppState, ThemeNotifier (+15 more)

### Community 195 - "project_notifier_members_test.dart"
Cohesion: 0.09
Nodes (21): expectLater, createCalls, createInvite, _editor, failRemove, getDetails, getDetailsMeta, getGeo (+13 more)

### Community 196 - "test_android_release_config.py"
Cohesion: 0.11
Nodes (18): _attr(), Android release-build invariants (issue #136).  The Flutter template produces, Without this the engine never hands the intent URL to go_router., The dev-server exemption must stay scoped to debug builds., Declared in src/debug only, a release APK has no network access at all., The encounter picker defaults to the current position., Both must be the published identity — it cannot change after release., `.MainActivity` in the manifest resolves relative to the namespace. (+10 more)

### Community 197 - "stale_shared_ref_test.dart"
Cohesion: 0.33
Nodes (5): dart:math, getOrCreateAnonId, id, _kKey, prefs

### Community 198 - "manage_devices_screen.dart"
Cohesion: 0.12
Nodes (17): ../core/design_tokens.dart, Center, ListTile, Scaffold, SnackBar, _approve, _approving, _body (+9 more)

### Community 199 - "great_circle.dart"
Cohesion: 0.17
Nodes (11): dot, greatCirclePoints, nPoints, omega, points, sinOmega, toEcef, toGeoPoint (+3 more)

### Community 200 - "billing_section.dart"
Cohesion: 0.12
Nodes (17): _billing, BillingSection, _BillingSectionState, build, _busy, _card, _changePlan, _Chip (+9 more)

### Community 201 - ".start"
Cohesion: 0.13
Nodes (11): HTTPServer, _DualStackServer, OAuthCallbackServer, OAuth callback handler for Strava authentication., Stop the callback server., Wait for OAuth callback and return the auth code., HTTPServer that accepts both IPv4 and IPv6 loopback connections.      On Windo, Simple HTTP server to handle OAuth callbacks. (+3 more)

### Community 202 - "project_stats_timeseries.dart"
Cohesion: 0.12
Nodes (16): _push, _RideTimeSeriesChart, _RideTimeSeriesSection, _RideTimeSeriesSectionState, _tsFormatY, _tsRawValue, _TsSeries, Chip (+8 more)

### Community 203 - "version_code"
Cohesion: 0.16
Nodes (15): main(), Return the Android versionCode for a ``vX.Y.Z`` tag.      Raises ValueError on, version_code(), Tag -> Android versionCode mapping (issue #136).  Android decides whether an A, Across a plausible release sequence, including the rollovers., The bump script's -Patch can run many times before the next feature bump., A mistyped tag must break the build, not ship a wrong code., Beyond 99 the components would collide (0.100.0 and 1.0.0 both -> 10000). (+7 more)

### Community 204 - "test_encounters_api.py"
Cohesion: 0.23
Nodes (16): _create(), _create_with_group(), env(), _seed_group(), test_create_encounter_appears_as_item(), test_create_encounter_requires_exactly_one_of_person_or_group(), test_create_encounter_with_group(), test_custom_geo_is_respected() (+8 more)

### Community 205 - "settings_service.dart"
Cohesion: 0.13
Nodes (14): Exception, connectPolarsteps, deleteAccount, _detail, disconnectPolarsteps, disconnectStrava, getPolarstepsStatus, getProfile (+6 more)

### Community 206 - "project_stats_counters.dart"
Cohesion: 0.15
Nodes (13): Column, dayOff, FlSpot, GestureDetector, Padding, xLabel, _CounterChart, _CounterSection (+5 more)

### Community 207 - "share_asset_source_impl.dart"
Cohesion: 0.40
Nodes (4): GPX, GPXTrackPoint, Build a GPX document respecting project item order (activities + segments)., Build a GPXTrackPoint, respecting include_time / include_elevation.

### Community 208 - "test_assetlinks.py"
Cohesion: 0.15
Nodes (9): Digital Asset Links statement for Android App Links (issue #136).  This one sm, The catch-all only exists when web_client/ is built (not in CI), so assert, A mismatch verifies nothing, with no error anywhere to show for it., Copied out of a keytool listing or a console, case varies; Android's     compar, Better than an empty statement: Android caches a failed verification, so     pu, test_404s_when_unconfigured(), test_lowercase_fingerprints_are_normalised(), test_package_matches_the_gradle_application_id() (+1 more)

### Community 209 - "One visitor record for a shared-project link.      Keyed on (project_id, token"
Cohesion: 0.10
Nodes (19): ArgumentError, ShareAssetSourceImpl, ShareAssetSource, ShareLinkResolver, ShareLinkResolverImpl, assets, _buildIntentUri, caps (+11 more)

### Community 210 - "run-android.ps1"
Cohesion: 0.24
Nodes (8): Die(), Get-JavaMajor(), Note(), Resolve-Jdk(), Sdk-Tool(), Send-DeepLink(), Start-App(), Step()

### Community 212 - "main"
Cohesion: 0.50
Nodes (4): main(), Main release function., Run the test suite and return True if all tests pass., run_tests()

### Community 216 - "upgrade_sheet.dart"
Cohesion: 0.18
Nodes (10): billing_service.dart, context, error, launcher, maybeShowUpgradeSheet, service, showPlanPicker, showUpgradeSheet (+2 more)

### Community 217 - "test_migration_split_parent_id.py"
Cohesion: 0.29
Nodes (9): _cfg(), _parents(), Path, Data-migration test for 90b8faeea0f3 — backfill split_parent_id (issue #143)., Insert an activity row using only the columns that exist AT _PREV_REV.      Sa, Nothing to backfill on a DB with no split families — the column is added     an, _seed_activity_row(), test_backfill_leaves_a_fresh_db_empty() (+1 more)

### Community 218 - "project_stats_body.dart"
Cohesion: 0.20
Nodes (9): Column, Divider, Padding, PieChartSectionData, Row, SingleChildScrollView, SizedBox, _StatsBody (+1 more)

### Community 219 - "image_export.dart"
Cohesion: 0.04
Nodes (55): basemaps.dart, LatLng, AlertDialog, Function, Positioned, SizedBox, elevation_chart.dart, currentDeviceLatLng (+47 more)

### Community 220 - ".to_strava_dict"
Cohesion: 0.31
Nodes (5): from_strava_api(), Create an Activity instance from Strava API response data., Serialise to a dict that can be round-tripped via from_strava_api()., to_dict(), TestActivityRoundTrip

### Community 223 - "TestPriceLookupKeys"
Cohesion: 0.22
Nodes (4): Account-independent handles for provider prices (issue #154)., So a second currency can be added without colliding with these., scripts/stripe_catalog.py stamps the key the server later resolves by., TestPriceLookupKeys

### Community 224 - "_cache_control_for"
Cohesion: 0.31
Nodes (8): _cache_control_for(), Cache-Control policy for a Flutter-web asset path.      Flutter does NOT conte, Serve the Flutter web build; fall back to index.html for SPA routing., spa_fallback(), Cache-Control policy for the served Flutter web build.  Regression guard for the, test_app_entry_points_are_never_long_cached(), test_static_trees_are_cacheable(), test_unknown_root_files_default_to_no_cache()

### Community 227 - "draw_logo"
Cohesion: 0.10
Nodes (26): _chain(), _draw_mark(), _draw_reduced_mark(), _glyph(), main(), _mix(), _on_field(), _Pen (+18 more)

### Community 229 - "List"
Cohesion: 0.07
Nodes (26): tool, EditTool get, TrackEditModel, addPointAfter, applyTrim, canCutForTransport, canSave, canSplitAt (+18 more)

### Community 230 - "merge"
Cohesion: 0.18
Nodes (8): ExportOptions, merge(), Write GPX document to *path* as indented XML., _make_track(), TestExportOptionsConcatenate, TestExportOptionsDataContent, TestGPXProcessorMerge, TestGPXProcessorSave

### Community 231 - "String?"
Cohesion: 0.05
Nodes (36): ../core/countries.dart, AlertDialog, Column, SizedBox, Spacer, Country, countryName, kCountries (+28 more)

### Community 233 - "polyline_decoder.dart"
Cohesion: 0.09
Nodes (22): a, b, cumDist, decodePolyline, dLat, dLon, elevTotalKm, h (+14 more)

### Community 234 - "dart:typed_data"
Cohesion: 0.06
Nodes (29): dart:typed_data, qnaWrapKey, qnaWrapKey, triggerBrowserDownload, downloadPng, downloadPngImpl, image_download_stub.dart, package:e2ee_spike/e2ee_spike.dart (+21 more)

### Community 235 - "design_tokens.dart"
Cohesion: 0.05
Nodes (40): activityTypeBucket, color, defaultTypeColor, defaultTypeLineStyle, iconBoxBg, iconBoxFg, kAccent, kAccentDark (+32 more)

### Community 236 - ".delete"
Cohesion: 0.07
Nodes (29): Regression: deleting a split tail via the timeline must not orphan its row., test_delete_local_removes_row_and_item(), test_delete_split_item_removes_local_row_and_allows_resplit(), TestDeleteUser, test_full_companion_journey(), _invite(), _join(), Emailing an already-existing invite to a second address doesn't     create a se (+21 more)

### Community 237 - "social_share_controller.dart"
Cohesion: 0.11
Nodes (18): canShareFiles, copyToClipboard, fetchPhotos, renderMapImage, resolveMemoryLink, shareFiles, shareTextOnly, ShareTransport (+10 more)

### Community 239 - "get_current_user"
Cohesion: 0.05
Nodes (78): get_current_user(), FastAPI dependency — validates JWT and returns the decoded payload., decline_invite(), list_members(), list_pending_invites(), Depends, Delete the project's invite token. Existing members are unaffected., Invites emailed to an address that hasn't joined yet (issue #110).     Co-owner (+70 more)

### Community 240 - "auth_notifier.dart"
Cohesion: 0.05
Nodes (41): authProvider, avatarUrl, clearError, displayName, email, emailVerified, _error, _extractMessage (+33 more)

### Community 241 - "activity_editor_page_test.dart"
Cohesion: 0.04
Nodes (48): Offset, poly, _activity, _chainNotifier, _controllerOf, _delta, edited, _encode (+40 more)

### Community 260 - "project_stats_screen_test.dart"
Cohesion: 0.15
Nodes (12): ProjectRef, clearLastOpenedProject, lastRef, _prefKey, prefs, raw, readLastOpenedProject, remove (+4 more)

### Community 261 - "return"
Cohesion: 0.10
Nodes (19): encounterCountByGroup, encounterCountByPerson, encounterNotesByGroup, encounterNotesByPerson, encountersByPerson, encountersForGroup, filterPeople, gid (+11 more)

### Community 262 - "photo_source.dart"
Cohesion: 0.06
Nodes (34): PhotoCandidate, buildPickedPhoto, bytes, candidate, capturedAt, computeAverageHash, data, dateRaw (+26 more)

### Community 263 - "social_share_controller_test.dart"
Cohesion: 0.06
Nodes (33): _NativeShareCapabilities, ShareCapabilities, canShareFiles, _Caps, main, calls, canShareFiles, clipboard (+25 more)

### Community 268 - ".set"
Cohesion: 0.08
Nodes (37): Config, OAuth2 helper for Strava authentication., Simple OAuth2 session manager for Strava., Config, Configuration management for ViewTrip., Set configuration value using dot notation.          Args:             key: C, Validate Strava configuration.          Returns:             True if valid St, Initialize configuration.          Args:             config_file: Path to con (+29 more)

### Community 269 - "strava_import_screen.dart"
Cohesion: 0.08
Nodes (36): AdminScreen, _AdminScreenState, WelcomeScreen, _WelcomeScreenState, _ProgressBar, _ProgressBarState, AddSpeedDial, _AddSpeedDialState (+28 more)

### Community 271 - "test_strava_client.py"
Cohesion: 0.06
Nodes (42): Any, Ensure access token is valid, refresh if needed., Clear stored token data., Store initial token data., Make an authenticated request with rate limiting and retry logic.          Ret, Fetch list of activities., Fetch full metadata for a single activity., Fetch GPS streams (latlng, altitude, time, distance) for a single activity. (+34 more)

### Community 272 - "tile_renderer.py"
Cohesion: 0.10
Nodes (32): Bounds, Lock, _annotate_bboxes(), _bbox_from_features(), _do_prerender(), get_or_build_features(), get_or_create_tile(), Any (+24 more)

### Community 273 - "photo_upgrade_screen.dart"
Cohesion: 0.06
Nodes (34): AlertDialog, computeAverageHash, Container, Icon, SizedBox, DayGeoMismatch, PickedPhoto, build (+26 more)

### Community 275 - "polarsteps_import_screen.dart"
Cohesion: 0.07
Nodes (32): Center, CheckboxListTile, Column, Divider, Icon, ListTile, SafeArea, Scaffold (+24 more)

### Community 276 - "test_admin.py"
Cohesion: 0.07
Nodes (16): _admin_app(), admin_client(), client(), ctx(), fake_email(), _FakeEmailService, _mk_user(), FastAPI (+8 more)

### Community 278 - "polarsteps_import_notifier.dart"
Cohesion: 0.06
Nodes (31): projectRef, StateError, alreadyImportedIds, _api, clearSelection, clearTrip, _detail, error (+23 more)

### Community 279 - "strava_import_notifier.dart"
Cohesion: 0.06
Nodes (31): activities, addSelected, allTypes, _applyEnvelopeMeta, clearSelection, _currentPage, endDate, error (+23 more)

### Community 282 - "encounter_dialog_test.dart"
Cohesion: 0.04
Nodes (53): ProjectNotifier, Finder get, ProjectListEntry, main, created, createEncounter, _FakeNotifier, group (+45 more)

### Community 283 - "_compute_stats"
Cohesion: 0.21
Nodes (19): _compute_stats(), Any, _activity(), TestDistancePerTag, _project(), _ride(), test_avg_speed_zero_when_no_time(), test_empty_when_no_activities() (+11 more)

### Community 306 - "elevation_chart.dart"
Cohesion: 0.06
Nodes (31): Color, activities, build, color, _compute, createState, ExtraLinesData, FlLine (+23 more)

### Community 313 - "location_picker_dialog.dart"
Cohesion: 0.07
Nodes (29): double get, build, _buildPolylines, createState, Dialog, Icon, LatLng, SizedBox (+21 more)

### Community 314 - "poster_config_dialog.dart"
Cohesion: 0.13
Nodes (15): AlertDialog, Function, allPhotos, build, counters, createState, distance, elevation (+7 more)

### Community 355 - "day_meta_editor_test.dart"
Cohesion: 0.07
Nodes (28): dot, availableTags, btn, counters, countersOnly, dayNumber, distanceKm, effectiveTags (+20 more)

### Community 377 - "social_share_modal_test.dart"
Cohesion: 0.08
Nodes (25): zoom, canShareFiles, clipboard, controller, copyToClipboard, fetchPhotos, intentUri, link (+17 more)

### Community 381 - "client_geo_builder_test.dart"
Cohesion: 0.07
Nodes (24): _encode, _encodeValue, main, prevLat, sb, toString, v, _encode (+16 more)

### Community 388 - "test_photo_replace_api.py"
Cohesion: 0.26
Nodes (5): _insert_journal(), _insert_memory(), _jpeg_bytes(), _other_users_project(), TestJournalPhotoReplace

### Community 403 - "test_resolve_route_async.py"
Cohesion: 0.20
Nodes (24): _find_segment(), _mark_segment_failed(), Background task: resolve a segment's real-world route geometry.      Runs the, Best-effort: flip a still-``pending`` segment to ``failed`` after a crash., _resolve_route_job(), _add_segment(), env(), _load_segment() (+16 more)

### Community 404 - "TestLowResGeoAndFullLoadDoNotCrash"
Cohesion: 0.27
Nodes (10): object, _client(), TestClient, Tests for the /api/auth/google login endpoint.  Focus: verification is resilient, The Google verification must allow a non-zero clock-skew window so a     server, The client only ever sees a generic 401; the real reason is logged     server-si, With no client id configured the endpoint reports unavailable, not 401., test_google_login_forwards_clock_skew_tolerance() (+2 more)

### Community 405 - "admin.py"
Cohesion: 0.09
Nodes (34): broadcast_email(), _counts_by_user(), delete_user(), BackgroundTasks, Depends, GROUP BY aggregate: {user_info_id: row_count} for a per-user table., Totals + per-user breakdown. No memory/journal content is returned., Bust the storage TTL cache so the next /stats re-walks the filesystem. (+26 more)

### Community 406 - "perf_timing.dart"
Cohesion: 0.08
Nodes (23): b, _build, f, idx, instance, janky, kFrameBudgetMs, kPerfNoMap (+15 more)

### Community 407 - "basemaps.dart"
Cohesion: 0.08
Nodes (23): kActiveManageBasemapUrl, kActiveManageStyleUri, kActiveManageSubdomains, kActiveViewBasemapUrl, kActiveViewLabelsOverlayUrl, kActiveViewLabelsSubdomains, kActiveViewStyleUri, kManageBasemapSubdomains (+15 more)

### Community 408 - "add_speed_dial.dart"
Cohesion: 0.10
Nodes (19): AnimationController, Column, FadeTransition, SizedBox, actions, build, _buildAction, createState (+11 more)

### Community 409 - "api/journal.py"
Cohesion: 0.09
Nodes (46): create_encounter(), delete_encounter(), _get_owned_encounter(), Depends, OwnerParam, _require_exactly_one_of_person_or_group(), _require_group_in_project(), _require_person_in_project() (+38 more)

### Community 410 - "project_shares.py"
Cohesion: 0.07
Nodes (40): _admin_emails(), google_login(), _is_admin_email(), login(), BackgroundTasks, Depends, Email + password login — returns a JWT., Create a new local account — returns a JWT.      Also queues a verification em (+32 more)

### Community 411 - "admin_screen_test.dart"
Cohesion: 0.07
Nodes (28): bool?, adminToggledFor, adminToggledTo, broadcastEmail, broadcastEmailError, deleteCalledFor, deleteError, deleteUser (+20 more)

### Community 413 - "theme.dart"
Cohesion: 0.09
Nodes (22): _darkBg, _darkBorder, _darkCard, _darkHint, _darkInput, _darkOnBg, _darkOnCard, darkTheme (+14 more)

### Community 414 - "device_key_store.dart"
Cohesion: 0.09
Nodes (21): clear, delete, FlutterSecureKvStore, _kv, load, read, save, SecureKvStore (+13 more)

### Community 415 - "sync_import_dialog.dart"
Cohesion: 0.10
Nodes (21): CheckboxListTile, Column, Dialog, Divider, Padding, SizedBox, Spacer, _BottomBar (+13 more)

### Community 417 - "client_geo_builder.dart"
Cohesion: 0.10
Nodes (20): activitiesById, _asLatLng, buildFullGeo, buildLowResGeo, _decodeActivityPolyline, end, endLat, endLon (+12 more)

### Community 419 - "version_gate.dart"
Cohesion: 0.11
Nodes (19): SizedBox, Stack, build, _check, child, _clientVersion, createState, didChangeAppLifecycleState (+11 more)

### Community 422 - "downsample_elevation"
Cohesion: 0.16
Nodes (15): _backfill(), add elevation_profile_low_res_json to activity (low-res-first chart)  Stores a d, Downsample existing full profiles into the new column (one-time)., upgrade(), downsample_elevation(), _lttb_indices(), Server-side elevation-profile downsampling for the low-res-first chart.  The ele, Downsample a ``(distances_km, elevations_m)`` profile to ~``max_points``.      U (+7 more)

### Community 430 - "great_circle_points"
Cohesion: 0.19
Nodes (6): great_circle_points(), Return *n_points* (lat, lon) tuples along the great-circle arc.      Algorithm, Coincident endpoints return a 2-point degenerate arc without raising., Antipodal endpoints (great circle undefined) return 2-point line., NYC → Tokyo: intermediate points should curve through the north., TestGreatCirclePoints

### Community 431 - "repo_activities.py"
Cohesion: 0.10
Nodes (18): ActivityMixin, Session, Apply an edited point list to an activity, recomputing all metrics.          S, Every LOCAL piece transitively cut out of *activity_id*.          Walks ``spli, Delete the pieces cut out of *row* and unlink their timeline items.          R, Rename every surviving member of a split family as ``"<base> (i/N)"``,, Delete a LOCAL (negative-id) activity row and unlink it from items.          O, Activity CRUD, enrichment writes, and track-geometry editing. (+10 more)

### Community 432 - "logging.py"
Cohesion: 0.07
Nodes (26): Logger, Stripe implementation of :class:`~src.billing.gateway.BillingGateway` (#121)., Drop the resolved-price cache. For tests and after a catalogue change., reset_price_cache(), configure_logging(), get_logger(), Set up logging for a module.      Args:         name: Logger name (typically, Get an existing logger by name.      Args:         name: Logger name      R (+18 more)

### Community 434 - "_build_comment_tree"
Cohesion: 0.27
Nodes (6): _build_comment_tree(), Convert flat comment rows into a fully recursive tree., _make_row(), Tests for memory comment tree builder and related helpers., A reply whose parent doesn't exist in the batch is treated as root., TestBuildCommentTree

### Community 435 - "settings_service.dart"
Cohesion: 0.04
Nodes (57): auth_notifier.dart, auth_service.dart, class, AuthNotifier, build, _busy, _confirm, createState (+49 more)

### Community 437 - "test_journal_per_user.py"
Cohesion: 0.31
Nodes (14): _create_entry(), _journal_ids_in_details(), _jpeg_bytes(), _ordered_items(), _owner_q(), _seed_mixed_timeline(), test_companion_memory_photo_lands_in_owner_dir(), test_delete_at_index_skips_hidden_journal_items() (+6 more)

### Community 438 - "haversine_km"
Cohesion: 0.15
Nodes (10): _interp_elev(), Pure geometry helpers for editing an activity's track (issue #31).  Two respon, Recompute an activity's scalar metrics from an edited point list.      ``origi, Linearly interpolate elevation at cumulative distance *d* (km).      Uses a bi, recompute_track_metrics(), TrackMetrics, Pure-unit tests for the track-edit geometry helpers (issue #31).  Covers recom, Regression test for issue #45 — save/split on a long, dense activity     (tens (+2 more)

### Community 442 - "main"
Cohesion: 0.16
Nodes (18): Row, compact_positions(), find_duplicate_groups(), main(), _nphotos(), _photo_files(), project_owner(), Connection (+10 more)

### Community 447 - "test_segments_api.py"
Cohesion: 0.30
Nodes (11): env(), _load_project(), API tests for plain Segment CRUD (create/update/delete) — split out of api/proj, _seed(), _segment_body(), test_create_segment_project_not_found(), test_create_segment_returns_id_and_is_added(), test_delete_segment_not_found() (+3 more)

### Community 459 - "download_web.dart"
Cohesion: 0.29
Nodes (5): dart:html, reloadApp, blob, triggerBrowserDownload, url

### Community 460 - "viewtrip_client"
Cohesion: 0.29
Nodes (6): Building for Production, Key Packages, Prerequisites, Running, Screens, viewtrip_client

### Community 461 - "Phase 1 crypto spike — results & locked stack (issue #26)"
Cohesion: 0.29
Nodes (6): Argon2id timing (median of 3, after warm-up), Gate verdict: GREEN to proceed to Phase 2, Locked stack (v1), Phase 1 crypto spike — results & locked stack (issue #26), Still requires the user's hardware (cannot run on this Windows box), What was proven (here, on Windows: VM + Chrome)

### Community 462 - "panel_resize.dart"
Cohesion: 0.33
Nodes (5): clampPanelWidth, kMaxPanelWidth, kMinMapWidth, kMinPanelWidth, maxW

### Community 501 - "flutter_client/lib/main.dart â€” App Entry Point"
Cohesion: 0.67
Nodes (3): app_router.dart â€” GoRouter with Auth Guard, AuthNotifier â€” Login/Logout/Session Restore, flutter_client/lib/main.dart â€” App Entry Point

## Knowledge Gaps
- **4102 isolated node(s):** `entrypoint.sh script`, `_kGoogleServerClientId`, `_router`, `main`, `createState` (+4097 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **85 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TestLowResGeoAndFullLoadDoNotCrash` connect `APIError` to `Memory`, `.get`, `ProjectItem`, `.project`, `project_io.py`, `TestLowResGeoAndFullLoadDoNotCrash`, `ConfigurationError`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **Why does `UserInfo` connect `project_io.py` to `Memory`, `A cached translation of a memory's name and description.`, `Per-user cache of the raw Strava activity list.      One row per user; the ent`, `test_photo_replace_api.py`, `people.py`, `poster_renderer.py`, `APIError`, `DBProjectMember`, `.project`, `_TsMetric`, `A cached translation of a memory's name and description.`, `_ProjectStatsScreenState`, `backup_db`, `SegmentDialog`, `get_logger`, `.token_rotated`, `test_resolve_route_async.py`, `test_admin.py`, `admin.py`, `project_stats_timeseries.dart`, `Version this image was built from (the git tag baked in at build time).      T`, `Serve the Flutter web build; fall back to index.html for SPA routing.`, `project_stats_counters.dart`, `project_shares.py`, `_BulkTagDialog`, `Scalar API reference UI.`, `A cached translation of a memory's name and description.`, `ProjectItem`, `Per-user cache of the raw Strava activity list.      One row per user; the ent`, `dart:math`, `PinSpec`, `A like on a memory — posted by an authenticated user.`, `repo_activities.py`, `Per-user cache of the raw Strava activity list.      One row per user; the ent`, `test_journal_per_user.py`, `test_quota_enforcement.py`, `AuthNotifier`, `main`, `test_segments_api.py`, `TestDataclassRoundTrips`, `.get`, `test_encounters_api.py`, `Per-user cache of the raw Strava activity list.      One row per user; the ent`, `A private, owner-only journal entry attached to a project and a specific date.`, `One ordered entry in a project — either an activity ref, segment, memory, or jou`, `One ordered entry in a project — an activity ref, segment, memory, journal, or e`, `One visitor record for a shared-project link.      Keyed on (project_id, token`, `Per-user cache of the raw Strava activity list.      One row per user; the ent`, `.delete`, `A cached translation of a memory's name and description.`, `get_current_user`, `Convert a Unix timestamp or ISO-8601 string to YYYY-MM-DD.`, `Slim down a Polarsteps step dict for the API response.`, `project_stats_counters.dart`, `ConfigurationError`, `One visitor record for a shared-project link.      Keyed on (project_id, token`, `poster_config_dialog_test.dart`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `TextStyle` connect `Strava activity row — shared across all projects that reference it.      Uses` to `activity_panel.dart`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 582 inferred relationships involving `DBProject` (e.g. with `ActivitiesAddedOut` and `ActivityFieldsUpdate`) actually correct?**
  _`DBProject` has 582 INFERRED edges - model-reasoned connections that need verification._
- **Are the 533 inferred relationships involving `UserInfo` (e.g. with `BroadcastEmailRequest` and `BroadcastEmailResponse`) actually correct?**
  _`UserInfo` has 533 INFERRED edges - model-reasoned connections that need verification._
- **Are the 411 inferred relationships involving `DBProjectItem` (e.g. with `ActivitiesAddedOut` and `ActivityFieldsUpdate`) actually correct?**
  _`DBProjectItem` has 411 INFERRED edges - model-reasoned connections that need verification._
- **Are the 275 inferred relationships involving `Activity` (e.g. with `ActivitiesAddedOut` and `ActivityFieldsUpdate`) actually correct?**
  _`Activity` has 275 INFERRED edges - model-reasoned connections that need verification._