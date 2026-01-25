#!/bin/bash
# Build TPC-C Schema Script
# Creates the TPC-C schema and loads test data into PostgreSQL

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
PG_WAREHOUSE_COUNT="${PG_WAREHOUSE_COUNT:-10}"
PG_BUILD_USERS="${PG_BUILD_USERS:-4}"
PG_USE_STORED_PROCS="${PG_USE_STORED_PROCS:-true}"

# Check for HammerDB installation
HAMMERDB_DIR="${BASE_DIR}/hammerdb"
if [ ! -d "$HAMMERDB_DIR" ]; then
    echo "Error: HammerDB not found at ${HAMMERDB_DIR}"
    echo "Please run ./scripts/install.sh first."
    exit 1
fi

echo "=== TPC-C Schema Build ==="
echo "Host: ${PG_HOST}:${PG_PORT}"
echo "Database: ${PG_DATABASE}"
echo "User: ${PG_USER}"
echo "Warehouses: ${PG_WAREHOUSE_COUNT}"
echo "Build Users: ${PG_BUILD_USERS}"
echo "Use Stored Procedures: ${PG_USE_STORED_PROCS}"
echo ""

# Generate Tcl build script
BUILD_TCL="${BASE_DIR}/tcl/pg_build_generated.tcl"

cat > "$BUILD_TCL" << EOF
#!/bin/tclsh
# Auto-generated HammerDB TPC-C schema build script

puts "Setting PostgreSQL connection parameters..."
dbset db pg
dbset bm TPC-C

# Connection settings
diset connection pg_host ${PG_HOST}
diset connection pg_port ${PG_PORT}

# TPC-C settings
diset tpcc pg_superuser ${PG_SUPERUSER:-$PG_USER}
diset tpcc pg_superuserpass ${PG_SUPERUSER_PASSWORD:-$PG_PASSWORD}
diset tpcc pg_defaultdbase postgres
diset tpcc pg_user ${PG_USER}
diset tpcc pg_pass ${PG_PASSWORD}
diset tpcc pg_dbase ${PG_DATABASE}

# Schema settings
diset tpcc pg_count_ware ${PG_WAREHOUSE_COUNT}
diset tpcc pg_num_vu ${PG_BUILD_USERS}
diset tpcc pg_storedprocs ${PG_USE_STORED_PROCS}

# Build schema
puts "Starting schema build with ${PG_WAREHOUSE_COUNT} warehouses..."
puts "This may take a while depending on the warehouse count."

buildschema
puts "Schema build complete!"

# Wait for virtual users to complete
vwait forever
EOF

echo "Running HammerDB schema build..."
cd "$HAMMERDB_DIR"
./hammerdbcli auto "${BUILD_TCL}"

echo ""
echo "=== Schema Build Complete ==="
