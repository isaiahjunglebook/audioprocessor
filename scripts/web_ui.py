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
import queue
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".aac"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2GB — a very long recording

JOBS: dict[int, dict] = {}
JOB_QUEUE: "queue.Queue[int]" = queue.Queue()
_lock = threading.Lock()
_next_id = 1
DEFAULT_OUT = str(Path.home() / "Documents" / "Transcripts")


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
        }
    JOB_QUEUE.put(job_id)
    return job_id


def _set(job_id: int, **fields) -> None:
    with _lock:
        JOBS[job_id].update(fields)


def _worker() -> None:
    """Run one job at a time. Transcription is CPU-bound; running several at
    once makes every one of them slower, so the queue is deliberately serial."""
    while True:
        job_id = JOB_QUEUE.get()
        job = JOBS[job_id]
        staging = Path(job["path"]).parent
        try:
            _set(job_id, status="running", detail="transcribing — this takes about "
                                                 "as long as the recording")
            if job["engine"] == "whisperx":
                cmd = ["bash", str(REPO / "scripts" / "transcribe_folder_whisperx.sh"),
                       str(staging), job["out_dir"]]
                if job["names"].strip():
                    cmd.append(job["names"].strip())
            else:
                cmd = ["bash", str(REPO / "scripts" / "transcribe_folder.sh"),
                       str(staging), job["out_dir"]]

            proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
            stem = Path(job["name"]).stem
            produced = Path(job["out_dir"]) / f"{stem}.md"

            if proc.returncode == 0 and produced.is_file():
                _set(job_id, status="done", detail=f"saved to {produced}",
                     result=str(produced))
            else:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                _set(job_id, status="failed",
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
  .job { background:var(--card); border:1px solid var(--line); border-radius:11px;
         padding:14px 16px; margin-top:10px; }
  .job b { font-size:14px; }
  .job .detail { color:var(--muted); font-size:12.5px; margin-top:4px;
                 white-space:pre-wrap; word-break:break-word; }
  .pill { float:right; font-size:11px; padding:3px 9px; border-radius:99px;
          background:var(--line); text-transform:uppercase; letter-spacing:.04em; }
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

<label for="out">Save transcripts to</label>
<input id="out" value="__DEFAULT_OUT__" spellcheck="false">
<div class="hint">Full path to a folder on this Mac. It'll be created if missing.</div>

<label for="engine">Transcript type</label>
<select id="engine">
  <option value="whisperx">Speaker names + timestamps (slower, needs WhisperX)</option>
  <option value="timestamps">Timestamps only (no speaker names)</option>
</select>

<label for="names">Who's talking, most talkative first</label>
<input id="names" value="Dad,Isaiah" spellcheck="false">
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
    document.getElementById('jobs').innerHTML = jobs.length ? jobs.map(j=>
      `<div class="job ${j.status}"><span class="pill">${j.status}</span>`+
      `<b>${esc(j.name)}</b><div class="detail">${esc(j.detail)}</div></div>`).join('')
      : '<div class="job"><div class="detail">Nothing yet.</div></div>';
  }catch(e){}
}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
refresh(); setInterval(refresh, 2000);
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
            page = PAGE.replace("__DEFAULT_OUT__", self.server.default_out)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/jobs":
            with _lock:
                jobs = sorted(JOBS.values(), key=lambda j: -j["id"])[:20]
            self._send(200, json.dumps(jobs).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        parts = urlparse(self.path)
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
    p.add_argument("--out", default=DEFAULT_OUT, help="Default output folder shown on the page")
    p.add_argument("--no-browser", action="store_true", help="Don't open a browser window")
    args = p.parse_args(argv)

    threading.Thread(target=_worker, daemon=True).start()

    # 127.0.0.1, never 0.0.0.0: this server starts processes, so it must not be
    # reachable from anything but this machine.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.default_out = args.out
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
