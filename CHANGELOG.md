# Changelog

## 2026-05-29
### Added

- Added country-specific output selection for `nXX_...` Whisp result columns.
  - Added a new country selection dialog.
  - Available countries can be selected.
  - Countries without available result columns are shown disabled/greyed out.
  - Added **None** and **All** shortcuts.

- Added output unit selection.
  - Users can now choose between **Hectares** and **Percentage** before submitting an analysis.

- Added support for the newer Whisp API request schema.
  - Requests now include `analysisOptions`.
  - Supports `externalIdColumn`, `nationalCodes`, `unitType`, and `async`.

- Added async Whisp analysis support.
  - Larger jobs can be submitted asynchronously.
  - The plugin polls the Whisp status endpoint until completion.
  - Progress updates are shown during processing.

- Added real progress reporting in the processing dialog.
  - Starts with an indeterminate progress bar.
  - Switches to percentage progress when Whisp returns real progress.
  - Adds an expandable **Show details** log for API/status messages.

- Added safer cancel handling.
  - Initialization can now be cancelled.
  - Analysis cancellation now signals the worker cleanly.
  - Temporary output cleanup runs after cancellation.

- Added improved first-launch handling.
  - API key prompt is now handled when the user launches the plugin.
  - Terms/GEE acknowledgement is stored after acceptance and not repeatedly shown.

### Changed

- Changed the plugin launch flow to use a dedicated `launch_plugin()` workflow.
  - API key check.
  - Whisp column initialization.
  - Terms acknowledgement.
  - Main analysis dialog.

- Changed request feature IDs from `plotId` to `external_id`, derived from the internal `link_id`.

- Changed output-column handling.
  - Country-specific `nXX_...` columns are no longer mixed into the main checkbox list.
  - Internal `whisp_processing_metadata` is hidden from user selection.

- Changed processing workflow so the progress dialog appears before heavier local geometry preparation begins.

- Changed output writing to use a temporary sibling GeoJSON first.
  - The final output is replaced only after analysis and result writing succeed.

- Changed result writing to use batched `changeAttributeValues()` for better performance and stability.

### Fixed

- Prevents users from choosing an output file with the same filename as the input file.

- Prevents writing to an output file that is already open in QGIS.

- Improves cleanup of temporary output files and sidecar files.
  - Handles `.aux.xml`, `.qmd`, and `.qml` sidecars.
  - Avoids deleting the user-selected final output during cancellation or failure cleanup.

- Fixes temporary-layer naming leakage.
  - Final GeoJSON collection names are rewritten so files do not keep `.whisp_tmp` naming.

- Improves handling of re-analysis.
  - Existing Whisp result fields are detected.
  - User is warned that old Whisp columns will be replaced.
  - A clean working copy is created before re-analysis.

- Improves API error classification.
  - Connectivity, authentication, API, and unexpected errors are handled more explicitly during initialization.

- Improves handling of nested API response values.
  - Dict/list values are serialized to JSON text before being written to layer attributes.

- Improves UI responsiveness.
  - Long loops now periodically process Qt events during reprojection, geometry preparation, request building, and result writing.

### Removed

- Removed the older simulated progress approach based on estimated feature count/area.
  - Replaced with indeterminate progress plus real Whisp API progress when available.

- Removed the old startup behavior that could raise an exception if no API key was provided during plugin construction.
  - Replaced with a user-facing launch-time prompt.

- Replaced the older direct synchronous-only request flow with a sync/async-compatible worker.

## 2025-06-20

- First release. Version updated to 1.0.
- Flagged as non-experimental.
