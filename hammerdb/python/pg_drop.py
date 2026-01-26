#!/usr/bin/env python3
# HammerDB TPC-C Schema Drop Script for PostgreSQL
#
# Configuration is read from environment variables.
# See .envrc.example for available options.
#
# To run:
#   cd hammerdb && ./hammerdbcli py auto ../python/pg_drop.py

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

print("=== HammerDB TPC-C Schema Drop ===")

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

print(f"Dropping TPC-C schema from {pg_dbase}...")
deleteschema()

print("Schema dropped.")
