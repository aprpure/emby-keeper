# AGENTS.md

## Project Snapshot

Embykeeper is a Python application for Telegram-based check-in automation, Emby/Subsonic account keepalive, registrar workflows, and a small web console. Prefer linking to existing user documentation instead of copying it into code comments or agent notes.

## Primary Code Areas

- `cli.py` and `web.py` are thin wrappers. Put behavior changes in package modules, not in the root wrappers.
- `embykeeper/cli.py` is the main orchestration layer for config loading, scheduling, and feature startup.
- `embykeeper/telegram/` is the largest business area. `checkin_main.py`, `monitor_main.py`, `message_main.py`, and `registrar_main.py` are the coordinator entry points for Telegram features.
- `embykeeper/emby/` and `embykeeper/subsonic/` contain keepalive and playback logic for media services.
- `embykeeper/config.py`, `embykeeper/schema.py`, `embykeeper/schedule.py`, and `embykeeper/runinfo.py` are shared core modules. Cross-cutting changes usually belong here.
- `embykeeperweb/app.py` is the current web console implementation. It uses Flask plus Flask-SocketIO and launches the CLI in a PTY-backed subprocess.
- `tests/` contains pytest coverage. `utils/` contains local dummy bots and debugging helpers; do not treat it as production runtime code.

## Working Commands

- Preferred Python range for development is 3.8-3.10. Packaging metadata is broader, but `tox.ini` and the Makefile are centered on that range.
- On Windows, prefer direct Python and npm commands. The Makefile assumes POSIX paths, `venv/bin/python`, bash syntax, and `systemd`.
- Run CLI: `python -m embykeeper -i`
- Run CLI with debug logs: `python -m embykeeper -i -dd`
- Run web console: `python -m embykeeperweb --public`
- Run tests: `python -m pytest tests -v --tb=long`
- Format Python: `python -m black .`
- Run Python checks: `python -m pre_commit run -a`
- Run docs locally: `npm run docs:dev`
- Build docs: `npm run docs:build`

## Project Conventions

- Keep the root entry scripts thin. If a change affects runtime behavior, update the package entry points instead.
- When changing config fields or defaults, update all of: `embykeeper/schema.py`, `embykeeper/config.py`, `config.example.toml`, and the relevant documentation page.
- For Telegram feature work, prefer extending existing manager patterns and add or update targeted pytest coverage instead of relying on live Telegram interactions.
- Use the dummy bots and test helpers under `utils/` when you need local reproduction for Telegram flows.
- Keep edits scoped. This repo has user-local state and generated artifacts that should not be normalized or committed.

## Known Pitfalls

- `package.json` contains `cli:dev`, but it points to `make run/dev`, which does not exist. Use `make run/debug` or the direct Python command instead.
- `docs/guide/参与开发.md` still contains some historical `telechecker` references. Verify behavior against the current `embykeeper/telegram/` source before following those names literally.
- The dependency set includes FastAPI and Uvicorn, but the visible web control surface in this repo is `embykeeperweb/app.py`. Do not assume FastAPI is the primary web entry point.
- Treat `.tmp_jellyfin_desktop_qt/` as an auxiliary subtree unless a task explicitly targets it.
- Local config and session files are intentionally ignored, including `*.toml` except the shipped examples/project metadata, plus `*.session` and related runtime artifacts.

## Useful References

- Project overview and installation: [README.md](README.md)
- Documentation index: [docs/index.md](docs/index.md)
- Configuration reference: [docs/guide/配置文件.md](docs/guide/配置文件.md)
- CLI options: [docs/guide/命令行参数.md](docs/guide/命令行参数.md)
- Development notes: [docs/guide/参与开发.md](docs/guide/参与开发.md)
- Debugging helpers: [docs/guide/调试工具.md](docs/guide/调试工具.md)
- Deployment guides: [docs/guide/安装指南.md](docs/guide/安装指南.md)