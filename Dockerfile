# The LiveKit agent runs as a worker: it dials out to LiveKit Cloud and waits
# for rooms. It serves no inbound traffic, so it needs no port and no domain.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv
WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY app ./app
COPY scripts ./scripts

# Downloads the turn-detection and VAD weights at build time rather than on the
# first call, so the first interview of the day is not the slow one.
RUN python -m app.agent download-files || true

CMD ["python", "-m", "app.agent", "start"]
