#!/bin/bash
set -e

SSL_DIR="/etc/nginx/ssl"
CERTBOT_DIR="/var/www/certbot"

mkdir -p "$SSL_DIR" "$CERTBOT_DIR"

# =============================================================================
# SSL Certificate Setup
# =============================================================================
setup_ssl() {
    if [ "$SSL_MODE" = "letsencrypt" ] && [ -n "$DOMAIN" ] && [ "$DOMAIN" != "localhost" ]; then
        echo "==> Setting up Let's Encrypt for $DOMAIN"

        # Check if cert already exists
        if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
            echo "==> Using existing Let's Encrypt certificate"
            ln -sf "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$SSL_DIR/cert.pem"
            ln -sf "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$SSL_DIR/key.pem"
        else
            echo "==> Generating temporary self-signed cert for initial nginx startup"
            generate_self_signed

            # Start nginx temporarily for ACME challenge
            nginx &
            sleep 2

            echo "==> Requesting Let's Encrypt certificate"
            certbot certonly --nginx -d "$DOMAIN" --non-interactive --agree-tos \
                --email "${ADMIN_EMAIL:-admin@$DOMAIN}" \
                --redirect

            # Stop temporary nginx
            nginx -s stop
            sleep 1

            # Link the new certs
            ln -sf "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$SSL_DIR/cert.pem"
            ln -sf "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$SSL_DIR/key.pem"
        fi

        # Set up auto-renewal cron
        echo "0 0 * * * certbot renew --quiet" | crontab -
    else
        echo "==> Using self-signed certificate"
        generate_self_signed
    fi
}

generate_self_signed() {
    if [ ! -f "$SSL_DIR/cert.pem" ]; then
        echo "==> Generating self-signed SSL certificate"
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$SSL_DIR/key.pem" \
            -out "$SSL_DIR/cert.pem" \
            -subj "/C=US/ST=State/L=City/O=SoccerRig/CN=${DOMAIN:-localhost}"
    fi
}

# =============================================================================
# Database Migration
# =============================================================================
run_migrations() {
    echo "==> Waiting for database..."
    MAX_RETRIES=60  # 60 seconds timeout
    RETRY_COUNT=0
    while ! python -c "from sqlalchemy import create_engine; e = create_engine('$DATABASE_URL'); e.connect()" 2>/dev/null; do
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
            echo "ERROR: Database not available after ${MAX_RETRIES} seconds"
            exit 1
        fi
        sleep 1
    done
    echo "==> Database ready"

    # Run Alembic migrations if available
    if [ -f "alembic.ini" ]; then
        echo "==> Running database migrations"
        alembic upgrade head
    fi
}

# =============================================================================
# Main
# =============================================================================
echo "=========================================="
echo "Soccer Rig Viewer Server"
echo "=========================================="

setup_ssl
run_migrations

echo "==> Starting nginx"
nginx

echo "==> Starting Flask application"
exec gunicorn --bind 127.0.0.1:5000 \
    --workers 4 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app()"
