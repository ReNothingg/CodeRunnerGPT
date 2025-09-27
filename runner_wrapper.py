import sys, os, traceback, runpy, io, signal
from contextlib import redirect_stdout, redirect_stderr

TIMEOUT = int(os.environ.get('RUNNER_TIMEOUT', '12'))

def timeout_handler(signum, frame):
    raise TimeoutError('Time limit reached')

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(TIMEOUT)

out_buf = io.StringIO()
err_buf = io.StringIO()

try:
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        runpy.run_path('/workspace/code/user_code.py', run_name='__main__')
except Exception as e:
    err_buf.write('\n' + ''.join(traceback.format_exception_only(type(e), e)))
finally:
    signal.alarm(0)
    os.makedirs('/workspace/output', exist_ok=True)
    with open('/workspace/output/stdout.txt', 'w', encoding='utf-8') as f:
        f.write(out_buf.getvalue())
    with open('/workspace/output/stderr.txt', 'w', encoding='utf-8') as f:
        f.write(err_buf.getvalue())