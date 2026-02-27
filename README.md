# manifixer

`manifixer` is a Dockerized STL repair and 3D format conversion service intended for Unraid.

It fixes common mesh problems that break slicing/printing, including:
- non-manifold edges
- holes/open boundaries
- flipped or inconsistent normals
- disconnected tiny shells

Internally it uses [`admesh`](https://github.com/admesh/admesh) with aggressive repair flags.

## Features
- Web UI for one-off STL upload/repair (`/` on port `8080`)
- Web UI + API conversion tool for common 3D formats (`POST /convert`)
- Automatic watch mode for batch repair from an input folder
- Repaired files are versioned to avoid overwrite collisions (`*.fixed.stl`, `*.fixed.1.stl`, ...)
- Watch mode uses a queue + worker pool and waits for files to stabilize before processing
- Quality report with before/after issue counts, triangle count, shell count, and confidence
- Session/temp-file retention cleanup runs automatically
- Health endpoint: `GET /health`

## Supported converter formats

Input and output:
- `3mf`
- `stl`
- `obj`
- `ply`
- `off`
- `glb`

The repair pipeline remains STL-only (`admesh`).

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
- `WATCH_WORKERS` (default `1`)
- `POLL_SECONDS` (default `30`)
- `STABILITY_CHECK_SECONDS` (default `3`)
- `STABILITY_MAX_WAIT_SECONDS` (default `120`)
- `SESSION_TTL_SECONDS` (default `7200`)
- `CLEANUP_SECONDS` (default `300`)
- `PORT` (default `8080`)

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

> `admesh` must be installed on the host for local (non-Docker) runs.
