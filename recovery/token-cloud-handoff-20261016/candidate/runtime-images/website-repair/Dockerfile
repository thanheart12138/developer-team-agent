FROM mcr.microsoft.com/playwright/python:v1.55.0-noble@sha256:640d578aae63cfb632461d1b0aecb01414e4e020864ac3dd45a868dc0eff3078

RUN python -m pip install --no-cache-dir playwright==1.55.0 && \
    python -c "import pathlib,playwright; pathlib.Path('/usr/local/bin/node').symlink_to(pathlib.Path(playwright.__file__).parent/'driver/node')" && \
    node --version && python -m pip show playwright

COPY controller.py /opt/repair/controller.py
ENV PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
USER 1000:1000
WORKDIR /product
ENTRYPOINT ["python", "/opt/repair/controller.py"]
