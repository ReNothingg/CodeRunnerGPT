import os
import re
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
MAX_IMAGES = int(os.getenv("MAX_IMAGES", "6"))
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

BASE_DIR = Path(__file__).parent.resolve()
RESULTS_DIR = BASE_DIR / "static" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_MD = (BASE_DIR / "prompt.md").read_text(encoding="utf-8")

app = Flask(__name__, static_folder="static", template_folder="templates")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL_ID)

CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.+?)\s*```", re.DOTALL | re.IGNORECASE)

def extract_code(md: str) -> str:
    m = CODE_BLOCK_RE.search(md)
    return m.group(1) if m else md.strip()

def cleanup_old_files():
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=IMAGE_RETENTION_DAYS)
            for p in RESULTS_DIR.iterdir():
                try:
                    if not p.is_dir():
                        continue
                    if datetime.utcfromtimestamp(p.stat().st_mtime) < cutoff:
                        for c in p.glob("**/*"):
                            try:
                                c.unlink(missing_ok=True)
                            except Exception:
                                pass
                        try:
                            p.rmdir()
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(3600)

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

def run_in_sandbox(job_dir: Path, code_path: Path, timeout_sec=30):
    if USE_DOCKER:
        cmd = [
            "docker","run","--rm",
            "--network=none",
            "--cpus=1",
            "--memory=1024m",
            "--pids-limit=128",
            "--read-only",
            "--tmpfs","/tmp:rw,size=64m",
            "--cap-drop=ALL",
            "--security-opt","no-new-privileges",
            "-v",f"{str(job_dir)}:/work:rw",
            "-w","/work",
            DOCKER_IMAGE,
            "python","-u","/runner/sandbox_runner.py",
            "--code",f"/work/{code_path.name}",
            "--time","10",
            "--mem","1024",
            "--fsize","20",
            "--max-images",str(MAX_IMAGES),
            "--output-base","output",
        ]
    else:
        cmd = [
            "python","-u",str(BASE_DIR / "sandbox" / "sandbox_runner.py"),
            "--code",str(code_path),
            "--time","10",
            "--mem","1024",
            "--fsize","20",
            "--max-images",str(MAX_IMAGES),
            "--output-base","output",
        ]
    proc = subprocess.run(cmd, cwd=job_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def list_images(job_dir: Path):
    items = []
    for p in job_dir.glob("output_*.png"):
        items.append(p)
    items.sort(key=lambda q: int(re.search(r"output_(\d+)\.png$", q.name).group(1)) if re.search(r"output_(\d+)\.png$", q.name) else 0)
    return items

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
    stdout_file = job_dir / "stdout.txt"
    stderr_file = job_dir / "stderr.txt"
    full_prompt = f"{PROMPT_MD}\n\nЗапрос:\n{user_prompt}\n"
    try:
        resp = model.generate_content(full_prompt, generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_TOKENS})
        text = resp.text or ""
        code = extract_code(text)
    except Exception as e:
        return jsonify({"error": f"Gemini API error: {e}"}), 500
    code_file.write_text(code, encoding="utf-8")
    try:
        rc, out, err = run_in_sandbox(job_dir, code_file, timeout_sec=30)
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "Timeout: execution exceeded limit"
    (job_dir / "stdout.txt").write_text(out or "", encoding="utf-8")
    (job_dir / "stderr.txt").write_text(err or "", encoding="utf-8")
    imgs = [f"/results/{job_id}/{p.name}" for p in list_images(job_dir)]
    result = {
        "job_id": job_id,
        "code_url": f"/results/{job_id}/{code_file.name}",
        "stdout_url": f"/results/{job_id}/{stdout_file.name}",
        "stderr_url": f"/results/{job_id}/{stderr_file.name}",
        "image_urls": imgs if imgs else ["/static/placeholder.svg"],
        "return_code": rc,
    }
    return jsonify(result)

@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.get_json(force=True, silent=True) or {}
    code_text = (data.get("code") or "").strip()
    if not code_text:
        return jsonify({"error": "Вставьте код"}), 400
    job_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    code_file = job_dir / "user_code.py"
    stdout_file = job_dir / "stdout.txt"
    stderr_file = job_dir / "stderr.txt"
    code_file.write_text(code_text, encoding="utf-8")
    try:
        rc, out, err = run_in_sandbox(job_dir, code_file, timeout_sec=30)
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "Timeout: execution exceeded limit"
    (job_dir / "stdout.txt").write_text(out or "", encoding="utf-8")
    (job_dir / "stderr.txt").write_text(err or "", encoding="utf-8")
    imgs = [f"/results/{job_id}/{p.name}" for p in list_images(job_dir)]
    result = {
        "job_id": job_id,
        "code_url": f"/results/{job_id}/{code_file.name}",
        "stdout_url": f"/results/{job_id}/{stdout_file.name}",
        "stderr_url": f"/results/{job_id}/{stderr_file.name}",
        "image_urls": imgs if imgs else ["/static/placeholder.svg"],
        "return_code": rc,
    }
    return jsonify(result)

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)