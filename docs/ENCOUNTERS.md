# Encounters — people met along the trip (#40)

Log the people you meet on a trip and where/when you met them.

## Concepts
- **Person** — a per-project directory entry. All fields are optional (`name`,
  `email`, `phone`, `polarsteps`, `notes`, `avatar`); an unnamed person renders as
  **"Unknown"**.
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

## Data model (per-project, Alembic `f40e0c0de001`)
- `person` — `id`, `project_id`, `name?`, `email?`, `phone?`, `polarsteps?`,
  `notes?`, `avatar_photo?`, `created_at`.
- `encounter` — `id`, `project_id`, `person_id`, `date`, `time?`, `description?`,
  `geo_mode`, `lat?`, `lon?`.
- `projectitem.encounter_id` — FK for encounter timeline items.

Deleting a person cascades to their encounters (+ timeline items). `.viewtrip`
export/import round-trips people + encounters (excluded from public shares).

## API
- People: `POST /api/people`, `GET/PUT/DELETE /api/people/{id}`, avatar
  `POST/DELETE /api/people/{id}/avatar`, `GET .../avatar[/thumb]`.
- Encounters: `POST /api/encounters`, `PUT/DELETE /api/encounters/{id}`.
- `PUT /api/projects/{name}/items/sort` orders encounters by `date`/`time`.

## Client
- **People** section (manage AppBar → groups icon): searchable list + per-person
  sheet (details, avatar, places/dates met).
- Add an encounter from the day add-item sheet, the "+" speed-dial, or a person;
  the dialog picks an existing person or creates one inline.
- Encounters appear inline on their day and as owner-only pins on the manage map.
