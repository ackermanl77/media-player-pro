# CLAUDE.md

Guidance for Claude Code in this repository. User docs: [README.md](README.md) (Spanish); architecture,
release and known issues: [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md); per-feature guides:
[docs/workflows/](docs/workflows/README.md).

## What this is

A PySide6 music and video player on libVLC (`python-vlc`). `run.py`/`run.pyw` start
`player.main_window.MainWindow`, whose code is split into mixins (`window_menus.py`,
`window_dialogs.py`, `window_inputs.py`, `window_effects.py`, `window_sources.py`). Needs a 64-bit
VLC 3.0 installed (or a `BUNDLE_VLC=1` build). The UI is in Spanish.

## Commands

```powershell
python run.py
python -m pytest -q                                   # needs requirements-dev.txt
pip install -r requirements-build.txt -c constraints.txt; pyinstaller --noconfirm ReproductorMultimediaPro.spec
iscc /DAppVersion=<version> installer\ReproductorMultimediaPro.iss
```

CI: `.github/workflows/ci.yml` (tests), `build-exe.yml`, and `release.yml` on a `v*` tag.

## Rules

- **`player/backend.py::VLCPlayer` is the only code that imports `vlc`.** The window reads
  `backend.PlaybackState`. Instance-level options (the visualizer) mean recreating the instance;
  `_create_instance()` reapplies volume, mute, speed and equalizer.
- **Every command is a `QAction` in `player/actions.py::ActionRegistry`** (menus, context menu,
  buttons, fullscreen controller and the shortcuts dialog all read it); add new commands there.
- `player/formats.py` stays free of VLC and Qt so it tests without either.
- The version lives only in `player/__init__.py` (`__version__`).
- Tests never touch real settings: `tests/conftest.py` redirects `Path.home()` and `%LOCALAPPDATA%`.
  `test_app_smoke.py` uses the `offscreen` Qt platform and skips without VLC.
- `test_visualizer_enabled_produces_a_video_output_for_audio` is a known intermittent failure on
  this machine (docs/PROJECT_STATUS.md, Known Issues); one failure of it alone is not a regression.

## Releases and licensing

- Third-party licenses live in `licenses/` (`THIRD_PARTY_NOTICES.txt`, kept by hand, with VLC's
  source link); the installer ships them. Update it when a dependency or the bundled VLC changes.
- `player/update_check.py` checks a JSON release feed once per launch. `UPDATE_FEED_URL` stays empty until
  releases are published somewhere users can reach (the GitHub repository is private).
- CI runs `pip-audit`; Dependabot opens weekly update PRs. A vulnerability with no fixed release
  is ignored only with a comment saying why it doesn't apply.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost), then `graphify export wiki` -- the git hooks rebuild graph.json after each commit/checkout but never the wiki.
- graphify-out/ is gitignored: every clone builds its own graph (`/graphify`), and the git hooks (`graphify hook install`) keep it current. Do not commit it or suggest skipping the rebuild or its hooks.
- Community names live in graphify-out/.graphify_labels.json (curated); a community a rebuild creates or reshapes gets a hub-name fallback in `.graphify_labels.pending.json` (e.g. a bare file or test name). When the report shows such names, rename them there (2-5 plain words) and run `graphify cluster-only .`.
