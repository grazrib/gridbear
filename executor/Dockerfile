FROM python:3.12-slim

# Create non-root user with UID 1000
# Note: docker group GID varies by host, handled via docker-compose
RUN groupadd -g 1000 gridbear && \
    useradd -u 1000 -g gridbear -m -s /bin/bash gridbear

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Create data directory for audit and set ownership
RUN mkdir -p /app/data/audit && \
    chown -R gridbear:gridbear /app

# Switch to non-root user
USER gridbear

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
