#!/bin/bash
# Test PostgreSQL Connection Script
# Verifies that PostgreSQL is accessible with the configured credentials

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Load configuration
CONFIG_FILE="${BASE_DIR}/config/pg_config.env"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE"
    echo "Please copy config/pg_config.env.example to config/pg_config.env and edit it."
    exit 1
fi
source "$CONFIG_FILE"

# Set defaults
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"
PG_DATABASE="${PG_DATABASE:-tpcc}"

echo "=== PostgreSQL Connection Test ==="
echo "Host: ${PG_HOST}"
echo "Port: ${PG_PORT}"
echo "User: ${PG_USER}"
echo "Database: ${PG_DATABASE}"
echo ""

# Test 1: Check if pg_isready is available and server is up
echo "Test 1: Checking server availability..."
if command -v pg_isready &> /dev/null; then
    if pg_isready -h "${PG_HOST}" -p "${PG_PORT}" -q; then
        echo "  [PASS] PostgreSQL server is accepting connections"
    else
        echo "  [FAIL] PostgreSQL server is not responding"
        exit 1
    fi
else
    echo "  [SKIP] pg_isready not found, skipping server check"
fi

# Test 2: Test authentication
echo "Test 2: Testing authentication..."
if PGPASSWORD="${PG_PASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -c "SELECT 1;" &> /dev/null; then
    echo "  [PASS] Authentication successful"
else
    echo "  [FAIL] Authentication failed"
    echo "  Check your username and password in config/pg_config.env"
    exit 1
fi

# Test 3: Check if target database exists
echo "Test 3: Checking if database '${PG_DATABASE}' exists..."
DB_EXISTS=$(PGPASSWORD="${PG_PASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${PG_DATABASE}'")
if [ "$DB_EXISTS" = "1" ]; then
    echo "  [INFO] Database '${PG_DATABASE}' exists"

    # Check for TPC-C tables
    echo "Test 4: Checking for TPC-C schema..."
    TABLE_COUNT=$(PGPASSWORD="${PG_PASSWORD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DATABASE}" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('warehouse', 'district', 'customer', 'history', 'orders', 'new_order', 'order_line', 'stock', 'item')")
    if [ "$TABLE_COUNT" = "9" ]; then
        echo "  [INFO] TPC-C schema is present (all 9 tables found)"
    elif [ "$TABLE_COUNT" = "0" ]; then
        echo "  [INFO] TPC-C schema not yet created"
        echo "  Run ./scripts/build_schema.sh to create it"
    else
        echo "  [WARN] Partial TPC-C schema found (${TABLE_COUNT}/9 tables)"
    fi
else
    echo "  [INFO] Database '${PG_DATABASE}' does not exist"
    echo "  It will be created when you run ./scripts/build_schema.sh"
fi

echo ""
echo "=== Connection Test Complete ==="
echo "Your PostgreSQL connection is properly configured."
