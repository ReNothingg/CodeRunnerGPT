import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory
import google.generativeai as genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_ID = os.getenv("MODEL_ID", "gemini-1.5-flash")
IMAGE_RETENTION_DAYS = int(os.getenv("IMAGE_RETENTION_DAYS", "5"))
USE_DOCKER = os.getenv("USE_DOCKER", "true").lower() == "true"
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "python-sandbox:latest")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

BASE_DIR = Path(__file__).parent.resolve()
RESULTS_DIR = BASE_DIR / "static" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_MD = (BASE_DIR / "prompt.md").read_text(encoding="utf-8")

app = Flask(__name__, static_folder="static", template_folder="templates")

# Configure Gemini
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is not set")
else:
    genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL_ID)

CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.+?)\s*```", re.DOTALL | re.IGNORECASE)

def extract_code(md: str) -> str:
    m = CODE_BLOCK_RE.search(md)
    if m:
        return m.group(1)
    return md.strip()

def cleanup_old_files():
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=IMAGE_RETENTION_DAYS)
            count = 0
            for p in RESULTS_DIR.iterdir():
                try:
                    if not p.is_dir():
                        continue
                    ts = datetime.utcfromtimestamp(p.stat().st_mtime)
                    if ts < cutoff:
                        for child in p.glob("**/*"):
                            try:
                                child.unlink(missing_ok=True)
                            except Exception:
                                pass
                        try:
                            p.rmdir()
                        except Exception:
                            pass
                        count += 1
                except Exception:
                    continue
            if count:
                print(f"[cleanup] removed {count} old jobs")
        except Exception as e:
            print(f"[cleanup] error: {e}")
        time.sleep(3600)  # hourly

threading.Thread(target=cleanup_old_files, daemon=True).start()

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/results/<job_id>/<path:filename>")
def results(job_id, filename):
    directory = RESULTS_DIR / job_id
    return send_from_directory(directory, filename, as_attachment=False)

def run_in_sandbox(job_dir: Path, code_path: Path, output_path: Path, timeout_sec=20):
    # Returns (exit_code, stdout, stderr)
    if USE_DOCKER:
        # Ensure runner is present in image. We rely on it being COPY'ed during build.
        cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--cpus=1",
            "--memory=1024m",
            "--pids-limit=128",
            "--read-only",
            "--tmpfs", " /tmp:rw,size=64m",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{str(job_dir)}:/work:rw",
            "-w", "/work",
            DOCKER_IMAGE,
            "python", "-u", "/runner/sandbox_runner.py",
            "--code", f"/work/{code_path.name}",
            "--output", f"/work/{output_path.name}",
            "--time", "10",
            "--mem", "1024",
            "--fsize", "20",
        ]
    else:
        # Fallback: run locally (less isolated). For development only.
        cmd = [
            "python", "-u", str(BASE_DIR / "sandbox_runner.py"),
            "--code", str(code_path),
            "--output", str(output_path),
            "--time", "10",
            "--mem", "1024",
            "--fsize", "20",
        ]

    proc = subprocess.run(
        cmd,
        cwd=job_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_sec,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True, silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip()
    if not user_prompt:
        return jsonify({"error": "Введите описание задачи"}), 400

    job_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    code_file = job_dir / "user_code.py"
    img_file = job_dir / "output.png"
    stdout_file = job_dir / "stdout.txt"
    stderr_file = job_dir / "stderr.txt"

    # Compose prompt
    full_prompt = f"{PROMPT_MD}\n\nUser request:\n{user_prompt}\n"

    # Call Gemini
    try:
        resp = model.generate_content(
            full_prompt,
            generation_config={
                "temperature": TEMPERATURE,
                "max_output_tokens": MAX_TOKENS,
            },
        )
        text = resp.text or ""
        code = extract_code(text)
    except Exception as e:
        return jsonify({"error": f"Gemini API error: {e}"}), 500

    # Save code
    code_file.write_text(code, encoding="utf-8")

    # Execute in sandbox
    try:
        rc, out, err = run_in_sandbox(job_dir, code_file, img_file, timeout_sec=30)
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "Timeout: execution exceeded limit"

    # Persist logs
    stdout_file.write_text(out or "", encoding="utf-8")
    stderr_file.write_text(err or "", encoding="utf-8")

    result = {
        "job_id": job_id,
        "code_url": f"/results/{job_id}/{code_file.name}",
        "stdout_url": f"/results/{job_id}/{stdout_file.name}",
        "stderr_url": f"/results/{job_id}/{stderr_file.name}",
        "image_url": f"/results/{job_id}/{img_file.name}" if img_file.exists() else "/static/placeholder.svg",
        "return_code": rc,
    }
    return jsonify(result)

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)