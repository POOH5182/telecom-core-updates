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
