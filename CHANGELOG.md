# Changelog

## 0.2.0 — 2026-11-21

- Public-ready packaging: MIT LICENSE, cleaned README, `config.example.toml`, neutral examples.
- Config file `$XDG_CONFIG_HOME/inftop/config.toml` (TOML via `tomllib`): `strata_url`, `remote_host`, `tz`, `interval`, `history_window`, `[alerts]` (`temp_c`, `vram_pct`, `stall_s`), `api_key_file`, `ollama_url`, `container_name`.
- Precedence: CLI > env (`INFTOP_STRATA_URL`, `INFTOP_REMOTE`, `INFTOP_TZ`, `STRATA_API_KEY`) > config > defaults.
- Generic defaults: `strata_url=http://127.0.0.1:8080`, `tz` = system local, `container_name=strata`.
- `inftop --init-config` writes a commented example (never overwrites without `--force`).
- API key file must be chmod 600 or stricter; looser modes are refused; key never printed.
- Scrubbed personal hostnames/IPs from docs, tests, and samples.

## 0.1.2 — 2026-11-21

- Sparklines show cur/min/max with units (%, W, /s); GPU panel header includes history span (e.g. last 2m); each series scaled to its own min/max.
- Ctrl+C / SIGTERM exit cleanly (no traceback): restore terminal, close SSH ControlMaster, exit 0.
- `--remote` CPU% from two `/proc/stat` samples over the transport (no more `cpu ?`).
- Recent-request table uses fixed-width columns so `-` prefill aligns with numeric rates.
- Prompt tokens show `?` when the "reading the prompt" line was never seen (not `0`).
- GPU activity indicator next to busy% (rule B: busy if active requests; else idle if power within 5 W of rolling min; else busy). Note: `gpu_busy_percent` is unreliable on gfx1151.
- `-r` short alias for `--remote`.

## 0.1.1 — 2026-11-21

- Display times via `zoneinfo`; add `--tz` override (hosts may run UTC).
- Fix prefill tok/s: use largest reading `"N s so far"`, fall back to timestamps, never divide by ~0; show `-` when unknown.
- Make Strata HTTP base configurable (`--strata-url`).
- Active-request detection: incomplete requests with progress < 30s stay active; older ones appear in recent as `reason=stale` instead of being dropped.

## 0.1.0 — 2026-11-21

- Initial release: curses UI merging AMD GPU sysfs stats with Strata logs/HTTP and Ollama.
- `--once --json`, `--remote HOST`, `--frames N --dump`, `stats [--since]`.
- SQLite history of finished requests and per-minute GPU samples.
- Alerts for high temp/VRAM, stalled requests, disconnect finishes.
