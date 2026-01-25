# HammerDB PostgreSQL Benchmark Guide

This guide provides instructions for setting up and running HammerDB benchmarks against PostgreSQL in CLI mode.

## Prerequisites

- PostgreSQL server (running and accessible)
- Linux/macOS system
- curl or wget for downloading HammerDB

## Quick Start

```bash
# 1. Install HammerDB
./scripts/install.sh

# 2. Configure your PostgreSQL connection
cp config/pg_config.env.example config/pg_config.env
# Edit config/pg_config.env with your database details

# 3. Build the schema (creates test data)
./scripts/build_schema.sh

# 4. Run the benchmark
./scripts/run_benchmark.sh
```

## Directory Structure

```
hammerdb/
├── README.md                 # This guide
├── config/
│   ├── pg_config.env.example # Example configuration
│   └── pg_config.env         # Your configuration (create this)
├── scripts/
│   ├── install.sh            # HammerDB installation
│   ├── build_schema.sh       # Schema and data setup
│   ├── run_benchmark.sh      # Execute benchmark
│   └── cleanup.sh            # Remove test data
└── tcl/
    ├── pg_build.tcl          # Schema build script
    ├── pg_run.tcl            # Benchmark run script
    └── pg_drop.tcl           # Schema drop script
```

## Configuration

Edit `config/pg_config.env` with your PostgreSQL settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `PG_HOST` | PostgreSQL host | localhost |
| `PG_PORT` | PostgreSQL port | 5432 |
| `PG_USER` | Database user | postgres |
| `PG_PASSWORD` | Database password | postgres |
| `PG_DATABASE` | Target database | tpcc |
| `PG_WAREHOUSE_COUNT` | TPC-C warehouses (scale factor) | 10 |
| `PG_VIRTUAL_USERS` | Concurrent virtual users for benchmark | 4 |
| `PG_RAMPUP_MINUTES` | Ramp-up time in minutes | 2 |
| `PG_DURATION_MINUTES` | Test duration in minutes | 5 |

## Benchmark Types

HammerDB supports two benchmark types for PostgreSQL:

### TPC-C (Default)
- OLTP workload simulating order processing
- Measures transactions per minute (TPM)
- Scale factor = number of warehouses

### TPC-H
- OLAP/decision support workload
- Measures query throughput
- Scale factor = data size multiplier

## Understanding Results

After running a benchmark, you'll see output like:

```
Vuser 1:TEST RESULT : System achieved 12345 NOPM from 28456 PostgreSQL TPM
```

- **NOPM**: New Orders Per Minute (TPC-C standard metric)
- **TPM**: Total Transactions Per Minute

## Scaling Guidelines

| Warehouses | Approx. Data Size | Recommended VUsers |
|------------|-------------------|-------------------|
| 10 | ~1 GB | 2-8 |
| 100 | ~10 GB | 8-32 |
| 1000 | ~100 GB | 32-128 |

## Troubleshooting

### Connection refused
- Verify PostgreSQL is running: `pg_isready -h $PG_HOST -p $PG_PORT`
- Check pg_hba.conf allows connections from your client

### Permission denied
- Ensure the database user has CREATE, INSERT, UPDATE, DELETE permissions
- For schema creation, SUPERUSER or schema owner privileges may be needed

### Build fails or hangs
- Reduce warehouse count for initial testing
- Check available disk space
- Monitor PostgreSQL logs for errors

## Advanced Usage

### Custom Virtual User Count
```bash
PG_VIRTUAL_USERS=16 ./scripts/run_benchmark.sh
```

### Extended Duration
```bash
PG_DURATION_MINUTES=30 ./scripts/run_benchmark.sh
```

### Multiple Runs
```bash
for i in 1 2 3; do
  ./scripts/run_benchmark.sh | tee "results/run_$i.log"
done
```
