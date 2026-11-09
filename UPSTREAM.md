# Upstream engine

`src/gputaskman/` is a verbatim copy of the measurement engine from
https://github.com/shanselman/gputaskman (MIT, Copyright (c) 2026 Scott Hanselman).

- Commit: `82c71dbe5f6ed6e44c8bdfc2967390f0eeed7774`
- Date: 2026-11-08
- Licence: `licenses/gputaskman-LICENSE.txt` (must ship with every build)

Rules:
- Do not edit files under `src/gputaskman/`. Desktop code lives in `src/gtm_desktop/`
  and only uses the engine's public pieces: `collector.Collector`, `collector.ordered_adapters`,
  `report.to_dict`, `report.to_text`.
- `src/gputaskman/app.py` (the upstream Textual TUI) is kept for easy diffs but is
  excluded from the build; Textual and Rich are not dependencies.
- To update: `.\scripts\sync_upstream.ps1` (clones upstream, replaces `src/gputaskman/`,
  rewrites the commit above), then run the tests.
