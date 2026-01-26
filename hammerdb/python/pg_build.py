#!/usr/bin/env python3
# HammerDB TPC-C Schema Build Script for PostgreSQL
#
# Configuration is read from environment variables.
# See .envrc.example for available options.
#
# To run:
#   cd hammerdb && ./hammerdbcli py auto ../python/pg_build.py

import os

# Read configuration from environment variables
pg_host = os.environ.get("HAMMERDB_PG_HOST", "localhost")
pg_port = os.environ.get("HAMMERDB_PG_PORT", "5432")
pg_superuser = os.environ.get("HAMMERDB_PG_SUPERUSER", "postgres")
pg_superuser_pass = os.environ.get("HAMMERDB_PG_SUPERUSER_PASS", "postgres")
pg_default_dbase = os.environ.get("HAMMERDB_PG_DEFAULT_DBASE", "postgres")
pg_user = os.environ.get("HAMMERDB_PG_USER", "postgres")
pg_pass = os.environ.get("HAMMERDB_PG_PASS", "postgres")
pg_dbase = os.environ.get("HAMMERDB_PG_DBASE", "tpcc")
pg_warehouses = os.environ.get("HAMMERDB_PG_WAREHOUSES", "10")
pg_build_vu = os.environ.get("HAMMERDB_PG_BUILD_VU", "4")
pg_stored_procs = os.environ.get("HAMMERDB_PG_STORED_PROCS", "true")

print("=== HammerDB TPC-C Schema Build ===")

# Set database type
dbset("db", "pg")
dbset("bm", "TPC-C")

# Connection settings
diset("connection", "pg_host", pg_host)
diset("connection", "pg_port", pg_port)

# Schema settings
diset("tpcc", "pg_superuser", pg_superuser)
diset("tpcc", "pg_superuserpass", pg_superuser_pass)
diset("tpcc", "pg_defaultdbase", pg_default_dbase)
diset("tpcc", "pg_user", pg_user)
diset("tpcc", "pg_pass", pg_pass)
diset("tpcc", "pg_dbase", pg_dbase)

# Scale factor: number of warehouses
# Each warehouse is approximately 100MB of data
diset("tpcc", "pg_count_ware", pg_warehouses)

# Number of virtual users for parallel data loading
diset("tpcc", "pg_num_vu", pg_build_vu)

# Use stored procedures for better benchmark performance
diset("tpcc", "pg_storedprocs", pg_stored_procs)

# Print configuration
print("Configuration:")
print(f"  Host: {pg_host}:{pg_port}")
print(f"  Database: {pg_dbase}")
print(f"  Warehouses: {pg_warehouses}")
print(f"  Build Users: {pg_build_vu}")
print(f"  Stored Procs: {pg_stored_procs}")

# Start the schema build
print("")
print("Starting schema build...")
print("This may take several minutes depending on warehouse count.")

buildschema()

print("Waiting for build to complete...")
vwait()
