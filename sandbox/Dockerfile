FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libopenblas0 libjpeg62-turbo libpng16-16 libfreetype6 fonts-dejavu-core tini && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==1.26.4 matplotlib==3.8.4 pandas==2.2.2 pillow==10.4.0
RUN useradd -m -u 10001 sandbox
USER sandbox
WORKDIR /runner
COPY sandbox_runner.py /runner/sandbox_runner.py
ENV MPLCONFIGDIR=/tmp/mpl OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=UTF-8
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python","-V"]