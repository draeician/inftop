# inftop

Top-like terminal monitor that merges AMD GPU sysfs stats with live inference
activity from **Strata** (and optionally Ollama).

Stdlib only (Python ≥ 3.11). No third-party dependencies.

## Install

```bash
pipx install git+https://github.com/draeician/inftop
```

Or run from a clone without installing:

```bash
python3 -m inftop
```

## Screenshot (text)

```
gpu-box  up 3d 04:12:01  model=example-model  strata=ok  max_ctx=131072  ollama 0.40.4
load 0.42 0.38 0.35  cpu 8%  ram 12.1 GiB/64.0 GiB  swap 0.0 GiB/8.0 GiB

>>GPU card0  busy 42% idle  VRAM [########------------] 24.0 GiB/96.0 GiB  GTT 40 MiB/80 GiB  temp 58C  power 28.4W  sclk 1800MHz  (last 2m)
  busy  ▁▂▄▆█  cur 42.0%  min 10.0%  max 100.0%
  power ▁▁▂▃▅  cur 28.4W  min 12.0W  max 84.0W
  tok/s ▁▁▂▄▇  cur 38.2/s  min 0.0/s  max 45.1/s

  Active requests
    answering  gen 412  38.2 tok/s  12s  clients=10.0.0.10

  Clients
  10.0.0.10 (workstation.lan)  open=1  reqs=3  last=15:33:01 UTC

  Recent requests (sort=time; best-effort client corr.)
  time          prompt    gen    prefill     decode   dur tools        reason
  15:32:16 UTC   12041     89   8200.0/s     40.1/s     4 -            stop
```

## Usage

```bash
python3 -m inftop
python3 -m inftop --once --json
python3 -m inftop --frames 3 --dump
python3 -m inftop --remote gpu-box
python3 -m inftop -r gpu-box
python3 -m inftop --strata-url http://10.0.0.5:8080
python3 -m inftop --init-config
python3 -m inftop stats --since 24h
```

| Flag | Meaning |
|------|---------|
| `-d SECS` | Refresh interval (default 1, or config `interval`) |
| `--once` | Single snapshot then exit |
| `--json` | With `--once`, print JSON |
| `-r` / `--remote HOST` | Probe over persistent SSH ControlMaster |
| `--strata-url URL` | Strata HTTP base (default `http://127.0.0.1:8080`) |
| `--tz ZONE` | Display timezone (default: system local) |
| `--frames N --dump` | Render N frames as text (no TTY) |
| `--init-config` | Write commented `config.toml` (use `--force` to overwrite) |
| `stats [--since 24h]` | Print history aggregates from SQLite |

## Config

File: `$XDG_CONFIG_HOME/inftop/config.toml` (default `~/.config/inftop/config.toml`).

See [`config.example.toml`](config.example.toml). Create one with `inftop --init-config`.

**Precedence:** CLI flag > environment > config file > built-in defaults.

| Env | Maps to |
|-----|---------|
| `INFTOP_STRATA_URL` | `strata_url` |
| `INFTOP_REMOTE` | `remote_host` |
| `INFTOP_TZ` | `tz` |
| `STRATA_API_KEY` | API key (beats `api_key_file`) |

Other keys: `interval`, `history_window`, `ollama_url`, `container_name` (default `strata`),
`api_key_file`, and `[alerts]` (`temp_c`, `vram_pct`, `stall_s`).

## Keys (curses UI)

`q` quit · `p` pause · `Tab` cycle panels · `l` raw log · `c` clients · `h` help · `s` sort recent

## Data sources

1. **GPU sysfs** — `/sys/class/drm/card*/device/` (busy%, VRAM/GTT, temp, power, sclk); optional `rocm-smi` every ≥5 s.
2. **Strata container logs** — `podman logs` on `container_name` (default `strata`); request state machine from log lines.
3. **Strata HTTP** — `/health` (unauthenticated); optional authenticated `/metrics`, `/slots`, `/props`, `/status`, `/v1/models` when a key is available.
4. **Clients** — host-side `ss` on the Strata listen port (from `strata_url`); reverse DNS best-effort.
5. **Ollama** — `/api/ps` and `/api/version` (section hidden if unreachable).
6. **Host** — load, RAM, CPU%, swap, uptime from `/proc`.

## GPU notes (gfx1151)

On **gfx1151** (Strix Halo iGPU), sysfs `gpu_busy_percent` is often stuck at 100% even when idle.
inftop still shows it, but treats **power draw** (and the activity indicator: idle when within 5 W of the
rolling minimum over the sparkline window, unless there is an active request) as the honest signal.

## Security

- Optional Strata API key from `STRATA_API_KEY` or `api_key_file` (must be mode `600` or stricter; refused if group/other bits are set). The key is never printed or logged.
- Read-only probes: inftop does not restart containers or modify remote services.
- `--remote` uses SSH `BatchMode` + ControlMaster; credentials come from your SSH agent/config.

## License

MIT — see [LICENSE](LICENSE).
