#!/bin/bash
# Cleanup Script
# Drops the TPC-C schema from PostgreSQL

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Load configuration
CONFIG_FILE="${BASE_DIR}/config/pg_config.env"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE"
    exit 1
fi
source "$CONFIG_FILE"

# Set defaults
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"
PG_DATABASE="${PG_DATABASE:-tpcc}"

echo "=== TPC-C Schema Cleanup ==="
echo "This will DROP the database: ${PG_DATABASE}"
echo ""

read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "Dropping database ${PG_DATABASE}..."

PGPASSWORD="${PG_PASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres << EOF
DROP DATABASE IF EXISTS ${PG_DATABASE};
EOF

echo "Database ${PG_DATABASE} dropped."
echo ""
echo "=== Cleanup Complete ==="
