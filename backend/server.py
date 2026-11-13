#!/usr/bin/env python3
"""Local dd clone backend — stdlib only, no Flask, no subprocess.run."""
import json
import os
import re
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BACKEND_TOKEN = os.environ.get("BACKEND_TOKEN", "")
ALLOWED_DEVICES = [d.strip() for d in os.environ.get("ALLOWED_LOCAL_DEVICES", "").split(",") if d.strip()]
LISTEN = os.environ.get("LISTEN", "0.0.0.0:8080")
JOBS_PATH = os.environ.get("JOBS_PATH", "/data/jobs.jsonl")
HOST, PORT = LISTEN.rsplit(":", 1)
PORT = int(PORT)
VERSION = "1.0.0"
FEATURES = ["compression", "bandwidth", "verify", "resume", "remote_dst"]

DEVICE_RE = re.compile(r"^/dev/[a-zA-Z0-9]+$")
HOST_RE   = re.compile(r"^[a-zA-Z0-9._-]+$")
USER_RE   = re.compile(r"^[a-zA-Z0-9._-]+$")

if not BACKEND_TOKEN:
    print("FATAL: BACKEND_TOKEN must be set", flush=True)
    raise SystemExit(1)

current_job = None
current_job_lock = threading.Lock()


def persist_job(job):
    try:
        os.makedirs(os.path.dirname(JOBS_PATH), exist_ok=True)
        with open(JOBS_PATH, "a") as f:
            f.write(json.dumps(job) + "\n")
    except Exception as exc:
        print("persist_job failed: {}".format(exc), flush=True)


def list_devices():
    try:
        out = subprocess.check_output(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MODEL,TRAN"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        )
        data = json.loads(out)
    except Exception as exc:
        return {"error": str(exc), "devices": [], "allowed_devices": ALLOWED_DEVICES}
    devices = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        devices.append({
            "path": "/dev/" + dev["name"],
            "size": int(dev.get("size") or 0),
            "model": (dev.get("model") or "").strip(),
            "tran": dev.get("tran") or "",
        })
    return {"devices": devices, "allowed_devices": ALLOWED_DEVICES}


def bytes_written(dev_path):
    name = os.path.basename(dev_path)
    try:
        with open("/sys/block/" + name + "/stat") as f:
            parts = f.read().split()
        return int(parts[6]) * 512
    except Exception:
        return None


def ssh_cmd(user, host, remote_shell):
    return ["ssh", "-o", "BatchMode=yes", "{}@{}".format(user, host), remote_shell]


def build_pipeline(req, skip_bytes, size):
    comp = req["options"].get("compression") or "none"
    tolerate = bool(req["options"].get("tolerate_errors"))
    bw = int(req["options"].get("bandwidth_limit_kbps") or 0)
    dst_host = req.get("dst_host") or ""

    skip_blocks = skip_bytes // (4 * 1024 * 1024)
    remote = "sudo dd if={} bs=4M status=none".format(req["target_device"])
    if skip_blocks > 0:
        remote += " skip={}".format(skip_blocks)
    if tolerate:
        remote += " conv=noerror,sync"
    comp_cmd = {
        "gzip": " | gzip -1", "pigz": " | pigz -1",
        "zstd": " | zstd -3 -T0", "lz4": " | lz4 -1",
    }.get(comp, "")
    remote += comp_cmd
    ssh_proc_cmd = ssh_cmd(req["target_user"], req["target_host"], remote)

    decompress_cmd = None
    if comp in ("gzip", "pigz", "zstd", "lz4"):
        dec = {"gzip": ["gzip", "-d"], "pigz": ["pigz", "-d"],
               "zstd": ["zstd", "-d"], "lz4": ["lz4", "-d"]}[comp]
        decompress_cmd = dec

    pv_cmd = None
    if bw > 0:
        remaining = size - skip_bytes
        pv_cmd = ["pv", "-q", "-L", "{}k".format(bw), "-s", str(remaining)]

    seek_blocks = skip_bytes // (4 * 1024 * 1024)
    if dst_host:
        writer_remote = "sudo dd of={} bs=4M conv=fsync status=none".format(req["dst_device"])
        if seek_blocks > 0:
            writer_remote += " seek={}".format(seek_blocks)
        writer_cmd = ssh_cmd(req.get("dst_user") or "root", dst_host, writer_remote)
    else:
        writer_cmd = ["dd", "of={}".format(req["dst_device"]), "bs=4M",
                      "conv=fsync", "status=none"]
        if seek_blocks > 0:
            writer_cmd += ["seek={}".format(seek_blocks)]

    human = "ssh {}@{} '{}'".format(req["target_user"], req["target_host"], remote)
    if decompress_cmd:
        human += " | " + " ".join(decompress_cmd)
    if pv_cmd:
        human += " | " + " ".join(pv_cmd)
    if dst_host:
        human += " | ssh {}@{} '{}'".format(req.get("dst_user") or "root", dst_host, writer_remote)
    else:
        human += " | " + " ".join(writer_cmd)
    return ssh_proc_cmd, decompress_cmd, pv_cmd, writer_cmd, human


def read_source_size(req):
    out = subprocess.check_output(
        ssh_cmd(req["target_user"], req["target_host"],
                "sudo blockdev --getsize64 {}".format(req["target_device"])),
        text=True, timeout=15, stderr=subprocess.PIPE,
    )
    return int(out.strip())


def run_verify(req, job, size):
    mode = req["options"].get("verify_mode") or "none"
    if mode == "none":
        return
    job["phase"] = "verifying"
    src_u = req["target_user"]; src_h = req["target_host"]; src_d = req["target_device"]
    dst_h = req.get("dst_host") or ""; dst_u = req.get("dst_user") or "root"; dst_d = req["dst_device"]

    def src_hash(shell):
        return subprocess.check_output(
            ssh_cmd(src_u, src_h, shell), text=True, timeout=3600, stderr=subprocess.PIPE,
        ).strip().split()[0]

    def dst_hash(shell):
        if dst_h:
            return subprocess.check_output(
                ssh_cmd(dst_u, dst_h, shell), text=True, timeout=3600, stderr=subprocess.PIPE,
            ).strip().split()[0]
        return subprocess.check_output(shell.split(), text=True, timeout=3600).strip().split()[0]

    try:
        if mode == "spot":
            skip_last = max(0, (size // 1048576) - 1)
            s_first = src_hash("sudo dd if={} bs=1M count=1 status=none | sha256sum".format(src_d))
            d_first = dst_hash("sudo dd if={} bs=1M count=1 status=none | sha256sum".format(dst_d))
            s_last  = src_hash("sudo dd if={} bs=1M skip={} count=1 status=none | sha256sum".format(src_d, skip_last))
            d_last  = dst_hash("sudo dd if={} bs=1M skip={} count=1 status=none | sha256sum".format(dst_d, skip_last))
            match = (s_first == d_first and s_last == d_last)
            job["verify"] = {"match": match, "detail":
                "first1MiB source={} dest={}\nlast1MiB  source={} dest={}".format(
                    s_first, d_first, s_last, d_last)}
        elif mode == "full":
            s = src_hash("sudo sha256sum {}".format(src_d))
            d = dst_hash("sudo sha256sum {}".format(dst_d))
            job["verify"] = {"match": s == d, "source_sha": s, "dest_sha": d}
    except Exception as exc:
        job["verify"] = {"match": False, "detail": "verify failed: {}".format(exc)}
    job["phase"] = "cloning"


def run_clone(job, req):
    try:
        size = read_source_size(req)
    except Exception as exc:
        job["status"] = "errored"
        job["error"] = "could not read source size: {}".format(exc)
        persist_job(job)
        return
    job["bytes_total"] = size
    skip = int(req["options"].get("resume_from_bytes") or 0)
    if skip > size:
        job["status"] = "errored"
        job["error"] = "resume_from_bytes ({}) > source size ({})".format(skip, size)
        persist_job(job)
        return

    ssh_proc_cmd, decompress_cmd, pv_cmd, writer_cmd, human = build_pipeline(req, skip, size)
    job["command"] = human

    ssh_proc = subprocess.Popen(ssh_proc_cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    stream = ssh_proc.stdout
    procs = [ssh_proc]

    if decompress_cmd:
        d = subprocess.Popen(decompress_cmd, stdin=stream, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        stream.close(); stream = d.stdout; procs.append(d)

    if pv_cmd:
        p = subprocess.Popen(pv_cmd, stdin=stream, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        stream.close(); stream = p.stdout; procs.append(p)

    writer = subprocess.Popen(writer_cmd, stdin=stream, stderr=subprocess.DEVNULL,
                              start_new_session=True)
    stream.close(); procs.append(writer)

    job["status"] = "running"
    while writer.poll() is None:
        if job.get("abort"):
            for p in procs:
                try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except Exception: pass
            time.sleep(1)
            for p in procs:
                try: os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception: pass
            for p in procs:
                try: p.wait(timeout=3)
                except Exception: pass
            job["status"] = "aborted"; job["finished_at"] = time.time()
            persist_job(job)
            return
        if not (req.get("dst_host") or ""):
            w = bytes_written(req["dst_device"])
            if w is not None:
                job["bytes_done"] = w
                job["percent"] = round(100.0 * (w - skip) / (size - skip), 2) if size > skip else 0.0
        time.sleep(1)

    rc = writer.returncode
    job["status"] = "done" if rc == 0 else "errored"
    if rc != 0:
        job["error"] = "writer exited rc={}".format(rc)
    if job["status"] == "done" and job.get("verify") is None:
        run_verify(req, job, size)
    job["finished_at"] = time.time()
    persist_job(job)


def validate_request(body, require_confirm):
    target_host = (body.get("target_host") or "").strip()
    target_user = (body.get("target_user") or "").strip() or "root"
    target_device = (body.get("target_device") or "").strip()
    dst_device = (body.get("dst_device") or "").strip()
    dst_host = (body.get("dst_host") or "").strip()
    dst_user = (body.get("dst_user") or "").strip() or "root"
    confirm = (body.get("confirm") or "").strip()
    options = body.get("options") or {}

    if not target_host or not target_device or not dst_device:
        return ("target_host, target_device, dst_device are required", None)
    if not HOST_RE.match(target_host):
        return ("target_host invalid", None)
    if not USER_RE.match(target_user):
        return ("target_user invalid", None)
    if not DEVICE_RE.match(target_device):
        return ("target_device must match ^/dev/[a-zA-Z0-9]+$", None)
    if not DEVICE_RE.match(dst_device):
        return ("dst_device must match ^/dev/[a-zA-Z0-9]+$", None)

    if dst_host:
        if not HOST_RE.match(dst_host):
            return ("dst_host invalid", None)
        if not USER_RE.match(dst_user):
            return ("dst_user invalid", None)
        expected_confirm = "{}@{}:{}".format(dst_user, dst_host, dst_device)
    else:
        if dst_device not in ALLOWED_DEVICES:
            return ("dst_device {} not in ALLOWED_LOCAL_DEVICES".format(dst_device), None)
        expected_confirm = dst_device

    if require_confirm and confirm != expected_confirm:
        return ("confirm must equal {}".format(expected_confirm), None)

    allowed_opts = {"compression", "bandwidth_limit_kbps", "resume_from_bytes",
                    "verify_mode", "tolerate_errors"}
    for k in options:
        if k not in allowed_opts:
            return ("unknown option: {}".format(k), None)
    if options.get("compression") not in (None, "none", "gzip", "pigz", "zstd", "lz4"):
        return ("compression must be one of none|gzip|pigz|zstd|lz4", None)
    if options.get("verify_mode") not in (None, "none", "spot", "full"):
        return ("verify_mode must be one of none|spot|full", None)

    return (None, {
        "target_host": target_host, "target_user": target_user,
        "target_device": target_device, "dst_device": dst_device,
        "dst_host": dst_host, "dst_user": dst_user,
        "options": options,
    })


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if self.headers.get("Authorization", "") == "Bearer " + BACKEND_TOKEN:
            return True
        q = urlparse(self.path).query
        return ("token=" + BACKEND_TOKEN) in q

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode()) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok", "version": VERSION, "features": FEATURES})
            return
        if not self._auth():
            self._send(401, {"error": "unauthorized"}); return
        if path == "/devices":
            self._send(200, list_devices()); return
        if path == "/status":
            with current_job_lock:
                j = dict(current_job) if current_job else None
            self._send(200, {"job": j}); return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._auth():
            self._send(401, {"error": "unauthorized"}); return
        try:
            body = self._read_json()
        except Exception as exc:
            self._send(400, {"error": "bad json: {}".format(exc)}); return

        if path == "/dryrun":
            err, req = validate_request(body, require_confirm=False)
            if err: self._send(400, {"error": err}); return
            try:
                size = read_source_size(req)
            except Exception as exc:
                self._send(502, {"error": "could not read source size: {}".format(exc)}); return
            skip = int(req["options"].get("resume_from_bytes") or 0)
            _, _, _, _, human = build_pipeline(req, skip, size)
            self._send(200, {"command": human, "bytes_total": size, "dry_run": True})
            return

        if path == "/clone":
            err, req = validate_request(body, require_confirm=True)
            if err: self._send(400, {"error": err}); return
            with current_job_lock:
                global current_job
                if current_job and current_job.get("status") in ("starting", "running", "verifying"):
                    self._send(409, {"error": "another job is running"}); return
                current_job = {
                    "status": "starting", "phase": "cloning",
                    "started_at": time.time(), "bytes_total": 0, "bytes_done": 0,
                    "percent": 0.0, "error": None, "command": None, "verify": None,
                }
                j = current_job
            threading.Thread(target=run_clone, args=(j, req), daemon=True).start()
            self._send(202, {"status": "started"})
            return

        if path == "/abort":
            with current_job_lock:
                j = current_job
            if not j or j.get("status") not in ("starting", "running"):
                self._send(409, {"error": "no running job"}); return
            j["abort"] = True
            self._send(200, {"status": "aborting"}); return

        self._send(404, {"error": "not found"})


def main():
    print("backend {} listening on {}:{}".format(VERSION, HOST, PORT), flush=True)
    print("features: {}".format(", ".join(FEATURES)), flush=True)
    print("allowed local devices: {}".format(ALLOWED_DEVICES or "(none - local writes refused)"), flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
