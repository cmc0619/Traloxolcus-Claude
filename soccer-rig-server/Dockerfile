# Soccer Rig Viewer Server
# Multi-stage build with nginx + SSL support

FROM python:3.11-slim as builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
FROM python:3.11-slim

# Install nginx, certbot, and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    certbot \
    python3-certbot-nginx \
    ffmpeg \
    openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python dependencies
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY . .

# Create directories
RUN mkdir -p /app/storage /etc/letsencrypt /var/log/nginx

# Copy nginx config
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
