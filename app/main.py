import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file
from werkzeug.utils import secure_filename

APP_TITLE = "Manifixer"
INPUT_DIR = Path(os.getenv("INPUT_DIR", "/data/input"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/output"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
WATCH_MODE = os.getenv("WATCH_MODE", "1") == "1"
PORT = int(os.getenv("PORT", "8080"))

ALLOWED_EXTENSIONS = {"stl"}
PROCESSED_SUFFIX = ".fixed.stl"

HTML = """
<!doctype html>
<html>
  <head>
    <title>{{title}}</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 760px; margin: 2rem auto; }
      .card { border: 1px solid #ddd; border-radius: 8px; padding: 1.5rem; }
      button { background: #1f6feb; color: white; border: none; border-radius: 6px; padding: 0.6rem 1rem; cursor: pointer; }
      code { background: #f2f2f2; padding: 0.1rem 0.3rem; border-radius: 4px; }
      .muted { color: #666; }
    </style>
  </head>
  <body>
    <h1>{{title}}</h1>
    <p class="muted">Repair non-manifold edges, hole issues, flipped normals, and disconnected shells for STL files.</p>
    <div class="card">
      <h2>Upload and repair</h2>
      <form action="/repair" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".stl" required />
        <button type="submit">Repair STL</button>
      </form>
      <p class="muted">For automatic repair, map your folders and enable watch mode. Input: <code>{{input_dir}}</code> Output: <code>{{output_dir}}</code></p>
    </div>
  </body>
</html>
"""

app = Flask(__name__)


def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def run_repair(input_file: Path, output_file: Path) -> tuple[bool, str]:
    """Run admesh in an aggressive repair configuration for 3D-printable meshes."""
    cmd = [
        "admesh",
        "--write-binary-stl",
        str(output_file),
        "--exact",
        "--normal-directions",
        "--remove-unconnected",
        "--fill-holes",
        "--nearby",
        "--tolerance=0.01",
        "--iterations=2",
        str(input_file),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    logs = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0 and output_file.exists(), logs.strip()


def process_one_file(source: Path) -> tuple[bool, str, Path]:
    safe_stem = secure_filename(source.stem) or "model"
    destination = OUTPUT_DIR / f"{safe_stem}{PROCESSED_SUFFIX}"
    success, logs = run_repair(source, destination)
    return success, logs, destination


def watcher_loop() -> None:
    seen: dict[Path, float] = {}
    while True:
        try:
            for stl in INPUT_DIR.glob("*.stl"):
                mtime = stl.stat().st_mtime
                if seen.get(stl) == mtime:
                    continue
                seen[stl] = mtime
                ok, logs, output = process_one_file(stl)
                status = "OK" if ok else "FAIL"
                print(f"[{status}] {stl.name} -> {output.name}\n{logs}\n", flush=True)
        except Exception as exc:
            print(f"[WATCHER ERROR] {exc}", flush=True)
        time.sleep(POLL_SECONDS)


@app.get("/")
def index():
    return render_template_string(
        HTML,
        title=APP_TITLE,
        input_dir=str(INPUT_DIR),
        output_dir=str(OUTPUT_DIR),
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "watch_mode": WATCH_MODE, "poll_seconds": POLL_SECONDS})


@app.post("/repair")
def repair_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    if not upload.filename or not allowed_file(upload.filename):
        return jsonify({"error": "Only .stl files are supported"}), 400

    ensure_dirs()
    safe_name = secure_filename(upload.filename)

    with tempfile.TemporaryDirectory(prefix="manifixer-") as td:
        temp_in = Path(td) / safe_name
        upload.save(temp_in)

        ok, logs, output = process_one_file(temp_in)
        if not ok:
            return jsonify({"error": "Repair failed", "logs": logs}), 500

    return send_file(output, as_attachment=True, download_name=output.name)


if __name__ == "__main__":
    ensure_dirs()
    if WATCH_MODE:
        thread = threading.Thread(target=watcher_loop, daemon=True)
        thread.start()
    app.run(host="0.0.0.0", port=PORT)
