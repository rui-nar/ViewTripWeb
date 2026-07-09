# Encounters — people met along the trip (#40)

Log the people you meet on a trip and where/when you met them.

## Concepts
- **Person** — a per-project directory entry. All fields are optional (`name`,
  `email`, `phone`, `notes`, `avatar`, plus **social links**, **nationalities**,
  and a **residence** city); an unnamed person renders as **"Unknown"**. Social
  links are a list of `{network, handle}` (Instagram / Facebook / Polarsteps /
  Strava / …); the legacy `polarsteps` field is kept as a mirror of the
  Polarsteps entry so the shared-trip view still resolves it.
- **Encounter** — links one person to a **day**, with a place (map pin, defaulting
  to the day's location, editable) and an optional note. Rendered as an ordered
  timeline item, like memories and journal entries.

## Privacy (owner-only)
People and encounters are **never** exposed in shared views (full or no-memories
tokens) — they hold third-party PII. The `GET /api/projects/{name}` owner payload
includes a `people` array + encounter items; the share endpoints strip both, and
the shared geo endpoints never emit encounter pins.

Keyword search runs **client-side** over already-loaded data (person fields +
encounter notes), so it stays compatible with the planned zero-knowledge
encryption work (#26): those text fields are the encrypt-on-write set when E2EE
lands.

## Data model (per-project, Alembic `f40e0c0de001`, extended by `f7e8d9c0b1a2`)
- `person` — `id`, `project_id`, `name?`, `email?`, `phone?`, `polarsteps?`,
  `notes?`, `avatar_photo?`, `created_at`, plus (`f7e8d9c0b1a2`) `socials_json?`,
  `nationalities_json?` (ISO 3166-1 alpha-2 codes), `residence?`.
- `encounter` — `id`, `project_id`, `person_id`, `date`, `time?`, `description?`,
  `geo_mode`, `lat?`, `lon?`.
- `projectitem.encounter_id` — FK for encounter timeline items.

Deleting a person cascades to their encounters (+ timeline items). `.viewtrip`
export/import round-trips people + encounters (excluded from public shares).

## API
- People: `POST /api/people`, `GET/PUT/DELETE /api/people/{id}`, avatar
  `POST/DELETE /api/people/{id}/avatar`, `GET .../avatar[/thumb]`.
- Encounters: `POST /api/encounters`, `PUT/DELETE /api/encounters/{id}`.
- Residence city autocomplete: `GET /api/geo/places?q=` — proxies OSM Nominatim
  server-side (owner-auth; the client debounces) and returns distinct
  "City, Country" labels; only the chosen display string is stored.
- `PUT /api/projects/{name}/items/sort` orders encounters by `date`/`time`.

## Client
- **People** section (manage AppBar → groups icon): searchable list + per-person
  sheet (details, avatar, places/dates met).
- Add an encounter from the day add-item sheet, the "+" speed-dial, or a person;
  the dialog picks an existing person or creates one inline.
- Encounters appear inline on their day and as owner-only pins on the manage map.

## Groups (#50)
Bundle several people into a named **group** (e.g. a family or a travel crew), so
an encounter can reference the group rather than each person individually. Like
people, groups are per-project and owner-only, and never appear in shared views.

- **PersonGroup** — an optional `name` plus its own `nationalities` and social
  links (same shape as a person). A person belongs to **at most one** group via
  `person.group_id` (many-to-many is out of scope for v1).
- Data model (Alembic `50c0de5f6a7b`): `person_group` — `id`, `project_id`,
  `name?`, `nationalities_json?`, `socials_json?`, `created_at`; plus the nullable
  `person.group_id` FK. Deleting a group **ungroups** its members (the people
  remain); `.viewtrip` export/import round-trips groups and membership.
- API: `POST /api/groups`, `GET/PUT/DELETE /api/groups/{id}`, and
  `PUT /api/groups/{id}/members` to set the member list.
- Client: a **People | Groups** directory; the group form reuses the person
  modal's nationality + social-link widgets.
