import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from hashlib import sha256
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file
import trimesh
from werkzeug.utils import secure_filename

APP_TITLE = "Manifixer"
INPUT_DIR = Path(os.getenv("INPUT_DIR", "/data/input"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/output"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
WATCH_MODE = os.getenv("WATCH_MODE", "1") == "1"
PORT = int(os.getenv("PORT", "8080"))
SESSION_ROOT = Path(tempfile.gettempdir()) / "manifixer-sessions"
WATCH_WORKERS = max(1, int(os.getenv("WATCH_WORKERS", "1")))
SESSION_TTL_SECONDS = max(60, int(os.getenv("SESSION_TTL_SECONDS", "7200")))
CLEANUP_SECONDS = max(30, int(os.getenv("CLEANUP_SECONDS", "300")))
STABILITY_CHECK_SECONDS = max(1, int(os.getenv("STABILITY_CHECK_SECONDS", "3")))
STABILITY_MAX_WAIT_SECONDS = max(
    STABILITY_CHECK_SECONDS, int(os.getenv("STABILITY_MAX_WAIT_SECONDS", "120"))
)
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "40"))
MAX_SESSION_LOG_CHARS = int(os.getenv("MAX_SESSION_LOG_CHARS", "60000"))
ADMESH_TIMEOUT_SECONDS = int(os.getenv("ADMESH_TIMEOUT_SECONDS", "180"))

REPAIR_ALLOWED_EXTENSIONS = {"stl"}
CONVERTER_ALLOWED_EXTENSIONS = {"3mf", "stl", "obj", "ply", "off", "glb"}
CONVERTER_EXPORT_TYPES = {
    "3mf": "3mf",
    "stl": "stl",
    "obj": "obj",
    "ply": "ply",
    "off": "off",
    "glb": "glb",
}
CONVERTER_SCENE_TARGETS = {"3mf", "glb"}
DEFAULT_CONVERTER_TARGET = "stl"
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

      select {
        border: 1px solid #8fa3bd;
        background: #ffffff;
        border-radius: 12px;
        padding: 0.62rem 0.75rem;
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
            <p class="muted">Repair STL files with staged mesh fixes, or convert between common 3D formats like 3MF, STL, and OBJ.</p>
          </div>
          <div class="meta-badges">
            <span>Web + Watch Mode</span>
            <span>STL Repair</span>
            <span>3D Converter</span>
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

      <div class="card" id="convertCard">
        <div class="timeline">
          <span>Tool</span><span>Convert</span>
        </div>
        <h2>4) Convert 3D File Format</h2>
        <div class="row">
          <input id="convertFileInput" type="file" accept=".3mf,.stl,.obj,.ply,.off,.glb" />
          <select id="convertTarget">
            <option value="stl">STL</option>
            <option value="3mf">3MF</option>
            <option value="obj">OBJ</option>
            <option value="ply">PLY</option>
            <option value="off">OFF</option>
            <option value="glb">GLB</option>
          </select>
          <button id="convertBtn" type="button">Convert File</button>
        </div>
        <p id="convertMsg" class="muted"></p>
        <a id="convertDownloadBtn" class="download-btn" href="#" style="display:none;">Download Converted File</a>
      </div>

      <div class="card" id="reportCard" style="display:none;">
        <h2>Quality Report</h2>
        <pre id="reportView"></pre>
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
      const reportCard = document.getElementById("reportCard");
      const reportView = document.getElementById("reportView");
      const logsCard = document.getElementById("logsCard");
      const logs = document.getElementById("logs");
      const convertFileInput = document.getElementById("convertFileInput");
      const convertTarget = document.getElementById("convertTarget");
      const convertBtn = document.getElementById("convertBtn");
      const convertMsg = document.getElementById("convertMsg");
      const convertDownloadBtn = document.getElementById("convertDownloadBtn");

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

      function renderQualityReport(report) {
        if (!report) {
          reportCard.style.display = "none";
          reportView.textContent = "";
          return;
        }
        const errors = report.errors || {};
        const metrics = report.metrics || {};
        reportCard.style.display = "";
        reportView.textContent = [
          `Confidence: ${report.confidence || "unknown"}`,
          `Errors: ${errors.before ?? "n/a"} -> ${errors.after ?? "n/a"} (reduced: ${errors.reduced ?? "n/a"})`,
          `Triangles: ${metrics.triangle_count_before ?? "n/a"} -> ${metrics.triangle_count_after ?? "n/a"} (delta: ${metrics.triangle_count_delta ?? "n/a"})`,
          `Parts: ${metrics.part_count_before ?? "n/a"} -> ${metrics.part_count_after ?? "n/a"} (delta: ${metrics.part_count_delta ?? "n/a"})`
        ].join("\\n");
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
        renderQualityReport(data.quality_report);

        if (data.status === "completed") {
          clearInterval(state.polling);
          state.polling = null;
          progressFill.style.width = "100%";
          resultCard.style.display = "";
          if ((data.remaining_errors || 0) === 0) {
            resultMsg.textContent = "Repair completed. All detected errors were resolved.";
          } else {
            resultMsg.textContent = `Repair completed with ${data.remaining_errors} issue(s) remaining.`;
          }
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
          renderQualityReport(data.quality_report);
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

      convertBtn.addEventListener("click", async () => {
        const file = (convertFileInput.files && convertFileInput.files[0]) ? convertFileInput.files[0] : null;
        if (!file) {
          convertMsg.textContent = "Choose a file to convert first.";
          return;
        }

        const target = convertTarget.value;
        convertBtn.disabled = true;
        convertMsg.textContent = "Converting file...";
        convertDownloadBtn.style.display = "none";

        const form = new FormData();
        form.append("file", file);
        form.append("target_format", target);

        try {
          const res = await fetch("/convert", { method: "POST", body: form });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            convertMsg.textContent = data.error || "Conversion failed.";
            return;
          }

          const outputName = res.headers.get("X-Output-Name") || "converted-model";
          const blob = await res.blob();
          const objectUrl = URL.createObjectURL(blob);

          convertDownloadBtn.href = objectUrl;
          convertDownloadBtn.download = outputName;
          convertDownloadBtn.style.display = "inline-block";
          convertMsg.textContent = `Converted successfully to ${target.toUpperCase()}.`;
        } catch (err) {
          console.error("Conversion failed", err);
          convertMsg.textContent = `Conversion failed: ${err}`;
        } finally {
          convertBtn.disabled = false;
        }
      });
    </script>
  </body>
</html>
"""

app = Flask(__name__)
sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()
watch_queue: queue.Queue[tuple[Path, float]] = queue.Queue()
queued_versions: dict[Path, float] = {}
queued_versions_lock = threading.Lock()
session_order: deque[str] = deque()
stats_lock = threading.Lock()
stats = {
    "analyze_requests": 0,
    "repair_requests": 0,
    "repair_success": 0,
    "repair_failed": 0,
    "watch_processed": 0,
    "watch_failed": 0,
}

ISSUE_PATTERNS = {
    "non_manifold_edges": [
        re.compile(r"non[- ]manifold edges?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"backwards edges?\s*:\s*(\d+)", flags=re.IGNORECASE),
    ],
    "holes_open_boundaries": [
        re.compile(r"holes?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"open edges?\s*:\s*(\d+)", flags=re.IGNORECASE),
    ],
    "flipped_normals": [
        re.compile(r"flipped normals?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"inconsistent normals?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"incorrect normals?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"normal vectors? fixed\s*:\s*(\d+)", flags=re.IGNORECASE),
    ],
    "disconnected_shells": [
        re.compile(r"disconnected shells?\s*:\s*(\d+)", flags=re.IGNORECASE),
        re.compile(r"unconnected facets?\s*:\s*(\d+)", flags=re.IGNORECASE),
    ],
}
PARTS_PATTERN = re.compile(r"number of parts\s*:\s*(\d+)", flags=re.IGNORECASE)


def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)


def file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def allowed_repair_file(filename: str) -> bool:
    return file_extension(filename) in REPAIR_ALLOWED_EXTENSIONS


def allowed_converter_file(filename: str) -> bool:
    return file_extension(filename) in CONVERTER_ALLOWED_EXTENSIONS


def increment_stat(key: str) -> None:
    with stats_lock:
        stats[key] = int(stats.get(key, 0)) + 1


def trim_logs(logs: list[str]) -> list[str]:
    joined = "\n\n".join(logs)
    if len(joined) <= MAX_SESSION_LOG_CHARS:
        return logs
    keep_tail = joined[-MAX_SESSION_LOG_CHARS:]
    marker = "[trimmed older logs]\n"
    return [f"{marker}{keep_tail}"]


def cleanup_expired_sessions(now: float | None = None) -> None:
    cutoff = (now or time.time()) - SESSION_TTL_SECONDS
    expired: list[str] = []
    with sessions_lock:
        for sid, sess in sessions.items():
            last_touch = float(sess.get("updated_at", sess.get("created_at", 0)))
            if last_touch < cutoff:
                expired.append(sid)

        for sid in expired:
            sess = sessions.pop(sid, None)
            if sess:
                try:
                    shutil.rmtree(sess.get("session_dir", ""), ignore_errors=True)
                except Exception:
                    pass
            try:
                session_order.remove(sid)
            except ValueError:
                pass


def enforce_session_limit() -> None:
    while len(session_order) > MAX_SESSIONS:
        oldest_id = session_order.popleft()
        sess = sessions.pop(oldest_id, None)
        if not sess:
            continue
        try:
            shutil.rmtree(sess.get("session_dir", ""), ignore_errors=True)
        except Exception:
            pass


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ADMESH_TIMEOUT_SECONDS)
        logs = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return proc.returncode == 0 and output_file.exists(), logs.strip()
    except subprocess.TimeoutExpired:
        return False, f"admesh timed out after {ADMESH_TIMEOUT_SECONDS}s"


def run_admesh_inspect(mesh_file: Path) -> str:
    cmd = ["admesh", "--exact", str(mesh_file)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ADMESH_TIMEOUT_SECONDS)
        return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return f"admesh inspect timed out after {ADMESH_TIMEOUT_SECONDS}s"


def convert_mesh(input_file: Path, output_file: Path, target_format: str) -> None:
    fmt = target_format.lower()
    export_type = CONVERTER_EXPORT_TYPES.get(fmt)
    if not export_type:
        raise ValueError(f"Unsupported target format: {target_format}")

    try:
        loaded = trimesh.load(str(input_file), force="scene")
    except Exception as exc:
        raise ValueError(f"Could not read input mesh: {exc}") from exc

    if isinstance(loaded, trimesh.Scene):
        scene = loaded
        if not scene.geometry:
            raise ValueError("Input model has no geometry.")
        mesh = scene.dump(concatenate=True)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
        scene = trimesh.Scene(mesh)
    else:
        raise ValueError("Unsupported mesh data in input file.")

    if mesh is None or len(mesh.faces) == 0:
        raise ValueError("Input model does not contain triangle faces.")

    target = scene if fmt in CONVERTER_SCENE_TARGETS else mesh
    try:
        target.export(file_obj=str(output_file), file_type=export_type)
    except Exception as exc:
        raise ValueError(f"Could not export to {target_format}: {exc}") from exc

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise ValueError("Conversion produced an empty output file.")


def parse_issue_counts(admesh_text: str) -> dict[str, int]:
    text = admesh_text or ""
    lower = text.lower()

    def pick_int(patterns: list[re.Pattern[str]]) -> int:
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                try:
                    return max(0, int(m.group(1)))
                except (TypeError, ValueError):
                    continue
        return -1

    issues = {key: pick_int(patterns) for key, patterns in ISSUE_PATTERNS.items()}

    parts_match = PARTS_PATTERN.search(text)
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


def parse_mesh_metrics(admesh_text: str) -> dict[str, int | None]:
    text = admesh_text or ""

    def pick(pattern: str) -> int | None:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    return {
        "triangle_count": pick(r"number of facets\s*:\s*(\d+)"),
        "part_count": pick(r"number of parts\s*:\s*(\d+)"),
    }


def build_quality_report(
    before_issues: dict[str, int],
    after_issues: dict[str, int],
    before_metrics: dict[str, int | None],
    after_metrics: dict[str, int | None],
) -> dict:
    before_total = total_errors(before_issues)
    after_total = total_errors(after_issues)
    reduced = max(0, before_total - after_total)

    confidence = "low"
    if after_total == 0:
        confidence = "high"
    elif reduced > 0:
        confidence = "medium"

    tri_before = before_metrics.get("triangle_count")
    tri_after = after_metrics.get("triangle_count")
    part_before = before_metrics.get("part_count")
    part_after = after_metrics.get("part_count")

    return {
        "errors": {
            "before": before_total,
            "after": after_total,
            "reduced": reduced,
        },
        "metrics": {
            "triangle_count_before": tri_before,
            "triangle_count_after": tri_after,
            "triangle_count_delta": (
                tri_after - tri_before if tri_before is not None and tri_after is not None else None
            ),
            "part_count_before": part_before,
            "part_count_after": part_after,
            "part_count_delta": (
                part_after - part_before
                if part_before is not None and part_after is not None
                else None
            ),
        },
        "confidence": confidence,
    }


def unique_output_path(base_dir: Path, stem: str, suffix: str) -> Path:
    safe_stem = secure_filename(stem) or "model"
    candidate = base_dir / f"{safe_stem}{suffix}"
    if not candidate.exists():
        return candidate

    if suffix.lower().endswith(".stl"):
        numbered_suffix_prefix = suffix[:-4]
        numbered_suffix_ext = ".stl"
    else:
        numbered_suffix_prefix = suffix
        numbered_suffix_ext = ""

    index = 1
    while True:
        candidate = base_dir / f"{safe_stem}{numbered_suffix_prefix}.{index}{numbered_suffix_ext}"
        if not candidate.exists():
            return candidate
        index += 1


def process_one_file(source: Path) -> tuple[bool, str, Path, dict]:
    safe_stem = secure_filename(source.stem) or "model"
    destination = unique_output_path(OUTPUT_DIR, safe_stem, PROCESSED_SUFFIX)
    before_inspect_logs = run_admesh_inspect(source)
    before_issues = parse_issue_counts(before_inspect_logs)
    before_metrics = parse_mesh_metrics(before_inspect_logs)
    success, logs = run_repair(source, destination)
    after_issues = dict(before_issues)
    after_metrics = dict(before_metrics)
    if success:
        after_inspect_logs = run_admesh_inspect(destination)
        after_issues = parse_issue_counts(after_inspect_logs)
        after_metrics = parse_mesh_metrics(after_inspect_logs)

    report = build_quality_report(before_issues, after_issues, before_metrics, after_metrics)
    return success, logs, destination, report


def is_file_stable(path: Path, stable_seconds: int, max_wait_seconds: int) -> bool:
    started = time.time()
    previous_size = -1
    previous_mtime = -1.0
    stable_for = 0.0

    while time.time() - started <= max_wait_seconds:
        if not path.exists():
            return False
        stat = path.stat()
        size_now = stat.st_size
        mtime_now = stat.st_mtime

        if size_now == previous_size and mtime_now == previous_mtime:
            stable_for += 1.0
            if stable_for >= stable_seconds:
                return True
        else:
            stable_for = 0.0

        previous_size = size_now
        previous_mtime = mtime_now
        time.sleep(1)

    return False


def enqueue_watch_file(path: Path, mtime: float) -> None:
    with queued_versions_lock:
        existing = queued_versions.get(path)
        if existing == mtime:
            return
        queued_versions[path] = mtime
    watch_queue.put((path, mtime))


def watch_worker_loop(worker_id: int) -> None:
    while True:
        stl, enqueued_mtime = watch_queue.get()
        try:
            with queued_versions_lock:
                current = queued_versions.get(stl)
                if current == enqueued_mtime:
                    queued_versions.pop(stl, None)

            if not stl.exists():
                continue

            if not is_file_stable(stl, STABILITY_CHECK_SECONDS, STABILITY_MAX_WAIT_SECONDS):
                print(f"[WATCHER #{worker_id}] SKIP (unstable): {stl.name}", flush=True)
                continue

            ok, logs, output, report = process_one_file(stl)
            status = "OK" if ok else "FAIL"
            print(
                f"[WATCHER #{worker_id}] [{status}] {stl.name} -> {output.name}\n"
                f"Report: {report}\n{logs}\n",
                flush=True,
            )
        except Exception as exc:
            print(f"[WATCHER #{worker_id} ERROR] {exc}", flush=True)
        finally:
            watch_queue.task_done()


def watcher_loop() -> None:
    seen: dict[Path, float] = {}
    while True:
        try:
            cleanup_expired_sessions()
            for stl in INPUT_DIR.glob("*.stl"):
                mtime = stl.stat().st_mtime
                if seen.get(stl) == mtime:
                    continue
                seen[stl] = mtime
                enqueue_watch_file(stl, mtime)
        except Exception as exc:
            print(f"[WATCHER ERROR] {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def update_session(session_id: str, **updates) -> None:
    with sessions_lock:
        if session_id in sessions:
            updates["updated_at"] = time.time()
            sessions[session_id].update(updates)
            sessions[session_id]["updated_at"] = time.time()


def get_session(session_id: str, touch: bool = True) -> dict | None:
    with sessions_lock:
        sess = sessions.get(session_id)
        if sess and touch:
            now = time.time()
            sess["updated_at"] = now
            sess["last_accessed_at"] = now
        return sess


def remove_session_files(session_dir: str | None) -> None:
    if not session_dir:
        return
    try:
        shutil.rmtree(session_dir, ignore_errors=True)
    except Exception as exc:
        print(f"[CLEANUP ERROR] could not remove {session_dir}: {exc}", flush=True)


def cleanup_loop() -> None:
    while True:
        try:
            now = time.time()
            expired_dirs: list[str] = []
            with sessions_lock:
                expired_ids = [
                    sid
                    for sid, sess in sessions.items()
                    if now - float(sess.get("updated_at", now)) > SESSION_TTL_SECONDS
                ]
                for sid in expired_ids:
                    sess = sessions.pop(sid, None)
                    if sess:
                        expired_dirs.append(str(sess.get("session_dir", "")))

            for d in expired_dirs:
                remove_session_files(d)

            cutoff = now - SESSION_TTL_SECONDS
            for p in SESSION_ROOT.iterdir():
                if not p.is_dir():
                    continue
                try:
                    if p.stat().st_mtime < cutoff:
                        shutil.rmtree(p, ignore_errors=True)
                except FileNotFoundError:
                    continue
        except Exception as exc:
            print(f"[CLEANUP ERROR] {exc}", flush=True)
        time.sleep(CLEANUP_SECONDS)


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
    initial_issues = dict(sess.get("issues_initial", {}))
    initial_metrics = dict(sess.get("metrics_initial", {}))
    logs: list[str] = []

    update_session(session_id, status="repairing", stage="starting", logs=[])

    for idx, stage in enumerate(stage_plan, start=1):
        stage_name = stage["name"]
        stage_output = session_dir / f"stage_{idx}.stl"
        cmd = build_stage_cmd(current_file, stage_output, stage["flags"])

        update_session(session_id, stage=stage_name)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ADMESH_TIMEOUT_SECONDS)
            stage_logs = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        except subprocess.TimeoutExpired:
            stage_logs = f"admesh stage timed out after {ADMESH_TIMEOUT_SECONDS}s"
            proc = None

        logs.append(f"[{stage_name}]\n{stage_logs}")
        logs = trim_logs(logs)

        if proc is None or proc.returncode != 0 or not stage_output.exists():
            increment_stat("repair_failed")
            update_session(session_id, status="failed", stage=stage_name, logs=logs)
            return

        current_file = stage_output

        inspect_logs = run_admesh_inspect(current_file)
        parsed = parse_issue_counts(inspect_logs)
        parsed_metrics = parse_mesh_metrics(inspect_logs)
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
            metrics_current=parsed_metrics,
            remaining_errors=total_errors(next_issues),
            quality_report=build_quality_report(
                initial_issues,
                next_issues,
                initial_metrics,
                parsed_metrics,
            ),
            logs=trim_logs(logs),
        )

    final_output = unique_output_path(session_dir, secure_filename(current_file.stem) or "model", PROCESSED_SUFFIX)
    shutil.copyfile(current_file, final_output)

    final_inspect_logs = run_admesh_inspect(final_output)
    final_issues = parse_issue_counts(final_inspect_logs)
    final_metrics = parse_mesh_metrics(final_inspect_logs)
    quality_report = build_quality_report(
        initial_issues,
        final_issues,
        initial_metrics,
        final_metrics,
    )
    increment_stat("repair_success")
    update_session(
        session_id,
        status="completed",
        stage="done",
        issues_current=final_issues,
        remaining_errors=total_errors(final_issues),
        metrics_current=final_metrics,
        quality_report=quality_report,
        output_path=str(final_output),
        output_name=final_output.name,
        logs=trim_logs([*logs, f"[Final Analyze]\n{final_inspect_logs}"]),
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
    return jsonify(
        {
            "status": "ok",
            "watch_mode": WATCH_MODE,
            "watch_workers": WATCH_WORKERS,
            "queue_depth": watch_queue.qsize(),
            "poll_seconds": POLL_SECONDS,
            "session_ttl_seconds": SESSION_TTL_SECONDS,
        }
    )


@app.get("/favicon.ico")
def favicon():
    return ("", 204)


@app.post("/analyze")
def analyze_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    if not upload.filename or not allowed_repair_file(upload.filename):
        return jsonify({"error": "Only .stl files are supported"}), 400

    increment_stat("analyze_requests")
    cleanup_expired_sessions()
    ensure_dirs()

    safe_name = secure_filename(upload.filename) or "model.stl"
    session_id = uuid.uuid4().hex
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    input_path = session_dir / safe_name
    upload.save(input_path)
    file_digest = file_sha256(input_path)

    inspect_logs = run_admesh_inspect(input_path)
    issues = parse_issue_counts(inspect_logs)
    metrics = parse_mesh_metrics(inspect_logs)
    now = time.time()

    session = {
        "session_id": session_id,
        "filename": safe_name,
        "status": "analyzed",
        "stage": "analyzed",
        "session_dir": str(session_dir),
        "input_path": str(input_path),
        "file_sha256": file_digest,
        "issues_initial": issues,
        "issues_current": dict(issues),
        "metrics_initial": metrics,
        "metrics_current": dict(metrics),
        "remaining_errors": total_errors(issues),
        "output_path": None,
        "output_name": None,
        "quality_report": build_quality_report(issues, issues, metrics, metrics),
        "logs": trim_logs([f"[Analyze]\n{inspect_logs}"]),
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": now,
    }

    with sessions_lock:
        sessions[session_id] = session
        session_order.append(session_id)
        enforce_session_limit()

    return jsonify(
        {
            "session_id": session_id,
            "issues": issues,
            "metrics": metrics,
            "quality_report": session["quality_report"],
            "total_errors": total_errors(issues),
            "file_sha256": file_digest,
        }
    )


@app.post("/repair/<session_id>")
def repair_session(session_id: str):
    increment_stat("repair_requests")
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
            "metrics_current": sess.get("metrics_current"),
            "remaining_errors": sess.get("remaining_errors", 0),
            "quality_report": sess.get("quality_report"),
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


@app.post("/convert")
def convert_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    target_format = (request.form.get("target_format") or DEFAULT_CONVERTER_TARGET).strip().lower()

    if not upload.filename:
        return jsonify({"error": "No file selected"}), 400

    if not allowed_converter_file(upload.filename):
        supported = ", ".join(sorted(CONVERTER_ALLOWED_EXTENSIONS))
        return jsonify({"error": f"Unsupported input format. Supported: {supported}"}), 400

    if target_format not in CONVERTER_ALLOWED_EXTENSIONS:
        supported = ", ".join(sorted(CONVERTER_ALLOWED_EXTENSIONS))
        return jsonify({"error": f"Unsupported target format. Supported: {supported}"}), 400

    ensure_dirs()
    safe_name = secure_filename(upload.filename) or "model.stl"
    safe_stem = secure_filename(Path(safe_name).stem) or "model"

    with tempfile.TemporaryDirectory(prefix="manifixer-convert-") as td:
        temp_in = Path(td) / safe_name
        upload.save(temp_in)

        output_path = unique_output_path(OUTPUT_DIR, safe_stem, f".converted.{target_format}")
        try:
            convert_mesh(temp_in, output_path, target_format)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Conversion failed: {exc}"}), 500

    response = send_file(output_path, as_attachment=True, download_name=output_path.name)
    response.headers["X-Output-Name"] = output_path.name
    return response


@app.get("/metrics")
def metrics():
    with stats_lock:
        current_stats = dict(stats)
    with sessions_lock:
        active = len(sessions)
    return jsonify(
        {
            "status": "ok",
            "active_sessions": active,
            "max_sessions": MAX_SESSIONS,
            "session_ttl_seconds": SESSION_TTL_SECONDS,
            "admesh_timeout_seconds": ADMESH_TIMEOUT_SECONDS,
            "stats": current_stats,
        }
    )


@app.get("/sessions")
def list_sessions():
    cleanup_expired_sessions()
    with sessions_lock:
        items = [
            {
                "session_id": sid,
                "filename": s.get("filename"),
                "status": s.get("status"),
                "remaining_errors": s.get("remaining_errors", 0),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "output_name": s.get("output_name"),
            }
            for sid, s in sessions.items()
        ]
    items.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
    return jsonify({"sessions": items})


@app.delete("/sessions/<session_id>")
def delete_session(session_id: str):
    with sessions_lock:
        sess = sessions.pop(session_id, None)
        try:
            session_order.remove(session_id)
        except ValueError:
            pass
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    shutil.rmtree(sess.get("session_dir", ""), ignore_errors=True)
    return jsonify({"status": "deleted", "session_id": session_id})


@app.post("/repair")
def repair_upload():
    """Backwards-compatible single-call repair endpoint."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    if not upload.filename or not allowed_repair_file(upload.filename):
        return jsonify({"error": "Only .stl files are supported"}), 400

    ensure_dirs()
    safe_name = secure_filename(upload.filename)

    with tempfile.TemporaryDirectory(prefix="manifixer-") as td:
        temp_in = Path(td) / safe_name
        upload.save(temp_in)

        ok, logs, output, _report = process_one_file(temp_in)
        if not ok:
            return jsonify({"error": "Repair failed", "logs": logs}), 500

    return send_file(output, as_attachment=True, download_name=output.name)


if __name__ == "__main__":
    ensure_dirs()
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    if WATCH_MODE:
        producer_thread = threading.Thread(target=watcher_loop, daemon=True)
        producer_thread.start()
        for i in range(WATCH_WORKERS):
            worker_thread = threading.Thread(target=watch_worker_loop, args=(i + 1,), daemon=True)
            worker_thread.start()
    app.run(host="0.0.0.0", port=PORT)
