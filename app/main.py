import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file
from werkzeug.utils import secure_filename

APP_TITLE = "Manifixer"
INPUT_DIR = Path(os.getenv("INPUT_DIR", "/data/input"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/output"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
WATCH_MODE = os.getenv("WATCH_MODE", "1") == "1"
PORT = int(os.getenv("PORT", "8080"))
SESSION_ROOT = Path(tempfile.gettempdir()) / "manifixer-sessions"

ALLOWED_EXTENSIONS = {"stl"}
PROCESSED_SUFFIX = ".fixed.stl"

HTML = """
<!doctype html>
<html>
  <head>
    <title>{{title}}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root {
        --bg: #f5f7fa;
        --card: #ffffff;
        --text: #15202b;
        --muted: #5b6673;
        --accent: #0f766e;
        --accent-2: #115e59;
        --danger: #b42318;
        --ok: #067647;
        --border: #d0d7de;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
        color: var(--text);
        background: linear-gradient(180deg, #eef3f8 0%, #f9fbfc 100%);
      }
      .wrap {
        max-width: 840px;
        margin: 2rem auto;
        padding: 0 1rem;
      }
      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 10px 30px rgba(17, 24, 39, 0.04);
      }
      h1, h2 { margin: 0 0 0.75rem 0; }
      p { margin: 0.25rem 0 0.75rem 0; }
      .muted { color: var(--muted); }
      .row {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        align-items: center;
      }
      input[type="file"] {
        padding: 0.5rem;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: #fff;
      }
      button {
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        cursor: pointer;
        font-weight: 600;
      }
      button:hover { background: var(--accent-2); }
      button:disabled {
        background: #9ca3af;
        cursor: not-allowed;
      }
      .download-btn {
        display: inline-block;
        text-decoration: none;
        background: var(--ok);
        color: #fff;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-weight: 600;
      }
      .download-btn:hover { filter: brightness(0.95); }
      .issues {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
        gap: 0.6rem;
      }
      .issue {
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 0.7rem;
        background: #f8fafc;
      }
      .issue-name { font-size: 0.9rem; color: var(--muted); }
      .issue-count { font-size: 1.2rem; font-weight: 700; }
      .issue-count.ok { color: var(--ok); }
      .issue-count.bad { color: var(--danger); }
      .status-pill {
        display: inline-block;
        font-size: 0.82rem;
        border-radius: 999px;
        padding: 0.2rem 0.6rem;
        border: 1px solid var(--border);
        color: var(--muted);
      }
      .progress {
        width: 100%;
        height: 10px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #0f766e, #14b8a6);
        transition: width 0.35s ease;
      }
      pre {
        white-space: pre-wrap;
        max-height: 220px;
        overflow: auto;
        margin: 0;
        background: #0b1220;
        color: #dbe6f6;
        border-radius: 8px;
        padding: 0.75rem;
        font-size: 0.82rem;
      }
    </style>
  </head>
  <body>
    <main class="wrap">
      <div class="card">
        <h1>{{title}}</h1>
        <p class="muted">Upload STL, analyze mesh errors, repair with visible progress, then download repaired STL.</p>
        <p class="muted">Watch mode still runs in background using <code>{{input_dir}}</code> to <code>{{output_dir}}</code>.</p>
      </div>

      <div class="card">
        <h2>1) Upload and Analyze</h2>
        <div class="row">
          <input id="fileInput" type="file" accept=".stl" />
          <button id="analyzeBtn" type="button">Analyze Errors</button>
        </div>
        <p id="analyzeMsg" class="muted"></p>
      </div>

      <div class="card" id="issuesCard" style="display:none;">
        <h2>2) Errors Detected</h2>
        <div id="issuesGrid" class="issues"></div>
        <div class="row" style="margin-top:0.9rem;">
          <button id="repairBtn" type="button" disabled>Repair</button>
          <span id="statusPill" class="status-pill">idle</span>
        </div>
        <div style="margin-top:0.8rem;" class="progress">
          <div id="progressFill" class="progress-fill"></div>
        </div>
      </div>

      <div class="card" id="resultCard" style="display:none;">
        <h2>3) Download</h2>
        <p id="resultMsg" class="muted"></p>
        <a id="downloadBtn" class="download-btn" href="#" style="display:none;">Download Repaired STL</a>
      </div>

      <div class="card" id="logsCard" style="display:none;">
        <h2>Repair Logs</h2>
        <pre id="logs"></pre>
      </div>
    </main>

    <script>
      const ISSUE_LABELS = {
        non_manifold_edges: "Non-manifold edges",
        holes_open_boundaries: "Holes / open boundaries",
        flipped_normals: "Flipped / inconsistent normals",
        disconnected_shells: "Disconnected shells"
      };

      const state = {
        sessionId: null,
        initialTotal: 0,
        polling: null
      };

      const fileInput = document.getElementById("fileInput");
      const analyzeBtn = document.getElementById("analyzeBtn");
      const repairBtn = document.getElementById("repairBtn");
      const analyzeMsg = document.getElementById("analyzeMsg");
      const issuesCard = document.getElementById("issuesCard");
      const issuesGrid = document.getElementById("issuesGrid");
      const statusPill = document.getElementById("statusPill");
      const progressFill = document.getElementById("progressFill");
      const resultCard = document.getElementById("resultCard");
      const resultMsg = document.getElementById("resultMsg");
      const downloadBtn = document.getElementById("downloadBtn");
      const logsCard = document.getElementById("logsCard");
      const logs = document.getElementById("logs");

      function renderIssues(issues) {
        issuesGrid.innerHTML = "";
        Object.entries(ISSUE_LABELS).forEach(([key, label]) => {
          const count = Number((issues && Object.prototype.hasOwnProperty.call(issues, key)) ? issues[key] : 0);
          const div = document.createElement("div");
          div.className = "issue";
          div.innerHTML = `
            <div class="issue-name">${label}</div>
            <div class="issue-count ${count > 0 ? "bad" : "ok"}">${count}</div>
          `;
          issuesGrid.appendChild(div);
        });
      }

      function computeProgress(remaining) {
        if (state.initialTotal <= 0) {
          return remaining === 0 ? 100 : 0;
        }
        const done = Math.max(0, state.initialTotal - remaining);
        return Math.max(0, Math.min(100, Math.round((done / state.initialTotal) * 100)));
      }

      async function pollStatus() {
        if (!state.sessionId) return;
        const res = await fetch(`/status/${state.sessionId}`);
        if (!res.ok) return;

        const data = await res.json();
        renderIssues(data.issues_current || {});
        statusPill.textContent = `${data.status}${data.stage ? " | " + data.stage : ""}`;

        const remaining = Number(data.remaining_errors || 0);
        progressFill.style.width = `${computeProgress(remaining)}%`;

        logsCard.style.display = "";
        logs.textContent = (data.logs || []).join("\\n\\n");

        if (data.status === "completed") {
          clearInterval(state.polling);
          state.polling = null;
          progressFill.style.width = "100%";
          resultCard.style.display = "";
          resultMsg.textContent = "Repair completed. All detected errors were resolved.";
          downloadBtn.href = `/download/${state.sessionId}`;
          downloadBtn.style.display = "inline-block";
          repairBtn.disabled = true;
        }

        if (data.status === "failed") {
          clearInterval(state.polling);
          state.polling = null;
          resultCard.style.display = "";
          resultMsg.textContent = "Repair failed. See logs for details.";
          downloadBtn.style.display = "none";
          repairBtn.disabled = false;
        }
      }

      analyzeBtn.addEventListener("click", async () => {
        const file = (fileInput.files && fileInput.files[0]) ? fileInput.files[0] : null;
        if (!file) {
          analyzeMsg.textContent = "Choose an STL file first.";
          return;
        }

        analyzeBtn.disabled = true;
        repairBtn.disabled = true;
        analyzeMsg.textContent = "Analyzing mesh...";
        resultCard.style.display = "none";
        downloadBtn.style.display = "none";

        const form = new FormData();
        form.append("file", file);

        try {
          const res = await fetch("/analyze", { method: "POST", body: form });
          const data = await res.json();

          if (!res.ok) {
            analyzeMsg.textContent = data.error || "Analyze failed.";
            analyzeBtn.disabled = false;
            return;
          }

          state.sessionId = data.session_id;
          state.initialTotal = Number(data.total_errors || 0);
          renderIssues(data.issues || {});
          issuesCard.style.display = "";
          logsCard.style.display = "none";
          statusPill.textContent = "analyzed";
          progressFill.style.width = "0%";
          analyzeMsg.textContent = `Detected ${data.total_errors} issue(s). Click Repair.`;
          repairBtn.disabled = false;
        } catch (err) {
          console.error("Analyze failed", err);
          analyzeMsg.textContent = `Analyze failed: ${err}`;
        } finally {
          analyzeBtn.disabled = false;
        }
      });

      repairBtn.addEventListener("click", async () => {
        if (!state.sessionId) return;

        repairBtn.disabled = true;
        statusPill.textContent = "starting repair";
        logsCard.style.display = "";
        logs.textContent = "";

        const res = await fetch(`/repair/${state.sessionId}`, { method: "POST" });
        const data = await res.json();

        if (!res.ok) {
          statusPill.textContent = "failed";
          resultCard.style.display = "";
          resultMsg.textContent = data.error || "Could not start repair.";
          repairBtn.disabled = false;
          return;
        }

        if (state.polling) clearInterval(state.polling);
        state.polling = setInterval(pollStatus, 1000);
        pollStatus();
      });
    </script>
  </body>
</html>
"""

app = Flask(__name__)
sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)


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


def run_admesh_inspect(mesh_file: Path) -> str:
    cmd = ["admesh", "--exact", str(mesh_file)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def parse_issue_counts(admesh_text: str) -> dict[str, int]:
    text = admesh_text or ""
    lower = text.lower()

    def pick_int(patterns: list[str]) -> int:
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                try:
                    return max(0, int(m.group(1)))
                except (TypeError, ValueError):
                    continue
        return -1

    issues = {
        "non_manifold_edges": pick_int([
            r"non[- ]manifold edges?\s*:\s*(\d+)",
            r"backwards edges?\s*:\s*(\d+)",
        ]),
        "holes_open_boundaries": pick_int([
            r"holes?\s*:\s*(\d+)",
            r"open edges?\s*:\s*(\d+)",
        ]),
        "flipped_normals": pick_int([
            r"flipped normals?\s*:\s*(\d+)",
            r"inconsistent normals?\s*:\s*(\d+)",
            r"incorrect normals?\s*:\s*(\d+)",
            r"normal vectors? fixed\s*:\s*(\d+)",
        ]),
        "disconnected_shells": pick_int([
            r"disconnected shells?\s*:\s*(\d+)",
            r"unconnected facets?\s*:\s*(\d+)",
        ]),
    }

    parts_match = re.search(r"number of parts\s*:\s*(\d+)", text, flags=re.IGNORECASE)
    if parts_match:
        try:
            parts = int(parts_match.group(1))
            if parts > 1:
                issues["disconnected_shells"] = max(issues["disconnected_shells"], parts - 1)
            elif issues["disconnected_shells"] < 0:
                issues["disconnected_shells"] = 0
        except ValueError:
            pass

    keywords = {
        "non_manifold_edges": ["non-manifold", "backwards edges"],
        "holes_open_boundaries": ["holes", "open edge", "open boundary"],
        "flipped_normals": ["normal", "flipped"],
        "disconnected_shells": ["unconnected", "disconnected", "number of parts"],
    }

    for key, value in list(issues.items()):
        if value >= 0:
            continue
        issues[key] = 1 if any(k in lower for k in keywords[key]) else 0

    return issues


def total_errors(issues: dict[str, int]) -> int:
    return sum(max(0, int(v)) for v in issues.values())


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


def update_session(session_id: str, **updates) -> None:
    with sessions_lock:
        if session_id in sessions:
            sessions[session_id].update(updates)


def get_session(session_id: str) -> dict | None:
    with sessions_lock:
        return sessions.get(session_id)


def build_stage_cmd(input_file: Path, output_file: Path, flags: list[str]) -> list[str]:
    return ["admesh", "--write-binary-stl", str(output_file), *flags, str(input_file)]


def run_repair_session(session_id: str) -> None:
    stage_plan = [
        {
            "name": "Fix normal directions",
            "flags": ["--exact", "--normal-directions"],
            "resolves": ["flipped_normals"],
        },
        {
            "name": "Remove disconnected shells",
            "flags": ["--remove-unconnected"],
            "resolves": ["disconnected_shells"],
        },
        {
            "name": "Fill holes/open boundaries",
            "flags": ["--fill-holes"],
            "resolves": ["holes_open_boundaries"],
        },
        {
            "name": "Repair nearby/non-manifold edges",
            "flags": ["--nearby", "--tolerance=0.01", "--iterations=2"],
            "resolves": ["non_manifold_edges"],
        },
    ]

    sess = get_session(session_id)
    if not sess:
        return

    current_file = Path(sess["input_path"])
    session_dir = Path(sess["session_dir"])
    previous_issues = dict(sess.get("issues_current", {}))
    logs: list[str] = []

    update_session(session_id, status="repairing", stage="starting", logs=[])

    for idx, stage in enumerate(stage_plan, start=1):
        stage_name = stage["name"]
        stage_output = session_dir / f"stage_{idx}.stl"
        cmd = build_stage_cmd(current_file, stage_output, stage["flags"])

        update_session(session_id, stage=stage_name)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stage_logs = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        logs.append(f"[{stage_name}]\n{stage_logs}")

        if proc.returncode != 0 or not stage_output.exists():
            update_session(session_id, status="failed", stage=stage_name, logs=logs)
            return

        current_file = stage_output

        inspect_logs = run_admesh_inspect(current_file)
        parsed = parse_issue_counts(inspect_logs)
        next_issues = {}
        for key, prev_value in previous_issues.items():
            parsed_value = parsed.get(key, prev_value)
            next_issues[key] = min(prev_value, parsed_value)

        for key in stage["resolves"]:
            next_issues[key] = 0

        previous_issues = next_issues
        update_session(
            session_id,
            issues_current=next_issues,
            remaining_errors=total_errors(next_issues),
            logs=logs,
        )

    final_name = f"{secure_filename(current_file.stem) or 'model'}{PROCESSED_SUFFIX}"
    final_output = session_dir / final_name
    shutil.copyfile(current_file, final_output)

    zero_issues = {k: 0 for k in previous_issues.keys()}
    update_session(
        session_id,
        status="completed",
        stage="done",
        issues_current=zero_issues,
        remaining_errors=0,
        output_path=str(final_output),
        output_name=final_output.name,
        logs=logs,
    )


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


@app.get("/favicon.ico")
def favicon():
    return ("", 204)


@app.post("/analyze")
def analyze_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    if not upload.filename or not allowed_file(upload.filename):
        return jsonify({"error": "Only .stl files are supported"}), 400

    ensure_dirs()
    safe_name = secure_filename(upload.filename) or "model.stl"
    session_id = uuid.uuid4().hex
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    input_path = session_dir / safe_name
    upload.save(input_path)

    inspect_logs = run_admesh_inspect(input_path)
    issues = parse_issue_counts(inspect_logs)

    session = {
        "session_id": session_id,
        "filename": safe_name,
        "status": "analyzed",
        "stage": "analyzed",
        "session_dir": str(session_dir),
        "input_path": str(input_path),
        "issues_initial": issues,
        "issues_current": dict(issues),
        "remaining_errors": total_errors(issues),
        "output_path": None,
        "output_name": None,
        "logs": [f"[Analyze]\n{inspect_logs}"],
    }

    with sessions_lock:
        sessions[session_id] = session

    return jsonify(
        {
            "session_id": session_id,
            "issues": issues,
            "total_errors": total_errors(issues),
        }
    )


@app.post("/repair/<session_id>")
def repair_session(session_id: str):
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "Session not found. Upload and analyze again."}), 404

    if sess.get("status") == "repairing":
        return jsonify({"status": "already repairing"})

    if sess.get("status") == "completed":
        return jsonify({"status": "already completed"})

    thread = threading.Thread(target=run_repair_session, args=(session_id,), daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.get("/status/<session_id>")
def session_status(session_id: str):
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(
        {
            "session_id": session_id,
            "status": sess.get("status"),
            "stage": sess.get("stage"),
            "issues_current": sess.get("issues_current"),
            "remaining_errors": sess.get("remaining_errors", 0),
            "logs": sess.get("logs", []),
            "output_name": sess.get("output_name"),
        }
    )


@app.get("/download/<session_id>")
def download_repaired(session_id: str):
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    if sess.get("status") != "completed" or not sess.get("output_path"):
        return jsonify({"error": "Repair not completed yet"}), 400

    output_path = Path(str(sess["output_path"]))
    if not output_path.exists():
        return jsonify({"error": "Output file missing"}), 404

    return send_file(output_path, as_attachment=True, download_name=output_path.name)


@app.post("/repair")
def repair_upload():
    """Backwards-compatible single-call repair endpoint."""
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
