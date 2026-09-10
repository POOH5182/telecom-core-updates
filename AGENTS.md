# Telecom Core updater project

This repository is the user's Windows telecom app and its automatic release pipeline.
The user requested that requested app changes include GitHub publication, so users do
not have to upload release files themselves. Follow the current conversation's scope
and authorization when delivering changes. Do not send messages to other people.

- Run `python tools/materialize_release.py` after downloading this repository to
  reconstruct `app/`. The complete source is transported in `release_payload/` as
  small base64 chunks of the same verified ZIP delivered to users.
  This transport is not encryption.
- Application source is in generated `app/`. Keep `version.json`, the imported workflow module,
  and the displayed version consistent. Bump the integer version for each changed app.
- Preserve `TELECOM_APP_HOME`, the launcher's instance locks and readiness notification.
- V48-installed launchers accept exactly three release files: `telecom_core_app.pyw`,
  `workflow_v<version>.py`, and `version.json`. Keep launcher_min at 1 only if compatible.
- `tools/telecom_updater.py` is the installed launcher's compatibility reference; changes
  here do not update a user's installed launcher. Never silently require a new launcher.
- Never commit customer drawings, SQLite data, project settings, credentials or backups.
- After editing, run `python tools/build_release.py --prepare` to update the payload.
  Do not re-materialize before preparing or local source edits will be replaced.
- Update `RELEASE_NOTES.md`, validate affected behavior, and commit the complete release
  source atomically. On `main`, the workflow validates and publishes the release.
- Verify the workflow's terminal result, both uploaded assets, and the latest manifest
  before claiming publication. Do not overwrite already published version contents.
- No personal access token is needed: the Actions workflow uses its scoped GITHUB_TOKEN.
- V50 cloud source lives in `cloud/client.py` and is bundled into the workflow module
  by `build_release.py --prepare`. Do not edit the appended copy independently.
- Keep the verified Google identity, server-side approval and owner checks in
  `cloud/schema.sql`. Admin emails belong only in the private database whitelist.
  Never commit OAuth secrets, privileged Supabase keys, tokens or account caches.
- Sync uses revision comparison, persistent outbox operation IDs and conflict copies.
  Always preserve unsent local edits before applying a remote drawing, including
  after restart. Bundles include working, before/after snapshots and undo history.
- `cloud-login` runs the Windows gates without publishing. Validate callback setup
  and the first real Google login before claiming end-to-end login works.
- The fixed client URL is
  `https://github.com/POOH5182/telecom-core-updates/releases/latest/download/latest.json`.
- V52 planning source lives in `planning/after_plan.py`, bundled before the cloud
  client. Regenerate both with `build_release.py --prepare`. Planning state belongs
  in `workflow_state.project.after_plan` for scenario/cloud/undo preservation.
- Renumbering is an explicit, stale-guarded, backed-up permutation. Preserve core
  annotations, RN ports, splice identities and survey/exception slot references.
  The history label `케이블 코어순서 교환` suppresses identity-annotation transport.
  Run `tools/check_after_plan.py` including its Windows UI gate before publishing.
- V53 identity-sheet blank cells preserve existing values in both the clipboard
  editor and Store.apply_core_identity_changes. Explicit deletion stays separate.
  Retain empty row offsets and never turn a missing ID into splice deletion.
- History checkpoint restores use the existing 100-group undo/redo journal with
  a revision guard, pre-restore backup and one all-or-nothing transaction. Do not
  create a new edit branch for cursor movement. Run tools/check_edit_history.py.
- V58 field investigation source lives in planning/field_survey.py, bundled before
  the after planner. GIS uses gis.sqlite3; before.sqlite3 remains the field baseline
  for after planning. Bundle/import/export all three snapshots plus working.sqlite3.
  Comparing observations never rewires. Preserve unknown rows, local splice scope,
  real-ID conflict refusal, fingerprint invalidation, atomic undo and pre-apply backup.
  Run tools/check_field_survey.py including its Windows stage/click gate.
- V59 RN endpoints require a real internal-port splice. The legacy RN terminal
  flag never ends a dangling cable. Field checks exclude terminal enclosures and
  include RN cable/internal-port observations. Run tools/check_locks_rn.py.
- Cable-wide automatic locks derive from both enclosure endpoints. A single locked
  enclosure still protects its splices, core identities and numbering. Preserve
  read-only selection/copy and migrate the named SQLite lock triggers on open.
- V60 field Excel A1 pastes merge cable columns and preserve unmentioned rows.
  Comparison stays read-only. The explicit save action adds only compatible new
  connections or missing metadata; differences stay pending for manual correction.
  Preserve manual issue flags, backups, per-row conflict rollback and grouped undo.
  Run tools/check_field_sheet.py including its Windows cell/clipboard gate.
- V60 directional route review and Ctrl+F sources are planning/connection_routes.py
  and planning/navigation.py, bundled before field_survey. Follow actual slot splices,
  separate common facilities/cables from shared cores, and never mutate on preview.
  Search uses user-facing IDs and preserves all disconnected core components.
  Run tools/check_routes_find.py including its Windows keyboard/navigation gate.
- V61 completion source lives in planning/completion.py and is bundled before
  connection_routes. Use completion_report for drawing, incomplete-list, field
  eligibility and phase connection counts. Count each core ID once; an ID-less
  signal/expected-cancellation slot is its own incomplete target. Before excludes
  exception/broken and temporary without ON; after excludes cancelled and temporary
  without ON. After expected cancellation is required. Apply exclusions first.
- Shared annotation/signal edits repaint existing cable, enclosure, summary and
  all-core rows through App.refresh, including undo/redo. Do not rebuild ID/name
  drafts or clear their edit history during repaint. Cancelled rows stay grey even
  when incomplete or also marked error. Run tools/check_completion.py including
  its Windows dialog/draft-preservation gate before publishing.
- V62 comparison source is planning/field_compare.py, bundled after field_survey.
  Freeze GIS evidence in workflow_state.field_gis_baseline; never refresh it from
  a changed survey/current drawing. GIS recopy explicitly resets the baseline.
  Comparison-only saving writes observations/acknowledgements without rewiring.
  Preserve notes, correction logs and displaced identities through re-paste,
  history, file reopen and cloud bundles. Missing real identities remain pending
  completion targets until explicitly reallocated or reviewed as a GIS error.
- Only the explicit field-resolution action may replace real identities on
  selected physical components. Preview the full changed scope, back up, guard
  revision/generation and apply the entire group atomically. Ordinary imports
  retain real-ID conflict refusal. The history label `현장 비교 선택 수정`
  suppresses annotation transport so one old ID's labels cannot leak to another.
  Never bypass enclosure locks or edit unrelated components merely by equal ID.
  Run tools/check_field_compare.py including its Windows compare/edit gate.
- V63 display sorting lives in planning/table_sort.py, bundled before completion.
  Use SortableTreeview for drawing tables. Heading clicks cycle ascending,
  descending and original insertion order; sort by moving stable item IDs only.
  Never map a sorted row back to source data with Treeview.index. TableDialog's
  row_indices map preserves this relationship for completion-route selection.
  Keep inline editors anchored to their physical row IDs; commit on heading clicks
  without reloading drafts. Background repaint must not commit an open editor.
  Pin spreadsheet title row 1. Multirow identity paste and Excel-grid paste restore
  default order and retain physical row offsets, blanks and original source data.
  Clipboard/export headings use heading_text to exclude sort arrows from cable IDs.
  Run tools/check_table_sort.py including its Windows click/edit/paste/trace gate.
- V64 completeness tables use completion_check_groups to show each exact nonempty
  core ID once, preserving every diagnostic/location in _check_items. Anonymous
  slot/facility issues stay separate. Highest severity drives group filtering;
  full reasons, source-location navigation and grouped CSV must remain available.
  Do not suppress raw Store diagnostics or change completion/handoff policy.
- V65 reviewed field-editor automatic defaults use field_auto_identity: match
  real core IDs only, including actual outward routes and supplied survey IDs.
  Different or blank names never block identity matching. An explicit survey
  name is the proposed name; without one, preserve each affected slot's name.
  Show name differences and the naming policy in the reviewed editor. Explicit
  manual name assignment clears preserve_names and is previewed on the route.
  Known conflicting state/signal requires review; blank values must not erase
  known values. Manual reviewed correction remains available. Run completion,
  field comparison and Windows smoke gates before publishing.
- V66 after step 1 lives in planning/after_routes.py, bundled after after_plan.
  List mandatory after cores once per ID using completion policy, retaining
  missing before identities and anonymous signal/expected-cancellation slots.
  Match core IDs only. Keep actual connected components intact; search active
  cables for a simple facility path covering every component. Minimize added
  cable segment count (no measured length exists). Never call a limited or
  partial search result a minimum; ambiguous ends require explicit selection.
- Cable route decisions, NOK evidence and manual drafts are stored in
  workflow_state.project.after_plan.route_step. This step must never assign
  core numbers, rewire splices, mutate existing identities or change baseline
  drawings. Keep stale guards, grouped history and cloud bundle preservation.
  Recheck confirmed routes after graph/topology changes, not name/layout-only
  changes. OK confirms the full ordered route; partial drafts never count done.
  Step 2 allocation is deliberately unspecified. Run tools/check_after_routes.py
  including its Windows list/map/NOK/draft/OK/reopen/CSV gate before publishing.

- V67 field-first topology import lives in planning/field_overlay.py, bundled
  after field_compare. The primary field survey action and Ctrl+S use its
  preview/backup/atomic commit. Partial input preserves all unmentioned pairs;
  only conflicting splices at the selected facility may change. Differing real
  IDs never block this explicit topology overlay and are never rewritten by it.
  Register blank newly observed slots as temporary cores, preserving existing
  names, state, signal and real IDs. Do not propagate identities to remote slots.
- Local OK/NOT OK belongs in each field_surveys record, keyed by connection with
  evidence/topology/core-ID fingerprints. Never store it as a shared annotation.
  GIS match is automatic OK only with matching current allocation and core IDs;
  names are ignored. Missing/different evidence is NOT OK until manual review.
  Manual OK requires locally coherent actual splices and IDs and becomes stale
  after relevant changes. Preserve GIS snapshots and overlay before/after logs.
- Overlay-enabled field completion uses local checks plus existing required-core
  exclusions. Node endpoint columns and right-click decisions must remain local;
  counts have an independent field_checks view toggle for canvas and SVG. Keep
  terminal-enclosure exclusion and RN internal-port rules. Legacy additive APIs
  remain for compatibility, but the user-facing field-save action uses overlay.
  Run check_field_overlay.py including Windows UI, and the existing field,
  completion, sorting and release gates before publication.

- V68 open_detail_dialog allows only one enclosure (hamche) NodeDialog at a
  time. Same-item opens reuse the live editor; another enclosure closes the
  previous editor through close_for_switch before constructing the new one.
  Honor dirty-header and field-sheet save/cancel choices, retain remembered
  popup position, and cancel old route-highlight timers. Cable/RN/subscriber
  editors retain their existing behavior. Run the Windows smoke gate's actual
  double-click, duplicate-open, save/cancel and popup-position checks.

- V69 supersedes V67's forced field topology rule. The primary field save and
  Ctrl+S persist observations/comparisons without removing or replacing existing
  GIS/current splices or identities. Only a pair with no local splice and blank
  IDs in both the frozen GIS reference and current drawing may be added as one
  temporary core. Partial re-pastes preserve unmentioned evidence and edits.
- Show unapplied observed connections as 현장 선번 미반영 / NOT OK, with a filter,
  count and GIS/field/current evidence. Related retained connections cannot stay
  OK while a conflicting observation is pending. Reviewed connection/identity
  correction is separate; a matching actual connection can then be marked OK.
  Keep the GIS difference and saved before/after evidence after manual completion.
  New imports never revert earlier manual corrections or rewrite old saved data.
- Retain backup, atomic history, stale/lock checks, and displaced-slot automatic
  splice exclusions during explicit correction. Run check_field_overlay.py and
  check_field_compare.py, including Windows save/pending-filter/correction/OK
  gates, before publishing.

- V70 automatically marks an observed new temporary pair OK when the frozen GIS
  has no touching splice or assigned ID and the current pair is uniquely spliced
  with one matching temporary ID. The local mode is 현장 신규 자동 OK. This read-only
  rule also covers previously saved V67–V69 temporary pairs; retain their IDs,
  evidence, history and original GIS differences without a destructive migration.
- Auto OK never overrides explicit manual NOT OK, conflicting supplied IDs,
  missing/duplicate actual splices, known GIS allocations or a pending conflicting
  observation. Keep all V69 mismatch deferral and local-only status behavior.
  Show the automatic result in the field save preview, endpoint columns and counts.
  Run field overlay/comparison, completion and Windows release gates.

- V71 renders dashboard mandatory-core counts as separate labels. Only the
  incomplete label is red (#c62828) when total minus done is positive; zero uses
  the existing metric color. Keep the stage completion policy and other colors.
  The title is work_progress_text and the percentage is work_progress_rate.

- V72 new field drawings store meta.field_identity_policy=cable_slots_v72.
  planning/field_slots.py owns this workflow, bundled after after_routes. The
  mode is per drawing, only active in before, and never inferred from version.
  Existing V71 field drawings retain their earlier behavior. New GIS derivatives
  preserve original slots/metadata/locks and frozen GIS evidence but initialize
  without splices, survey entries or the previous drawing's undo journal.
- In this mode field input writes local topology despite different real IDs.
  Never propagate identities, names or signal through ordinary connections or
  slot edits; disable automatic ID/number splicing. Blank observed slots become
  neutral temporary cores. Preserve unmentioned field observations/connections.
- Audit actual components including neutral temporary IDs. Known signals must
  agree; unknown is neutral. Real IDs, names or ON signal create mandatory targets,
  without legacy annotation exemptions. Required paths need distinct valid ends,
  coherent IDs/signals, and explicit fingerprinted final ID/name confirmation.
  Pending unconnected GIS placements must not prevent reviewing the actual path,
  but continue to prevent 100% until allocated or explicitly cleaned up.
- Slot moves swap ID/name only by default, optionally state/signal; never change
  splices. Finalization assigns the confirmed ID/name within the reviewed actual
  component only. Cleanup may clear matching-ID unconnected waiting identities,
  preserving state/signal. Never clear a different ID, a linked or observed slot,
  an independently complete path, or ON signal. Show every affected slot before
  commit; protect locks, revision/generation, backups, atomic history and GIS.
- _windowsFieldSlotsV72 preserves independent per-slot state/signal, the policy
  and frozen reference through legacy JSON whose global ID maps cannot represent
  those differences. Scenario switching preserves slot moves and confirmations.
- Run check_field_slots.py with its real Windows copy/Excel/move/confirm/JSON/
  phase gate. legacy_field_fixture.py prepares already-saved V71 snapshots for
  the older Windows compatibility gates; it never changes production behavior.
