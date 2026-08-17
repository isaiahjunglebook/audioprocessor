#!/usr/bin/env python3
"""A drag-and-drop page for transcribing recordings, served from your own Mac.

Opens at http://127.0.0.1:8756 — drop an audio file on the page, choose where
the transcript should be saved, and it runs the same batch scripts the command
line uses. Nothing is uploaded anywhere: the browser is talking to a server on
this machine, and the audio never leaves it.

Deliberately standard-library only (no Flask, no framework) so it runs in the
repo virtualenv with nothing extra installed, and deliberately bound to
127.0.0.1 so nothing on the network can reach an endpoint that runs programs.

Usage:  python scripts/web_ui.py [--port 8756] [--out <default output folder>]
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # importable however the script was launched

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".aac"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2GB — a very long recording

JOBS: dict[int, dict] = {}
JOB_QUEUE: "queue.Queue[int]" = queue.Queue()
_lock = threading.Lock()
_next_id = 1


def _defaults() -> tuple[str, str]:
    """(output folder, speaker names) for the default project, if configured.

    Imported lazily and failure-tolerantly: the page must still start for
    someone with no config.yaml (or no PyYAML) yet.
    """
    try:
        from call_processor import config as config_mod, projects as projects_mod
        from call_processor.paths import format_value
        settings = projects_mod.resolve(config_mod.load_config(None))
        return (format_value(settings["transcripts_dir"], is_path=True) or DEFAULT_OUT,
                format_value(settings["speaker_names"]))
    except Exception:
        return DEFAULT_OUT, ""


def _reexec_in_venv() -> None:
    """Restart under the repo's virtualenv if this Python can't read config.

    Launching with the system `python3` is the natural thing to type, but
    PyYAML lives in the repo virtualenv — so config.yaml would silently fail
    to load and the page would come up with no projects and no defaults,
    looking like a config mistake rather than a wrong interpreter.
    """
    try:
        import yaml  # noqa: F401
        return       # this interpreter is fine
    except ImportError:
        pass
    venv_python = REPO / ".venv" / "bin" / "python"
    if not (venv_python.is_file() and os.access(venv_python, os.X_OK)):
        return       # nothing better available; carry on with defaults
    if Path(sys.executable).resolve() == venv_python.resolve():
        return       # already there — never loop
    print(f"  (restarting under {venv_python} so config.yaml can be read)")
    os.execv(str(venv_python),
             [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


def choose_folder_dialog(start: str = "") -> str | None:
    """Open the real macOS folder chooser and return the path picked.

    A browser can't hand a server a filesystem path — the File System Access
    API gives out opaque handles, not paths — but this server is on the same
    machine, so it can raise the native dialog itself. Returns None when the
    user cancels or the dialog isn't available (non-macOS, no osascript).
    """
    if not shutil.which("osascript"):
        return None
    default = ""
    if start:
        candidate = Path(start).expanduser()
        if candidate.is_dir():
            # AppleScript string literal: backslashes and quotes need escaping.
            escaped = str(candidate).replace("\\", "\\\\").replace('"', '\\"')
            default = f' default location POSIX file "{escaped}"'
    script = ('tell application "System Events" to activate\n'
              'POSIX path of (choose folder with prompt '
              f'"Where should transcripts be saved?"{default})')
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None          # cancelled, or the dialog failed
    return result.stdout.strip() or None


def _project_list() -> dict:
    """Projects from config.yaml, resolved for the picker. Empty if none."""
    try:
        from call_processor import config as config_mod, projects as projects_mod
        from call_processor.paths import format_value
        cfg = config_mod.load_config(None)
        out = {}
        for name in projects_mod.list_projects(cfg):
            settings = projects_mod.resolve(cfg, name)
            out[name] = {
                "transcripts_dir": format_value(settings["transcripts_dir"], is_path=True),
                "speaker_names": format_value(settings["speaker_names"]),
            }
        return {"projects": out, "current": projects_mod.default_project(cfg) or ""}
    except Exception:
        return {"projects": {}, "current": ""}


DEFAULT_OUT = str(Path.home() / "Documents" / "Transcripts")


# Progress is read out of the transcriber's own output. WhisperX prints a
# "[12.34 --> 56.78]" line per segment; call_processor prints "[progress] x/y".
# Either one tells us how far into the audio we are.
_SEG_RE = re.compile(r"\[(\d+(?:\.\d+)?)\s*-->\s*(\d+(?:\.\d+)?)\]")
_PROGRESS_RE = re.compile(r"\[progress\]\s*([\d.]+)\s*/\s*([\d.]+)")
_DIARIZE_RE = re.compile(r"diariz", re.IGNORECASE)


def audio_duration(path: Path) -> float:
    """Length of the recording in seconds, or 0 if ffprobe can't tell us.

    Without this a percentage is impossible — the transcriber reports where it
    is, not how far it has to go.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _humanize(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def _add_job(name: str, path: Path, out_dir: str, engine: str, names: str) -> int:
    global _next_id
    with _lock:
        job_id = _next_id
        _next_id += 1
        JOBS[job_id] = {
            "id": job_id, "name": name, "path": str(path), "out_dir": out_dir,
            "engine": engine, "names": names, "status": "queued",
            "detail": "waiting for the machine to be free",
            "queued_at": datetime.now().strftime("%H:%M:%S"), "result": None,
            "percent": 0, "phase": "", "eta": "", "elapsed": "",
        }
    JOB_QUEUE.put(job_id)
    return job_id


def _set(job_id: int, **fields) -> None:
    with _lock:
        JOBS[job_id].update(fields)


def _read_progress(job_id: int, line: str, total: float, started: float) -> None:
    """Update a job's percentage from one line of transcriber output."""
    # Diarization runs after transcription and reports nothing useful, so the
    # bar holds at 100% of *transcription* and the label says what's happening.
    if _DIARIZE_RE.search(line):
        _set(job_id, phase="finding speakers", percent=100, eta="almost there",
             elapsed=_humanize(time.monotonic() - started),
             detail="separating the voices — the last step, a few minutes")
        return

    position = 0.0
    known_total = total
    m = _PROGRESS_RE.search(line)
    if m:
        position, known_total = float(m.group(1)), float(m.group(2)) or total
    else:
        m = _SEG_RE.search(line)
        if m:
            position = float(m.group(2))
    if position <= 0 or known_total <= 0:
        return

    fraction = min(1.0, position / known_total)
    elapsed = time.monotonic() - started
    # Cap at 99: the job isn't done until the file is actually on disk.
    percent = min(99, int(fraction * 100))
    eta = ""
    if fraction > 0.02 and elapsed > 5:
        eta = f"about {_humanize(elapsed / fraction - elapsed)} left"
    _set(job_id, percent=percent, phase="transcribing", eta=eta,
         elapsed=_humanize(elapsed),
         detail=f"{_humanize(position)} of {_humanize(known_total)} transcribed")


def _worker() -> None:
    """Run one job at a time. Transcription is CPU-bound; running several at
    once makes every one of them slower, so the queue is deliberately serial."""
    while True:
        job_id = JOB_QUEUE.get()
        job = JOBS[job_id]
        staging = Path(job["path"]).parent
        try:
            total = audio_duration(Path(job["path"]))
            _set(job_id, status="running", phase="transcribing", percent=0,
                 detail=("transcribing — this takes about as long as the recording"
                         if not total else
                         f"transcribing {_humanize(total)} of audio"))
            if job["engine"] == "whisperx":
                cmd = ["bash", str(REPO / "scripts" / "transcribe_folder_whisperx.sh"),
                       str(staging), job["out_dir"]]
                if job["names"].strip():
                    cmd.append(job["names"].strip())
            else:
                cmd = ["bash", str(REPO / "scripts" / "transcribe_folder.sh"),
                       str(staging), job["out_dir"]]

            started = time.monotonic()
            tail: list[str] = []
            proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                tail = (tail + [line.rstrip()])[-40:]
                _read_progress(job_id, line, total, started)
            proc.wait()

            stem = Path(job["name"]).stem
            produced = Path(job["out_dir"]) / f"{stem}.md"

            if proc.returncode == 0 and produced.is_file():
                _set(job_id, status="done", percent=100, phase="", eta="",
                     elapsed=_humanize(time.monotonic() - started),
                     detail=f"saved to {produced}", result=str(produced))
            else:
                _set(job_id, status="failed", percent=0, phase="", eta="",
                     detail="\n".join(tail[-6:]) or "the transcriber exited with an error")
        except Exception as e:  # a crashed job must not take the server down
            _set(job_id, status="failed", detail=str(e))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            JOB_QUEUE.task_done()


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Transcribe</title>
<style>
  :root { color-scheme: light dark; --bg:#fbfbfd; --fg:#1d1d1f; --card:#fff;
          --line:#e3e3e8; --accent:#0071e3; --muted:#6e6e73; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#151517; --fg:#f5f5f7; --card:#1f1f22; --line:#34343a; --muted:#9a9aa0; } }
  * { box-sizing: border-box; }
  body { margin:0; padding:40px 20px; background:var(--bg); color:var(--fg);
         font:16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }
  .wrap { max-width:640px; margin:0 auto; }
  h1 { font-size:26px; margin:0 0 4px; letter-spacing:-.02em; }
  .sub { color:var(--muted); margin:0 0 28px; font-size:14px; }
  #drop { border:2px dashed var(--line); border-radius:14px; padding:48px 20px;
          text-align:center; background:var(--card); cursor:pointer; transition:.15s; }
  #drop.over { border-color:var(--accent); background:color-mix(in srgb, var(--accent) 8%, var(--card)); }
  #drop strong { display:block; font-size:18px; margin-bottom:6px; }
  #drop span { color:var(--muted); font-size:14px; }
  label { display:block; font-size:13px; font-weight:600; margin:20px 0 6px; }
  input, select { width:100%; padding:10px 12px; border:1px solid var(--line);
                  border-radius:9px; background:var(--card); color:var(--fg); font-size:14px; }
  .hint { color:var(--muted); font-size:12px; margin-top:5px; }
  .row { display:flex; gap:8px; align-items:stretch; }
  .row input { flex:1; min-width:0; }
  button { padding:10px 16px; border:1px solid var(--line); border-radius:9px;
           background:var(--card); color:var(--fg); font-size:14px; cursor:pointer;
           white-space:nowrap; font-family:inherit; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  button:disabled { opacity:.5; cursor:default; }
  .job { background:var(--card); border:1px solid var(--line); border-radius:11px;
         padding:14px 16px; margin-top:10px; }
  .job b { font-size:14px; }
  .job .detail { color:var(--muted); font-size:12.5px; margin-top:4px;
                 white-space:pre-wrap; word-break:break-word; }
  .pill { float:right; font-size:11px; padding:3px 9px; border-radius:99px;
          background:var(--line); text-transform:uppercase; letter-spacing:.04em; }
  .bar { height:7px; border-radius:99px; background:var(--line); margin-top:10px;
         overflow:hidden; }
  .bar i { display:block; height:100%; background:var(--accent); border-radius:99px;
           transition:width .4s ease; }
  .meta { display:flex; justify-content:space-between; color:var(--muted);
          font-size:12px; margin-top:6px; font-variant-numeric:tabular-nums; }
  .queued .pill{background:#8e8e93;color:#fff}.running .pill{background:#0071e3;color:#fff}
  .done .pill{background:#34c759;color:#fff}.failed .pill{background:#ff3b30;color:#fff}
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--muted); margin:34px 0 0; }
</style></head><body><div class="wrap">
<h1>Transcribe a recording</h1>
<p class="sub">Runs on this Mac. Nothing is uploaded anywhere.</p>

<div id="drop">
  <strong>Drop an audio file here</strong>
  <span>or click to choose &middot; m4a, mp3, wav, flac, aac</span>
  <input type="file" id="file" accept="audio/*" hidden multiple>
</div>

<div id="projectRow" hidden>
  <label for="project">Project</label>
  <select id="project"></select>
  <div class="hint">Switches the folder and speakers below. Edit either afterwards.</div>
</div>

<label for="out">Save transcripts to</label>
<div class="row">
  <input id="out" value="__DEFAULT_OUT__" spellcheck="false">
  <button id="browse" type="button" hidden>Choose…</button>
</div>
<div class="hint">Full path to a folder on this Mac. It'll be created if missing.</div>

<label for="engine">Transcript type</label>
<select id="engine">
  <option value="whisperx">Speaker names + timestamps (slower, needs WhisperX)</option>
  <option value="timestamps">Timestamps only (no speaker names)</option>
</select>

<label for="names">Who's talking, most talkative first</label>
<input id="names" value="__DEFAULT_NAMES__" spellcheck="false">
<div class="hint">Only used for the speaker-names option. Comma separated.</div>

<h2>Jobs</h2>
<div id="jobs"></div>
</div>
<script>
const drop=document.getElementById('drop'), file=document.getElementById('file');
drop.onclick=()=>file.click();
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};
drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');send(e.dataTransfer.files)};
file.onchange=()=>send(file.files);

async function send(files){
  for (const f of files){
    const q=new URLSearchParams({name:f.name, out:document.getElementById('out').value,
      engine:document.getElementById('engine').value, names:document.getElementById('names').value});
    try{
      const r=await fetch('/upload?'+q,{method:'POST',body:f});
      if(!r.ok) alert(await r.text());
    }catch(err){ alert('Upload failed: '+err); }
  }
  file.value=''; refresh();
}
async function refresh(){
  try{
    const jobs=await (await fetch('/jobs')).json();
    document.getElementById('jobs').innerHTML = jobs.length ? jobs.map(j=>{
      const active = j.status==='running';
      const bar = active
        ? `<div class="bar"><i style="width:${j.percent||0}%"></i></div>`+
          `<div class="meta"><span>${esc(j.phase)} &middot; ${j.percent||0}%</span>`+
          `<span>${esc(j.eta||'')}</span></div>`
        : '';
      return `<div class="job ${j.status}"><span class="pill">${j.status}</span>`+
             `<b>${esc(j.name)}</b><div class="detail">${esc(j.detail)}</div>${bar}</div>`;
    }).join('') : '<div class="job"><div class="detail">Nothing yet.</div></div>';
  }catch(e){}
}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}

// Projects are optional: with none configured the picker stays hidden and the
// page behaves exactly as it did before.
let PROJECTS={};
async function loadProjects(){
  try{
    const data=await (await fetch('/projects')).json();
    PROJECTS=data.projects||{};
    const names=Object.keys(PROJECTS);
    if(!names.length) return;
    const sel=document.getElementById('project');
    sel.innerHTML=names.map(n=>`<option value="${esc(n)}"${n===data.current?' selected':''}>${esc(n)}</option>`).join('');
    document.getElementById('projectRow').hidden=false;
    sel.onchange=()=>{
      const p=PROJECTS[sel.value]||{};
      if(p.transcripts_dir) document.getElementById('out').value=p.transcripts_dir;
      document.getElementById('names').value=p.speaker_names||'';
    };
  }catch(e){}
}
// Native folder chooser, opened by the server — a browser can only hand back
// an opaque handle, but the server is on this machine and can ask macOS.
const browse=document.getElementById('browse');
(async()=>{
  try{
    if(!(await (await fetch('/can-browse')).json()).ok) return;
    browse.hidden=false;
    browse.onclick=async()=>{
      browse.disabled=true; browse.textContent='Choose…';
      try{
        const out=document.getElementById('out');
        const r=await fetch('/choose-folder?current='+encodeURIComponent(out.value),{method:'POST'});
        const {path}=await r.json();
        if(path) out.value=path;          // empty means cancelled: keep what's there
      }catch(e){}
      browse.disabled=false;
    };
  }catch(e){}
})();

loadProjects(); refresh(); setInterval(refresh, 2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the terminal readable
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/":
            page = (PAGE.replace("__DEFAULT_OUT__", self.server.default_out)
                        .replace("__DEFAULT_NAMES__", self.server.default_names))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/can-browse":
            self._send(200, json.dumps({"ok": bool(shutil.which("osascript"))}).encode(),
                       "application/json")
        elif route == "/projects":
            self._send(200, json.dumps(_project_list()).encode(), "application/json")
        elif route == "/jobs":
            with _lock:
                jobs = sorted(JOBS.values(), key=lambda j: -j["id"])[:20]
            self._send(200, json.dumps(jobs).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        parts = urlparse(self.path)
        if parts.path == "/choose-folder":
            current = (parse_qs(parts.query).get("current") or [""])[0]
            chosen = choose_folder_dialog(current)
            return self._send(200, json.dumps({"path": chosen or ""}).encode(),
                              "application/json")
        if parts.path != "/upload":
            return self._send(404, b"not found", "text/plain")

        q = parse_qs(parts.query)
        name = Path((q.get("name") or ["recording"])[0]).name  # strip any path
        out_dir = (q.get("out") or [DEFAULT_OUT])[0].strip()
        engine = (q.get("engine") or ["whisperx"])[0]
        names = (q.get("names") or [""])[0]

        if Path(name).suffix.lower() not in AUDIO_EXTS:
            return self._send(400, f"'{name}' isn't an audio file I recognise "
                                   f"({', '.join(sorted(AUDIO_EXTS))}).".encode(),
                              "text/plain")
        if not out_dir:
            return self._send(400, b"Give me a folder to save transcripts into.",
                              "text/plain")

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._send(400, b"That file came through empty.", "text/plain")
        if length > MAX_UPLOAD_BYTES:
            return self._send(413, b"That file is larger than 2GB.", "text/plain")

        try:
            out_path = Path(out_dir).expanduser()
            out_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return self._send(400, f"Can't use that folder: {e}".encode(), "text/plain")

        # One staging folder per job: the batch scripts take a folder, and this
        # keeps concurrent uploads from being seen as tracks of one recording.
        staging = Path(tempfile.mkdtemp(prefix="transcribe-"))
        dest = staging / name
        remaining = length
        with open(dest, "wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            shutil.rmtree(staging, ignore_errors=True)
            return self._send(400, b"Upload was cut off. Try again.", "text/plain")

        job_id = _add_job(name, dest, str(out_path), engine, names)
        self._send(200, json.dumps({"id": job_id}).encode(), "application/json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local drag-and-drop transcription page.")
    p.add_argument("--port", type=int, default=8756)
    p.add_argument("--out", default=None,
                   help="Default output folder shown on the page "
                        "(default: paths.transcripts_dir from config.yaml)")
    p.add_argument("--names", default=None,
                   help="Default speaker names, most talkative first "
                        "(default: whisperx.speaker_names from config.yaml)")
    p.add_argument("--no-browser", action="store_true", help="Don't open a browser window")
    args = p.parse_args(argv)
    _reexec_in_venv()   # before any state exists, so restarting costs nothing

    threading.Thread(target=_worker, daemon=True).start()

    # 127.0.0.1, never 0.0.0.0: this server starts processes, so it must not be
    # reachable from anything but this machine.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    config_out, config_names = _defaults()
    server.default_out = args.out or config_out
    server.default_names = args.names or config_names
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  Transcriber running at {url}")
    print("  Leave this window open. Press Control-C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
