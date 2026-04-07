FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY scripts/ ./scripts/

# Run as non-root for security
RUN useradd --no-create-home --shell /bin/false botuser
USER botuser

# Set PYTHONPATH so src/ imports resolve correctly
ENV PYTHONPATH=/app/src

CMD ["python", "src/main.py"]
