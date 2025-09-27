import argparse
import os
import resource
import signal
import sys
import time
from pathlib import Path

def set_limits(cpu_seconds: int, mem_mb: int, fsize_mb: int):
    # CPU time
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # Virtual memory/address space
    mem_bytes = mem_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    # File size
    fsize_bytes = fsize_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
    # Processes
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    # Open files
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    # Core dumps off
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def disable_network():
    # Best-effort: disable socket creation inside Python.
    # (В контейнере и так --network=none; это дополнительная защита.)
    try:
        import socket  # noqa
        class _NoNetSocket:
            def __init__(self, *a, **kw):
                raise RuntimeError("Network is disabled in this sandbox")
        socket.socket = _NoNetSocket  # type: ignore
        socket.create_connection = _NoNetSocket  # type: ignore
    except Exception:
        pass

def configure_matplotlib():
    # Force non-GUI backend
    import matplotlib
    matplotlib.use("Agg")  # must be before importing pyplot
    import matplotlib.pyplot as plt  # noqa
    return plt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="Path to user code (python)")
    parser.add_argument("--output", required=True, help="Path to output image")
    parser.add_argument("--time", type=int, default=10, help="CPU seconds limit")
    parser.add_argument("--mem", type=int, default=1024, help="Memory MB")
    parser.add_argument("--fsize", type=int, default=20, help="Max file size MB")
    args = parser.parse_args()

    # Working dir = output dir
    workdir = Path(args.output).parent
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)

    # Env: limit BLAS threads, isolated tmp, matplotlib cache path
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_MAX_THREADS", "1")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl")
    os.environ.setdefault("HOME", str(workdir))

    # Apply resource limits
    set_limits(cpu_seconds=args.time, mem_mb=args.mem, fsize_mb=args.fsize)

    # Kill on SIGXCPU
    signal.signal(signal.SIGXCPU, lambda *_, **__: sys.exit(124))

    # Extra safety
    disable_network()
    # Prepare matplotlib backend (no-op if not used)
    try:
        configure_matplotlib()
    except Exception:
        pass

    # Provide OUTPUT_IMAGE in globals
    g = {"OUTPUT_IMAGE": str(Path(args.output).name)}
    l = {}

    code_path = Path(args.code)
    if not code_path.is_file():
        print("Code file not found", file=sys.stderr)
        sys.exit(2)

    # Read and execute user code
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
        duration = time.time() - start
        print(f"[sandbox] elapsed: {duration:.3f}s", file=sys.stderr)

    # Done
    sys.exit(0)

if __name__ == "__main__":
    main()