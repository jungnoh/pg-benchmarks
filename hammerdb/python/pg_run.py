#!/usr/bin/env python3
# HammerDB TPC-C Benchmark Run Script for PostgreSQL
#
# Configuration is read from environment variables.
# See .envrc.example for available options.
#
# To run:
#   cd hammerdb && ./hammerdbcli py auto ../python/pg_run.py

import os

# Read configuration from environment variables
pg_host = os.environ.get("HAMMERDB_PG_HOST", "localhost")
pg_port = os.environ.get("HAMMERDB_PG_PORT", "5432")
pg_user = os.environ.get("HAMMERDB_PG_USER", "postgres")
pg_pass = os.environ.get("HAMMERDB_PG_PASS", "postgres")
pg_dbase = os.environ.get("HAMMERDB_PG_DBASE", "tpcc")
pg_warehouses = os.environ.get("HAMMERDB_PG_WAREHOUSES", "10")
pg_stored_procs = os.environ.get("HAMMERDB_PG_STORED_PROCS", "true")
pg_rampup = os.environ.get("HAMMERDB_PG_RAMPUP", "2")
pg_duration = os.environ.get("HAMMERDB_PG_DURATION", "5")
pg_all_warehouse = os.environ.get("HAMMERDB_PG_ALL_WAREHOUSE", "false")
pg_time_profile = os.environ.get("HAMMERDB_PG_TIME_PROFILE", "false")
pg_run_vu = int(os.environ.get("HAMMERDB_PG_RUN_VU", "4"))

print("=== HammerDB TPC-C Benchmark ===")

# Set database type
dbset("db", "pg")
dbset("bm", "TPC-C")

# Connection settings
diset("connection", "pg_host", pg_host)
diset("connection", "pg_port", pg_port)

# Driver settings
diset("tpcc", "pg_driver", "timed")
diset("tpcc", "pg_user", pg_user)
diset("tpcc", "pg_pass", pg_pass)
diset("tpcc", "pg_dbase", pg_dbase)

# Must match the warehouse count used in schema build
diset("tpcc", "pg_count_ware", pg_warehouses)

# Use stored procedures (must match schema build setting)
diset("tpcc", "pg_storedprocs", pg_stored_procs)

# Timing settings
diset("tpcc", "pg_rampup", pg_rampup)
diset("tpcc", "pg_duration", pg_duration)

# Distribution settings
# false = each user gets dedicated warehouses (better for scaling tests)
# true = users can access all warehouses (more contention)
diset("tpcc", "pg_allwarehouse", pg_all_warehouse)

# Time profiling
diset("tpcc", "pg_timeprofile", pg_time_profile)

# Load the PostgreSQL TPC-C driver script
loadscript()

print("Configuration:")
print(f"  Host: {pg_host}:{pg_port}")
print(f"  Database: {pg_dbase}")
print(f"  Virtual Users: {pg_run_vu}")
print(f"  Warehouses: {pg_warehouses}")
print(f"  Ramp-up: {pg_rampup} minutes")
print(f"  Duration: {pg_duration} minutes")

# Configure virtual users
vuset("vu", pg_run_vu)
vuset("logtotemp", 1)
vuset("unique", 1)

# Create virtual users
print("")
print("Creating virtual users...")
vucreate()

# Start the benchmark
print("Starting benchmark...")
vurun()

# Wait for the test to complete
# Total time = ramp-up + duration + buffer (1 min)
wait_time = (int(pg_rampup) + int(pg_duration) + 1) * 60000
runtimer(wait_time)

# Clean up
print("Cleaning up...")
vudestroy()
tclsleep(5000)

print("")
print("=== Benchmark Complete ===")
print("Check output for TEST RESULT line with NOPM and TPM metrics.")
