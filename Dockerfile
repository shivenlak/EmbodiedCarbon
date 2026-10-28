# One image serving the interface and the API from the same origin.
#
# A full upload -> takeoff -> carbon -> trace cycle loads only pymupdf and
# numpy, so ifcopenshell (163 MB) and pandas (79 MB) are deliberately absent:
# they belong to ecarbon/bench and scripts/, which score the pipeline against
# the IFC models and never run here. That keeps the image small enough to
# deploy quickly and to redeploy during a demo.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build


FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EC_DATA=/data/cmhc

WORKDIR /app

# Only what the service needs at runtime. Pinned to the same majors the
# project develops against; the test and benchmark extras are not installed.
RUN pip install --no-cache-dir \
      "pymupdf>=1.24" \
      "pydantic>=2.7" \
      "fastapi>=0.115" \
      "uvicorn[standard]>=0.30" \
      "python-multipart>=0.0.9"

COPY ecarbon/ ./ecarbon/
COPY --from=web /web/dist ./web/dist

# Plan sets, staged by deploy/stage_data.py, together with the takeoffs
# prebuilt by deploy/prebuild.py. Licence-restricted, which is why they are
# baked in here rather than committed: this image is deployed behind
# credentials, the repository is public.
#
# The prebuilt takeoffs are what make the first request fast. Parsing a set
# costs 23 s on a shared core, 177 s for the largest, and the only cache is in
# memory -- so without these, the first visitor after every restart pays for
# the parse. With them the same request is served in under half a second.
COPY deploy/data/ /data/cmhc/

EXPOSE 8080
# One worker: each request holds a parsed document and peaks around 540 MB on
# a 46-page set, so concurrency is bounded by memory rather than CPU.
CMD ["uvicorn", "ecarbon.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
