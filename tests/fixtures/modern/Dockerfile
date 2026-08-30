# syntax=docker/dockerfile:1
ARG PY=3.12
FROM python:${PY}-slim AS deps
WORKDIR /app
COPY requirements.txt .
# BuildKit cache mount - extremely common in modern Dockerfiles, and it
# interacts with layer caching in ways worth checking.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

FROM python:${PY}-slim AS final
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY src ./src
CMD ["python", "src/app.py"]
