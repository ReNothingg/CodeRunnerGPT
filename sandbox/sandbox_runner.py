import argparse
import os
import resource
import signal
import sys
import time
from pathlib import Path

def set_limits(cpu_seconds: int, mem_mb: int, fsize_mb: int):
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_mb * 1024 * 1024, fsize_mb * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def disable_network():
    try:
        import socket
        class _NoNet:
            def __init__(self, *a, **k):
                raise RuntimeError("Network is disabled")
        socket.socket = _NoNet
        socket.create_connection = _NoNet
    except Exception:
        pass

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--code", required=True)
    p.add_argument("--time", type=int, default=10)
    p.add_argument("--mem", type=int, default=1024)
    p.add_argument("--fsize", type=int, default=20)
    p.add_argument("--max-images", type=int, default=8)
    p.add_argument("--output-base", default="output")
    args = p.parse_args()
    code_path = Path(args.code)
    workdir = code_path.parent
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_MAX_THREADS", "1")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl")
    os.environ.setdefault("HOME", str(workdir))
    set_limits(cpu_seconds=args.time, mem_mb=args.mem, fsize_mb=args.fsize)
    signal.signal(signal.SIGXCPU, lambda *_, **__: sys.exit(124))
    disable_network()
    saved = 0
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        def _save_all():
            nonlocal saved
            fnums = plt.get_fignums()
            for _ in fnums:
                if saved >= args.max_images:
                    break
                saved += 1
                name = f"{args.output_base}_{saved}.png"
                fig = plt.figure(_)
                fig.savefig(name, dpi=150, bbox_inches="tight")
        def _show(*a, **k):
            _save_all()
            plt.close("all")
        plt.show = _show
    except Exception:
        pass
    g = {}
    l = {}
    if not code_path.is_file():
        print("Code file not found", file=sys.stderr)
        sys.exit(2)
    code_text = code_path.read_text(encoding="utf-8", errors="ignore")
    start = time.time()
    try:
        compiled = compile(code_text, filename=str(code_path.name), mode="exec")
        exec(compiled, g, l)
    except SystemExit as e:
        print(f"Script exited with code {e.code}", file=sys.stderr)
        sys.exit(int(e.code) if isinstance(e.code, int) else 1)
    except BaseException as e:
        print(f"Runtime error: {e.__class__.__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            import matplotlib.pyplot as plt
            f = plt.get_fignums()
            if f:
                try:
                    _ = plt.show
                    _()
                except Exception:
                    pass
        except Exception:
            pass
        dur = time.time() - start
        print(f"[sandbox] elapsed: {dur:.3f}s", file=sys.stderr)
    sys.exit(0)

if __name__ == "__main__":
    main()