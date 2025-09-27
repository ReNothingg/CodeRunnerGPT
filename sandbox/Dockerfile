FROM python:3.11-slim

# System deps for numpy/matplotlib/pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
   libopenblas0 \
   libjpeg62-turbo \
   libpng16-16 \
   libfreetype6 \
   fonts-dejavu-core \
   tini \
   && rm -rf /var/lib/apt/lists/*

# Python libs (only allowed)
RUN pip install --no-cache-dir numpy==1.26.4 matplotlib==3.8.4 pandas==2.2.2 pillow==10.4.0

# Non-root user
RUN useradd -m -u 10001 sandbox
USER sandbox

# Runner files
WORKDIR /runner
# sandbox_runner.py будет скопирован при сборке из корня проекта
# (см. инструкцию в разделе "Запуск")
# После копирования runner можно вызывать как: python -u /runner/sandbox_runner.py

# Runtime env
ENV MPLCONFIGDIR=/tmp/mpl \
   OPENBLAS_NUM_THREADS=1 \
   OMP_NUM_THREADS=1 \
   MKL_NUM_THREADS=1 \
   NUMEXPR_MAX_THREADS=1 \
   PYTHONDONTWRITEBYTECODE=1 \
   PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-V"]