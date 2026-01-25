#!/bin/bash
# Run TPC-C Benchmark Script
# Executes the TPC-C benchmark against PostgreSQL

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
PG_VIRTUAL_USERS="${PG_VIRTUAL_USERS:-4}"
PG_RAMPUP_MINUTES="${PG_RAMPUP_MINUTES:-2}"
PG_DURATION_MINUTES="${PG_DURATION_MINUTES:-5}"
PG_USE_STORED_PROCS="${PG_USE_STORED_PROCS:-true}"

# Check for HammerDB installation
HAMMERDB_DIR="${BASE_DIR}/hammerdb"
if [ ! -d "$HAMMERDB_DIR" ]; then
    echo "Error: HammerDB not found at ${HAMMERDB_DIR}"
    echo "Please run ./scripts/install.sh first."
    exit 1
fi

# Create results directory
RESULTS_DIR="${BASE_DIR}/results"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RESULT_FILE="${RESULTS_DIR}/benchmark_${TIMESTAMP}.log"

echo "=== TPC-C Benchmark ==="
echo "Host: ${PG_HOST}:${PG_PORT}"
echo "Database: ${PG_DATABASE}"
echo "Virtual Users: ${PG_VIRTUAL_USERS}"
echo "Ramp-up: ${PG_RAMPUP_MINUTES} minutes"
echo "Duration: ${PG_DURATION_MINUTES} minutes"
echo "Results: ${RESULT_FILE}"
echo ""

# Generate Tcl run script
RUN_TCL="${BASE_DIR}/tcl/pg_run_generated.tcl"

cat > "$RUN_TCL" << EOF
#!/bin/tclsh
# Auto-generated HammerDB TPC-C benchmark script

puts "Configuring PostgreSQL benchmark..."
dbset db pg
dbset bm TPC-C

# Connection settings
diset connection pg_host ${PG_HOST}
diset connection pg_port ${PG_PORT}

# TPC-C driver settings
diset tpcc pg_driver timed
diset tpcc pg_user ${PG_USER}
diset tpcc pg_pass ${PG_PASSWORD}
diset tpcc pg_dbase ${PG_DATABASE}
diset tpcc pg_count_ware ${PG_WAREHOUSE_COUNT}
diset tpcc pg_storedprocs ${PG_USE_STORED_PROCS}
diset tpcc pg_rampup ${PG_RAMPUP_MINUTES}
diset tpcc pg_duration ${PG_DURATION_MINUTES}
diset tpcc pg_allwarehouse false
diset tpcc pg_timeprofile false

# Load the driver script
loadscript

puts "Creating ${PG_VIRTUAL_USERS} virtual users..."
vuset vu ${PG_VIRTUAL_USERS}
vuset logtotemp 1
vuset unique 1

# Create virtual users
vucreate

puts "Starting benchmark run..."
puts "Ramp-up: ${PG_RAMPUP_MINUTES} minutes"
puts "Duration: ${PG_DURATION_MINUTES} minutes"

# Run the benchmark
vurun

# Wait for completion
runtimer [expr {(${PG_RAMPUP_MINUTES} + ${PG_DURATION_MINUTES} + 1) * 60000}]

puts "Benchmark complete. Collecting results..."
vudestroy
after 5000

puts "Done!"
EOF

echo "Running HammerDB benchmark..."
cd "$HAMMERDB_DIR"
./hammerdbcli auto "${RUN_TCL}" 2>&1 | tee "$RESULT_FILE"

echo ""
echo "=== Benchmark Complete ==="
echo "Results saved to: ${RESULT_FILE}"

# Extract key metrics from results
echo ""
echo "=== Key Metrics ==="
grep -E "(NOPM|TPM|TEST RESULT)" "$RESULT_FILE" || echo "No metrics found in output (check log file)"
