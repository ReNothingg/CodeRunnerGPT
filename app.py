# app.py
import os, tempfile, shutil, subprocess, base64, uuid, time
from flask import Flask, render_template, request, jsonify, send_from_directory
from threading import Thread
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

UPLOAD_FOLDER = Path('static/uploads')
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '5'))
RUNNER_IMAGE = os.environ.get('RUNNER_IMAGE', 'remind-runner')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

# Background cleaner

def cleaner_worker():
    while True:
        now = time.time()
        cutoff = now - RETENTION_DAYS * 24 * 3600
        for p in UPLOAD_FOLDER.iterdir():
            try:
                if p.is_file():
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
            except Exception:
                pass
        time.sleep(24 * 3600)  # run once per day

Thread(target=cleaner_worker, daemon=True).start()

# Helper: placeholder Gemini call (user must set up their own API)
def generate_code_with_gemini(prompt_text):
    # === PLACEHOLDER ===
    # In production you should call Google's Gemini API (or another LLM)
    # securely with authentication. Here we simulate the response by
    # returning a safe, simple python script.
    safe_script = r"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
x = np.linspace(0, 10, 400)
y = np.sqrt(x)
plt.figure(figsize=(6,4))
plt.plot(x, y)
plt.title('y = sqrt(x)')
plt.grid(True)
plt.savefig('/workspace/output/plot.png', dpi=300, bbox_inches='tight')
print('OK: created plot')
"""
    return safe_script

@app.route('/')
def index():
    images = sorted(UPLOAD_FOLDER.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    images = [p.name for p in images if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.svg')]
    return render_template('index.html', images=images, retention_days=RETENTION_DAYS)

@app.route('/api/generate', methods=['POST'])
def api_generate():
    # read prompt.md
    with open('prompt.md', 'r', encoding='utf-8') as f:
        prompt_text = f.read()

    # ask Gemini (placeholder)
    code = generate_code_with_gemini(prompt_text)

    job_id = str(uuid.uuid4())[:8]
    tmpdir = tempfile.mkdtemp(prefix=f'run_{job_id}_')
    code_dir = Path(tmpdir) / 'code'
    output_dir = Path(tmpdir) / 'output'
    code_dir.mkdir()
    output_dir.mkdir()

    # write user_code.py
    with open(code_dir / 'user_code.py', 'w', encoding='utf-8') as f:
        f.write(code)

    # run docker runner
    try:
        cmd = [
            'docker', 'run', '--rm',
            '--network', 'none',
            '--memory', '512m',
            '--cpus', '1.0',
            '-v', f"{tmpdir}:/workspace",
            RUNNER_IMAGE
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'error': 'execution timeout'}), 504
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

    # read outputs
    stdout = ''
    stderr = ''
    try:
        with open(output_dir / 'stdout.txt', 'r', encoding='utf-8') as f:
            stdout = f.read()
    except:
        pass
    try:
        with open(output_dir / 'stderr.txt', 'r', encoding='utf-8') as f:
            stderr = f.read()
    except:
        pass

    # move plot.png to uploads
    saved_name = None
    for candidate in ['plot.png', 'plot.jpg', 'plot.jpeg', 'plot.svg']:
        src = output_dir / candidate
        if src.exists():
            ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            dest_name = f"{ts}_{job_id}_{candidate}"
            dest = UPLOAD_FOLDER / dest_name
            shutil.move(str(src), str(dest))
            saved_name = dest_name
            break

    # cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

    return jsonify({'stdout': stdout, 'stderr': stderr, 'image': saved_name})

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)