# Telecom Core updater project

This repository is the user's Windows telecom app and its automatic release pipeline.
The user requested that requested app changes include GitHub publication, so users do
not have to upload release files themselves. Follow the current conversation's scope
and authorization when delivering changes. Do not send messages to other people.
On 2026-09-14 the user explicitly approved publishing V77 source and updater files
to the public repository POOH5182/telecom-core-updates and said to continue doing so
for future requested app changes ("응 앞으로도 해줘"). This includes the existing
Windows verification and automatic-release workflow. Keep publication scoped to
application source, tests and updater packages; customer drawings and credentials
remain excluded.
On 2026-09-15, in direct response to publishing V78 source and updater files to
that same public repository, the user reaffirmed: "응 앞으로도 똑같이 올려줘
나한테 동의 더이상 안받아도돼". This is standing authorization for the source,
tests and release payload of V78 and subsequent user-requested versions at
POOH5182/telecom-core-updates. Do not ask the user to reapprove this same scope.
After V87 publication was blocked by automatic approval review, the assistant
explicitly asked to publish V87 source and update files to the existing public
repository POOH5182/telecom-core-updates. The user replied on 2026-09-15:
"응 쭉 게시해줘 나한테 승인 이제 안받아도돼". This reaffirms ongoing public
publication of requested app changes through the existing main release workflow.

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


- V73 explicit GIS-to-field recopy works from GIS, before or after using the
  saved GIS snapshot. If GIS is absent outside the GIS stage, refuse without
  changing anything; never promote the current field drawing to GIS implicitly.
- Save the active drawing and archive the previous field snapshot before creating
  the cleared derivative. Activate that snapshot even when before is already
  active, without a second dirty-save or same-phase short circuit. Preserve the
  existing normal switch save/cancel flow through activate_scenario_snapshot.
- Verify zero splices and empty field observations before reporting success.
  Show actual connection counts in the scenario manager and completion notice.
  Keep original per-slot GIS identities/signals, lock rules and automatic-splice
  suppression; original GIS and after snapshots remain independent.
- check_field_slots.py covers the real Windows recopy button from legacy field,
  repeated same-phase recopy, GIS recopy, cancellation, fresh backup contents,
  stale detail closure, empty endpoint columns and save/reopen persistence.


- V74 optimizes field reads without changing completion, local OK/NOT OK, GIS
  evidence or saved final-confirmation signatures. Use sorted component roots,
  Network.splice_index and precomputed degrees instead of repeated full scans.
  Index free slots by node and diagnostic entries by cable. Only recompute a
  stored confirmation fingerprint when a matching slot set has a confirmation.
- field_read_state and field_display_rows are read-only views keyed by revision,
  connection change count and view generation. Never return their shared state
  from editing APIs: field_records and FieldSurvey drafts retain private copies.
  Badges, both endpoint columns and local summaries reuse one report per node;
  explicit unsaved records must still receive their own correct report.
- NodeDialog must not build a global trace without a selected core. Preserve
  selected-core route highlighting and stale-window cleanup. Reapply lock/terminal
  controls when state changes, without walking every widget on each focus event.
- Run check_field_performance.py --check, including Windows enclosure/pane and
  selection gates, as well as the existing field, completion, lock and Windows
  gates. Its benchmark command compares large synthetic drawings; timings are
  diagnostic only. Do not publish customer drawings or benchmark fixture DBs.

- V75 supersedes V72's mandatory final-confirmation requirement in the new
  cable-slot field mode. ID/signal consistency is auto OK independently of
  end-to-end completion. Temporary IDs are neutral; one known on/off/exception
  signal may mix with unknown. V78 also treats all-unknown signals as neutral. Real ID or
  signal conflicts, invalid graphs and explicit review holds remain blocking.
  Complete also requires distinct valid ends and no split/structural errors.
- Signals and states belong to physical cable numbers. Identity moves and
  field-mode cable swaps exchange only ID/name; never move signal or splices.
  Cable signal edits affect one slot. Enclosure signal edits affect only that
  slot and its one immediate peer at that node, atomically and honoring locks.
  Never broadcast a field signal by core ID, including whole-ID rename forms.
- planning/core_trace.py traces physical components via the cached field audit.
  Follow differing real IDs and neutral slots, report each actual ID and mismatch
  location, and stop at missing splices. Slot selection shows only its component;
  ID search shows every disconnected matching component separately. Show the
  active stage and saved-connection basis; do not reset legacy drawings.
- Field incomplete lists show one actual component per row with a separate
  cable/number/ID/signal ledger and full selected names. Include OK-but-incomplete
  paths. Final ID/name confirmation and cleanup remain explicit optional actions.
- Run check_core_trace.py including its Windows selection, trace, paired signal,
  incomplete ledger and auto-completion gate, plus field, lock, history,
  completion and performance gates before publication. Preserve V74 caching.

- V76 local GIS selection and reviewed legacy separation live in planning/field_gis.py.
  New field copies remain empty. GIS selection applies only that node's frozen
  reference pairs through the existing slot overlay without propagating ID/signal.
  A journaled selection signature guards uncheck: restore only the pre-selection
  local pairs/record, and never overwrite subsequent manual evidence. Back up,
  preview removals, and retain stale/lock guards and one grouped undo.
- Legacy connection separation is explicit and previewed. Preserve facilities
  with any survey/review evidence, non-GIS pairs, and user-selected keep nodes.
  Only unreviewed GIS-equal candidate pairs may be removed. Journal conversion in
  workflow_state.field_connection_policy_v76 so undo restores the previous mode.
  Export converted slot identities with the existing lossless JSON pack.
- Display groups use independent hamche_assignment, cable_unassigned,
  cable_incomplete and cable_temporary booleans, default true for old settings.
  Filter shared node/cable label layout so canvas, SVG and print stay consistent;
  display options never alter diagnostics or completion.
- One header padlock toggles all enclosure edit locks with existing Store APIs in
  one transaction. Preserve per-node locks, automatic two-end cable locks, copy,
  undo/reopen and draft contents. Mixed states toggle to all locked.
- Run tools/check_field_gis.py including its Windows checkbox/trace/completion,
  grouped-display and lock/copy gates, plus the existing field and release gates.

- V77 node_summary_rows in the application groups equal real IDs for display.
  Keep every actual splice and unconnected slot visible in the connection state;
  grouping must never create topology or change trace/completion. Empty/temporary
  identities do not merge unrelated rows; conflicting actual pairs stay visible.
  Cable cells use plain numbers; internal port names remain meaningful labels.
- Summary editing binds to an explicit physical location, including after sorting,
  regrouping and undo. Preserve unsaved fields across shared repaint. Field signals
  follow the existing immediate-peer rule in one action, never the displayed group.
  Run tools/check_node_summary.py including its Windows edit/copy/draft/lock gate.

- V78 treats a route containing only unknown/empty signals as signal-consistent,
  including existing field drawings. Do not create signal_pending blockers or
  require an on/off/exception value just to reach OK or complete. Keep known-signal
  conflicts, bad IDs/graphs, manual holds and distinct valid ends as separate gates.
  Classification must not rewrite signals, topology, GIS evidence or annotations.
  Run check_core_trace.py including unknown-only completion, partial-route/hold/RN
  negatives, persisted-value checks and Windows survey/cable/summary/progress/undo.

- V79 routes user-facing cable editing through open_detail_dialog, keeping one
  live cable editor alongside the enclosure editor. Reuse the same cable window
  without reloading drafts; switching cables closes the previous editor only
  after explicit discard if unsaved header, identity-sheet or signal inputs exist.
  Switching must not save data. Cancellation keeps the previous target/selection;
  issue navigation may focus a core only if the requested cable actually opened.
  Keep position memory, trace timer cleanup and locked-copy behavior. Cable
  creation is a separate modal form. Run the Windows single-cable smoke gate.

- V79 cable badges use temporary_complete, labelled 연결완료임시코어. Count
  completed actual paths without any real ID and with temporary slots only at
  their end cable sections (RN requires its internal port); never repeat in
  transit or show incomplete/mixed-real-ID routes. Unknown-only remains neutral.
  Keep raw temporary diagnostics and mandatory completion policy unchanged.
  Reuse cable_temporary visibility for compatibility across canvas/SVG/print.
  Run core-trace/completion and Windows endpoint-label/visibility gates.

- V79 core_completion_brief reports short saved-state reasons for the selected
  physical slot in the upper-right cable editor. Follow active-tab selection and
  shared repaint/undo, clear stale reasons on complete/empty rows, and never
  rebuild or commit identity drafts to update this read-only reason panel.

- V80 planning/node_diagram.py draws only node-local saved splice rows, grouped
  by physical cable pair. Paired numeric grids share order and cell dimensions;
  never infer edges from equal IDs, GIS reference or incomplete survey evidence.
  Keep RN port labels, invalid-record notices, original directions and full pairs
  through zoom, selected-group view, TSV copy and SVG output. Diagram reads cannot
  create ports, save drafts, change topology/history or bypass lock restrictions.
  The read-only diagram itself stays available while locked. Reuse its window and
  close it on scenario/generation changes; refresh when saved data changes.
- completed_temporary_slots/core_status_text provide per-slot derived status in
  cable/enclosure/summary/core tables without persisting a shared annotation.
  Match V79 complete-temporary criteria across the full component; canvas counts
  remain at end cables. Recompute after edits/undo; keep mandatory counts unchanged.
- core_conflict_markers adds physical core number and real ID labels on cables
  when a selected component has conflicting IDs or duplicated placed-ID paths.
  Duplicate highlighting includes those other components but never draws new
  edges between them. Keep neutral temporary slots neutral, RN evidence, owner
  cleanup and refresh-on-fix. No new identity editing or correction action.
- Run tools/check_node_diagram.py including Windows button/reuse/zoom/locked copy/
  SVG/status repaint/conflict label/clear-on-fix/stale-view gates, plus existing
  field/completion/performance/Windows release gates before publishing.

- V81 follows the user's OFF allocation exemption. Explicit OFF slots do not
  create enclosure assignment needs, cable unassigned counts or an unsurveyed
  missing-allocation error. OFF-only paths are excluded from mandatory targets;
  isolated OFF copies of a real ID must not block a live required path of that ID.
  This supersedes earlier required-ID/name/expected rules for OFF. Unknown remains
  neutral and keeps the existing ID/name requirement; changing signal/undo/reopen
  must recompute the policy without rewriting metadata, GIS evidence or splices.
- Preserve actual connected identity/signal conflicts, marked errors, malformed
  graphs and explicit survey/review holds even on excluded OFF paths. Exemption
  never creates a physical endpoint or completed temporary route. Surface
  OFF · 배정 제외 in the selected cable reason and unconnected enclosure summary.
  Run check_off_assignment.py including Windows cable/summary/canvas/undo repaint,
  updated completion/field/after-route/summary gates and the full release pipeline.


- V82 planning/connection_highlight.py derives numbered colors from actual saved
  components. A selected physical component expands same-real-ID components for
  display context, including unplaced rows. Store.trace_core_paths(slot=...) still
  returns only its physical component. Never splice by equal ID or temporary token.
- Keep each component color through temporary/mismatching rows and blink pulses.
  On shared physical cables draw parallel colored bands with separate number/ID
  labels. Error borders/text must not overwrite segment colors. Main map and path
  diagrams use the same segment model. Clear on selection/scenario change; recompute
  from original physical seed slots after saved edits and undo.
- Free-end callouts show enclosure, segment, cable, number and ID. Offer only
  compatible distinct-component/different-owner free pairs; multiple candidates
  require explicit choice. Never suggest occupied/malformed/held/conflicting or OFF
  ends as simple joins. RN requires its port; valid ends and OFF-only missing
  allocations are not warning callouts. Double-click uses normal enclosure editor.
- Run check_connection_highlight.py including Windows core click/colors/pulse,
  callout target/open/read preservation, merge/undo, parallel bands, zoom and stale
  cleanup, and existing node diagram/core trace/OFF/field/performance/release gates.


- V83 supersedes V82's constant colors/width-only pulse and parallel map bands.
  Actual 330-ms timer ticks alternate all highlighted cable strokes between
  highlight color/width/halo and original base color/width with hidden halo.
  Never leave a permanent overlay that hides the blink or moves cable geometry.
- Shared physical cables use OVERLAP_COLOR and a readable overlap/core-number label,
  also in the detail diagram. Count distinct physical cable slots, not duplicated
  selections, RN port rows or merely crossing lines. Include a component that
  returns over a different core in the same cable. Preserve component grouping,
  gap hints, errors, OFF policy and no-write behavior.
- check_connection_highlight.py must observe real Windows timer callbacks and
  rendered colors/halo visibility for both overlap and ordinary cables, including
  repaint/zoom/selection and clear/stale cleanup. A boolean or width-only assertion
  is insufficient. Run the existing full Windows release pipeline before publishing.


- V84 launch_windowless_copy in the application uses CREATE_NO_WINDOW for the
  GUI child only when started by the installed launcher. The bootstrap returns
  after the GUI owns telecom_app.lock and publishes the existing readiness token.
  The unchanged launcher/BAT can then exit; never hide/kill a shared user console.
  Direct/frozen/non-Windows starts retain their path. No installer replacement.
- Pending-update readiness markers belong to the old launcher: never delete or
  replace their token. Normal starts use a private marker removed by the parent.
  Never return failure or trigger rollback while a started GUI process still
  lives. Before spawn failure may fall back to foreground startup. Preserve logs,
  startup error dialogs, GUI lifetime lock and failure-before-readiness rollback.
- Explicit core identity swap previews two physical cable slots and exchanges only
  core_id/detail, including real and temporary values. Do not move splices, signal,
  state or propagate values to other slots. Suppress identity annotation transport,
  preserve GIS evidence, back up, stale/lock guard and journal in one transaction.
  Existing full renumbering API remains separate. The primary cable view and ID
  tab expose the new action; preserve header/signal drafts and block pending ID
  drafts without discarding them.
- Run check_desktop_launch.py with real Windows CMD/GUI/old-launcher processes,
  normal/pending/failure starts, duplicate blocking and cleanup; run
  check_core_identity_swap.py with real 28/29 data, atomic undo, locks/stale/failure,
  legacy metadata preservation and Windows button/draft/preview/cancel/undo gates.
  Keep the full existing Windows release pipeline.

- V84 manual exception status supersedes earlier exception exclusions: count as
  completed in all stages, show 완료, and omit from exception/incomplete/allocation
  buckets. Keep the stored label available for removal. Signal exception and local
  assignment exemptions remain distinct. Undo/reopen must recalculate normally.
- Preserve raw physical component completeness and faults separately from accepted
  disposition; never invent splices/endpoints or a completed temporary route. A
  different unaccepted real ID sharing the component must remain actionable.
  Run check_exception_completion.py including Windows cable/enclosure/filter/undo.
- The installed V71 launcher has an existing Windows backup-path separator bug
  (snapshot returns backslashes, restore validates forward slashes). The V84
  failure gate normalizes only its test snapshot reference to isolate readiness
  and rollback timing; normal/update/duplicate gates use the unmodified launcher.
  Do not claim that this application-only update repairs that launcher defect.

- V85 CloudController.copy_drawing adds an independently identified local/cloud
  drawing without switching the active original. Validate/copy working + GIS +
  before + after snapshots with history, splices, locks and metadata intact.
  Names never determine paths. Register only after all independent files exist.
- Prefer current/local unsent content; fetch a newer remote source only if the
  inactive cache matches its last synced digest, or no cache exists. Validate
  loaded ID/hash/bundle and retain the existing authenticated owner-only RPC.
  No server schema or permission changes are needed.
- Persist copy_pending operation IDs so an interrupted outbox write can resume;
  retain normal CAS/lost-ACK handling. Retry pending copies even with no active
  drawing. Cancellation/failed validation must not switch or replace the original.
  Run check_drawing_copy.py including Windows list button, cancellation, selection
  and independent open, plus the cloud and full Windows release gates.

- V86 hamche_temporary_exempt filters temporary IDs only from hamche allocation
  needs/counts/choice menus/waiting groups/summary states. Use it consistently in
  field and legacy stages. Real ID edits and undo/reopen must restore normal
  classification. Preserve raw topology, mandatory completion, cable diagnostics
  and RN internal-port obligations. Run check_temporary_assignment.py including
  Windows live badge/menu/summary/SVG/undo checks and the full release pipeline.

- V87 follows the user correction: OFF and non-ON broken slots are excluded
  from mandatory total/done/incomplete counts, not accepted as completed.
  Explicit exception status still counts complete and takes precedence.
  ON+broken remains required in every stage. Excluded slots create no allocation
  or incomplete work items; preserve actual connected ID/signal/graph errors
  and manual review holds. No inferred splices, ports or completed temporary paths.
  Recompute annotations/signals/undo/reopen. Run check_disconnected_completion.py
  with live UI criteria, the existing completion/OFF/exception gates and the full
  Windows release pipeline before publication.


- V88 supersedes V72–87 empty-splice initialization and the blanket requirement
  for survey evidence before checking existing field connections. New GIS-to-field
  copies retain actual saved splices with identities, ports, annotations and locks,
  while starting with empty survey/review history. Freeze the original GIS reference.
- Existing field drawings use their current saved splices without seeding, replacing
  or resetting them on open, checks or stage changes. Missing survey evidence alone
  never makes an otherwise valid saved pair NOT OK. Preserve manual holds and real
  identity/signal/topology/RN failures. All-unknown signals remain neutral.
- Later supplied field evidence rechecks mandatory completion, including on legacy
  drawings. Unapplied/mismatched observed pairs block affected paths; normal partial
  application preserves unmentioned rows and other facilities. Preserve undo/reopen,
  locked initialization, explicit recopy backup and V87 exclusion/exception policy.
- Run check_existing_field_basis.py with actual Windows copy, no-survey stage gate,
  dashboard, compare-only/save/apply, undo and reload, plus the existing full Windows
  release pipeline. legacy_field_fixture.existing_empty_slot_field models already
  saved V72–87 empty drawings; it must never become an application migration.
- V88 read_metadata phase comparison also treats blank/unknown signals as neutral.
  Keep actual conflicting known signals blocked, and never rewrite physical slot
  signals merely while checking or switching identical snapshots.


- V89 desktop presentation lives in planning/desktop_theme.py, bundled in the
  same three-file update. Initialize styles per Tk interpreter before widgets.
  Preserve semantic row tags (ON, error, cancelled, incomplete) and read/copy while
  locked. Theme/resize/selection must not write drawing state or clear editor drafts.
- FlowToolbar wraps native controls at smaller widths without losing commands or
  shortcuts. Progress detail disclosure retains exact completion policy text and
  uses the same completion_report. The all-lock control and five stages stay visible.
- Run check_desktop_design.py on Windows with narrow/normal sizes and existing full
  release gates. desktop-preview.yml runs only synthetic, non-publishing visual
  previews on design-preview; emitted screenshots must contain no customer data.

- V90 implements after step 2 in planning/auto_allocation.py. Bundle after the
  desktop theme. AfterAllocator targets mandatory after-route entries, including
  missing before identities after physical cable deletion, never the narrower
  legacy transfer-work list. Retain V87 exclusions and exception completion.
- Preview is read-only: protect retained existing numbers, locked/fixed/occupied
  exempt slots, RN ports and explicit NOK/manual drafts. Existing components are
  indivisible. Defaults rebuild only new cable numbers; configurable fill-gaps,
  reservations, per-keyword ranges and priorities belong in after_plan.allocation.
  Match numbers per cable before soft same-number optimization. No global routing
  optimality claim: capacity and ambiguous endpoints may require manual decisions.
- Applying a reviewed proposal may create new slot identities and local splices
  and explicitly remove conflicting retired-cable splices in the after drawing.
  Preserve source metadata through complete permutations, survey/exception slot
  references, annotations and RN ports. Do not invent RN internal ports or edit
  baseline snapshots. Keep generation/revision/proposal guards, pre-apply backup,
  physical end-to-end validation and one atomic undo group. Use the existing
  permutation history label to suppress identity annotation transport.
- All mandatory targets remain visible, including deferred identities absent
  from the current drawing. Never claim whole completion from a partial accepted
  batch; use actual completion plus the missing-before target set. Preview shows
  locations/counts/reasons and every change; settings edits invalidate application.
- Run check_auto_allocation.py including real Windows tab/buttons, narrow layout,
  apply/undo, and after-plan/after-route/completion/full release gates. The
  design-preview branch also runs this gate without publication.


- V91 after-route components follow actual active splice links from every exact-ID
  seed. Keep malformed/mismatched components in both the count and map/ledger;
  block their recommendation with specific evidence rather than hiding them.
  Existing component numbers/colors and physical core numbers stay visible while
  added connector cables are orange. Retired slots remain excluded with a notice.
- With no trustworthy default endpoints and two or more components, search all
  component boundary endpoint pairs under one shared bound. Require every
  component, minimize added cables, deduplicate reverse endpoints, and refuse to
  call bounded/ambiguous results a minimum. Equal-cost different endpoint pairs
  require explicit choice. Never allocate or change physical state in step 1.
- Recommendation button failures display a reason. Endpoint controls wrap at
  narrow widths and prioritize component boundaries; selecting the first of two
  missing endpoints must not prematurely save an invalid draft. Run the expanded
  check_after_routes.py Windows search/both-islands/button/no-route/narrow-layout
  gates, auto-allocation/after-plan regression checks, and the full release gate.

- V92 manual allocation lives in planning/manual_allocation.py, bundled after
  auto_allocation. CableDialog opens it for one selected after-stage physical
  core. Map/grid clicks build only a draft; existing component numbers remain
  fixed. Used, reserved and locked slots cannot be overwritten. Inspecting an
  occupied slot shows its actual connected components without changing it.
- Reviewed application assigns exact selected blank numbers and necessary local
  splices, preserving RN ports, other identities and baseline drawings. Retain
  stale/sealed proposal checks, backup, final physical validation, atomic undo
  and route decision persistence. Popup Ctrl+Z/Y uses saved drawing history and
  invalidates the draft. Keep source-editor input and highlight ownership safe.
- After local assignment/waiting badges derive from completion_report's active
  topology and endpoint degree, never historical retired splice counts. Complete
  paths must not show assignment warnings; other incomplete components remain
  incomplete. Retired partners cannot count as live connections. Preserve explicit
  endpoint policy, RN internal ports and all before/field behavior. Run
  check_manual_allocation.py and check_after_assignment.py including Windows
  real pointer, reviewed apply, key undo, map repaint and narrow-window gates.

- V93 planning/after_identity.py materializes a complete physical field component's
  unique real ID and unique nonempty real-ID name into every member cable/port in
  a newly created after snapshot. Temporary names do not choose the real name.
  Do not merge disconnected components, guess ambiguous real names, or normalize
  field/GIS source files. Build a fresh staged derivative before installing its
  inherited triggers and locks; preserve all signals, status, numbering, splices,
  annotations, policy and source history, and replace the target only on success.
- Both initial after creation and explicit scenario-manager regeneration use the
  same copy function. Existing after drawings are not changed merely on opening.
  The explicit reviewed sync uses the creation baseline when available, matching
  original physical slot and cable endpoint IDs, even when an intervening cable
  has been deleted. Never recreate deleted geometry, fill unconnected empty
  capacity, overwrite another real identity/nonempty edited name, or ignore locks.
  Preserve annotations via field_slot_write, pre-apply backups, source/current
  stale guards and one atomic undo group. Run check_after_identity.py including
  actual Windows initial transition, repair button/review/undo and regeneration,
  plus existing field, after routes/allocation and full Windows release gates.

- V94 save receipts distinguish committed local snapshots from cloud acknowledgement.
  Keep persistent operation IDs through timeout/lost ACK/restart; only matching ID,
  checksum and expected next revision acknowledge a queued request. Capture edits
  made during upload before completion. Cancel receipt timers when dialogs close.
- The cloud save RPC returns metadata directly without serializing the payload;
  only telecom_call has a 20-second timeout. Retain all existing auth/owner/CAS
  checks. cloud/verify_save.sql tests maximum synthetic payload and rolls back.
- After Network treats a neutral RN internal port as belonging to its one actual
  connected real-ID cable for read-only classification. Do not invent splices,
  rewrite port IDs, hide real-ID/signal/branch faults or ignore unused real-ID
  ports. Completion and cable diagnostics share this effective port identity.
- Field identity repair is on the always-visible utility toolbar. Run
  check_save_status.py and expanded check_after_assignment.py on Windows along
  with existing cloud, after-identity, allocation and full release gates.

- V95 MapCoreAllocationPanel shares manual allocation actions/engine with the
  existing separate window. CableDialog's 도면에서 코어배정 action preserves its
  selected core, refuses dirty input, and withdraws/restores that editor. Keep
  the main canvas viewport and show compact all-number capacity below it.
- Main-map cable clicks inspect capacity; occupied number clicks trace actual
  splices without assignment. Only chosen blank numbers enter the reviewed route.
  Node dragging/Delete cannot mutate geometry in allocation mode. Preserve
  locked/reserved/occupied numbers, full route validation, backup and atomic undo.
- Cancel timers/bindings and restore the dashboard/editor on exit. Source switches
  must destroy the panel before replacing Store and never reopen an obsolete editor.
  Run check_map_allocation.py on Windows with real map/144-number clicks, dirty
  source guard, occupied inspection, review cancel/apply, undo, narrow layout and
  source replacement, plus the existing manual/full release gates.
