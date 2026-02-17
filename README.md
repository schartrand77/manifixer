# manifixer

`manifixer` is a Dockerized STL repair service intended for Unraid.

It fixes common mesh problems that break slicing/printing, including:
- non-manifold edges
- holes/open boundaries
- flipped or inconsistent normals
- disconnected tiny shells

Internally it uses [`admesh`](https://github.com/admesh/admesh) with aggressive repair flags.

## Features
- Web UI for one-off STL upload/repair (`/` on port `8080`)
- Automatic watch mode for batch repair from an input folder
- Repaired files are written to an output folder as `*.fixed.stl`
- Health endpoint: `GET /health`
- Runtime metrics endpoint: `GET /metrics`
- Session management endpoints: `GET /sessions`, `DELETE /sessions/<id>`

## Quick start (Docker)

```bash
docker build -t manifixer:latest .

docker run --rm -p 8080:8080 \
  -e WATCH_MODE=1 \
  -e POLL_SECONDS=30 \
  -v /path/to/to_fix:/data/input \
  -v /path/to/fixed:/data/output \
  manifixer:latest
```

Then open `http://localhost:8080`.

## Unraid setup

1. Build and push this image to a registry (e.g. GHCR) and update the repository URL in `unraid/manifixer.xml`.
2. Add the XML template in Unraid's **Community Applications** templates.
3. Set:
   - `Input Folder` to your watched STL folder
   - `Output Folder` to where repaired files should be saved
   - `Watch Mode=1` for automatic batch processing

You can also disable watch mode and use only the web uploader.

## Environment variables

- `INPUT_DIR` (default `/data/input`)
- `OUTPUT_DIR` (default `/data/output`)
- `WATCH_MODE` (`1` or `0`, default `1`)
- `POLL_SECONDS` (default `30`)
- `PORT` (default `8080`)
- `MAX_SESSIONS` (default `40`)
- `SESSION_TTL_SECONDS` (default `21600` / 6 hours)
- `MAX_SESSION_LOG_CHARS` (default `60000`)
- `ADMESH_TIMEOUT_SECONDS` (default `180`)

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

> `admesh` must be installed on the host for local (non-Docker) runs.
