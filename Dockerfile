FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for ZeroMQ
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install RIS-SIM
COPY pyproject.toml .
COPY ris_sim/ ris_sim/
RUN pip install --no-cache-dir -e .

# Default entry point
ENTRYPOINT ["python", "-m", "ris_sim.cli.main"]

# Default command: show help
CMD ["--help"]
