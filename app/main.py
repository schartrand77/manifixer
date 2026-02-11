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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Manrope:wght@500;700&display=swap" rel="stylesheet">
    <style>
      :root {
        --ink: #1f2937;
        --muted: #5d6673;
        --card: #ffffff;
        --line: #d7dee8;
        --brand: #ef6c2f;
        --brand-strong: #cb4f17;
        --accent: #0f766e;
        --danger: #c2410c;
        --good: #0f766e;
        --soft: #f6f8fb;
      }
      * {
        box-sizing: border-box;
      }
      body {
        font-family: "Space Grotesk", "Manrope", "Trebuchet MS", sans-serif;
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at 8% 12%, #ffd7be 0%, transparent 34%),
          radial-gradient(circle at 89% 15%, #b9f3e4 0%, transparent 30%),
          linear-gradient(180deg, #f4f7fb 0%, #f8fafc 100%);
        min-height: 100vh;
      }

      body::before,
      body::after {
        content: "";
        position: fixed;
        z-index: -1;
        border-radius: 999px;
        opacity: 0.25;
        pointer-events: none;
      }

      body::before {
        width: 380px;
        height: 380px;
        background: #ffc19c;
        top: -130px;
        right: -90px;
        filter: blur(15px);
      }

      body::after {
        width: 320px;
        height: 320px;
        background: #9de5db;
        bottom: -130px;
        left: -60px;
        filter: blur(18px);
      }

      .wrap {
        max-width: 980px;
        margin: 2.4rem auto 3rem;
        padding: 0 1.1rem;
      }

      .card {
        background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 1.1rem 1.15rem;
        margin-bottom: 0.95rem;
        box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
        animation: riseIn 600ms ease both;
      }

      .card:nth-child(2) { animation-delay: 70ms; }
      .card:nth-child(3) { animation-delay: 120ms; }
      .card:nth-child(4) { animation-delay: 170ms; }
      .card:nth-child(5) { animation-delay: 220ms; }

      @keyframes riseIn {
        from {
          transform: translateY(14px);
          opacity: 0;
        }
        to {
          transform: translateY(0);
          opacity: 1;
        }
      }

      .hero {
        padding: 1.4rem 1.2rem;
        background:
          linear-gradient(140deg, rgba(239, 108, 47, 0.12) 0%, rgba(15, 118, 110, 0.12) 100%),
          #ffffff;
      }

      h1 {
        margin: 0;
        font-size: clamp(1.7rem, 4vw, 2.5rem);
        line-height: 1.05;
        letter-spacing: 0.01em;
      }

      h2 {
        margin: 0 0 0.65rem 0;
        font-size: 1.08rem;
      }

      p {
        margin: 0.35rem 0 0.8rem 0;
      }

      .hero p {
        max-width: 70ch;
      }

      .muted {
        color: var(--muted);
      }

      .split {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
      }

      .meta-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
      }

      .meta-badges span {
        border: 1px solid #cfd9e7;
        border-radius: 999px;
        padding: 0.2rem 0.6rem;
        font-size: 0.79rem;
        background: #f8fafc;
      }

      .row {
        display: flex;
        gap: 0.65rem;
        flex-wrap: wrap;
        align-items: center;
      }

      input[type="file"] {
        border: 1px dashed #8fa3bd;
        background: #f8fbff;
        border-radius: 12px;
        padding: 0.65rem 0.75rem;
        font-family: inherit;
        font-size: 0.94rem;
      }

      button {
        font-family: inherit;
        font-weight: 700;
        letter-spacing: 0.01em;
        color: #ffffff;
        background: linear-gradient(145deg, var(--brand) 0%, var(--brand-strong) 100%);
        border: none;
        border-radius: 12px;
        padding: 0.62rem 1.1rem;
        cursor: pointer;
        transition: transform 140ms ease, filter 140ms ease;
      }

      button:hover {
        transform: translateY(-1px);
        filter: saturate(1.08);
      }

      button:disabled {
        background: #9aa7b8;
        cursor: not-allowed;
        transform: none;
        filter: none;
      }

      .download-btn {
        display: inline-block;
        text-decoration: none;
        background: linear-gradient(150deg, #118a77 0%, #0d6b64 100%);
        color: #fff;
        border-radius: 12px;
        padding: 0.62rem 1.05rem;
        font-weight: 700;
        transition: transform 140ms ease;
      }

      .download-btn:hover {
        transform: translateY(-1px);
      }

      .timeline {
        display: flex;
        gap: 0.5rem;
        align-items: center;
        flex-wrap: wrap;
        margin-bottom: 0.65rem;
      }

      .timeline span {
        font-size: 0.78rem;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        padding: 0.18rem 0.5rem;
        border-radius: 999px;
        border: 1px solid #d6dfeb;
        color: #4f5b69;
        background: #f9fbfd;
      }

      .issues {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
        gap: 0.55rem;
      }

      .issue {
        border: 1px solid #d8e0ec;
        border-radius: 14px;
        padding: 0.7rem 0.7rem 0.63rem;
        background: linear-gradient(180deg, #f9fbfe 0%, #f5f8fc 100%);
      }

      .issue-name {
        font-size: 0.8rem;
        color: var(--muted);
      }

      .issue-count {
        font-size: 1.48rem;
        font-weight: 700;
        line-height: 1.05;
      }

      .issue-count.ok {
        color: var(--good);
      }

      .issue-count.bad {
        color: var(--danger);
      }

      .issue-bar {
        margin-top: 0.36rem;
        height: 7px;
        border-radius: 999px;
        overflow: hidden;
        background: #e6edf5;
      }

      .issue-bar-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #f97316 0%, #fb923c 100%);
        transition: width 360ms ease;
      }

      .status-pill {
        display: inline-block;
        font-size: 0.79rem;
        border-radius: 999px;
        padding: 0.22rem 0.62rem;
        border: 1px solid #cfd9e6;
        color: #4f5b67;
        background: #f8fafd;
      }

      .status-pill.active {
        border-color: #f2b58d;
        background: #fff3eb;
        color: #9a3f14;
      }

      .status-pill.good {
        border-color: #95d8ca;
        background: #ebfffb;
        color: #0d5f56;
      }

      .status-pill.bad {
        border-color: #f2b7a8;
        background: #fff1ee;
        color: #9b2d19;
      }

      .progress {
        width: 100%;
        height: 11px;
        border-radius: 999px;
        background: #e6ecf4;
        overflow: hidden;
      }

      .progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #ef6c2f 0%, #f79a43 50%, #0f766e 100%);
        transition: width 380ms ease;
      }

      pre {
        white-space: pre-wrap;
        max-height: 260px;
        overflow: auto;
        margin: 0;
        background: #1b2533;
        color: #d8e3f4;
        border-radius: 12px;
        padding: 0.82rem;
        border: 1px solid #2d3c52;
        font-size: 0.8rem;
        line-height: 1.4;
      }

      .mono {
        font-family: "Consolas", "SFMono-Regular", "Liberation Mono", monospace;
      }

      @media (max-width: 700px) {
        .wrap {
          margin-top: 1.35rem;
          padding: 0 0.75rem;
        }

        .card {
          padding: 0.92rem 0.9rem;
          border-radius: 14px;
        }

        h1 {
          font-size: 1.7rem;
        }
      }
    </style>
  </head>
  <body>
    <main class="wrap">
      <div class="card hero">
        <div class="split">
          <div>
            <h1>{{title}}</h1>
            <p class="muted">Upload one STL, inspect mesh problems, run a staged fix, then download the repaired model.</p>
          </div>
          <div class="meta-badges">
            <span>Web + Watch Mode</span>
            <span>STL Repair</span>
            <span>admesh Engine</span>
          </div>
        </div>
        <p class="muted mono">watch: {{input_dir}} -> {{output_dir}}</p>
      </div>

      <div class="card">
        <div class="timeline">
          <span>Step 1</span><span>Upload</span><span>Analyze</span>
        </div>
        <h2>1) Upload and Analyze</h2>
        <div class="row">
          <input id="fileInput" type="file" accept=".stl" />
          <button id="analyzeBtn" type="button">Analyze Errors</button>
        </div>
        <p id="analyzeMsg" class="muted"></p>
      </div>

      <div class="card" id="issuesCard" style="display:none;">
        <div class="timeline">
          <span>Step 2</span><span>Repair</span><span>Track Errors</span>
        </div>
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
        <div class="timeline">
          <span>Step 3</span><span>Download</span>
        </div>
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

      function setStatusTone(statusText) {
        statusPill.className = "status-pill";
        if (statusText === "completed") {
          statusPill.classList.add("good");
          return;
        }
        if (statusText === "failed") {
          statusPill.classList.add("bad");
          return;
        }
        if (statusText === "repairing" || statusText === "starting repair" || statusText === "analyzed") {
          statusPill.classList.add("active");
        }
      }

      function renderIssues(issues) {
        issuesGrid.innerHTML = "";
        let maxCount = 0;
        Object.keys(ISSUE_LABELS).forEach((key) => {
          const value = Number((issues && Object.prototype.hasOwnProperty.call(issues, key)) ? issues[key] : 0);
          if (value > maxCount) maxCount = value;
        });
        if (maxCount < 1) maxCount = 1;

        Object.entries(ISSUE_LABELS).forEach(([key, label]) => {
          const count = Number((issues && Object.prototype.hasOwnProperty.call(issues, key)) ? issues[key] : 0);
          const pct = Math.max(4, Math.min(100, Math.round((count / maxCount) * 100)));
          const div = document.createElement("div");
          div.className = "issue";
          div.innerHTML = `
            <div class="issue-name">${label}</div>
            <div class="issue-count ${count > 0 ? "bad" : "ok"}">${count}</div>
            <div class="issue-bar"><div class="issue-bar-fill" style="width:${count > 0 ? pct : 0}%"></div></div>
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
        setStatusTone(data.status);

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
        setStatusTone("starting repair");
        logsCard.style.display = "";
        logs.textContent = "";

        const res = await fetch(`/repair/${state.sessionId}`, { method: "POST" });
        const data = await res.json();

        if (!res.ok) {
          statusPill.textContent = "failed";
          setStatusTone("failed");
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
