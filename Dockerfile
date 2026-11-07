FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip setuptools wheel jaraco.context && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pre-commit virtualenv pip && \
    rm -rf /usr/local/lib/python3.11/ensurepip

COPY src/ src/

# Create a volume mount point for state
RUN mkdir -p /app/data

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src"]
