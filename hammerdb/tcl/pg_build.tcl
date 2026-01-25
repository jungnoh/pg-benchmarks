#!/bin/tclsh
# HammerDB TPC-C Schema Build Script for PostgreSQL
# This is a template script - the build_schema.sh script generates
# a configured version at runtime.
#
# To run manually:
#   cd hammerdb && ./hammerdbcli auto ../tcl/pg_build.tcl

puts "=== HammerDB TPC-C Schema Build ==="

# Set database type
dbset db pg
dbset bm TPC-C

# Connection settings - modify these for your environment
diset connection pg_host localhost
diset connection pg_port 5432

# Schema settings
diset tpcc pg_superuser postgres
diset tpcc pg_superuserpass postgres
diset tpcc pg_defaultdbase postgres
diset tpcc pg_user postgres
diset tpcc pg_pass postgres
diset tpcc pg_dbase tpcc

# Scale factor: number of warehouses
# Each warehouse is approximately 100MB of data
# Recommended: start with 10 for testing
diset tpcc pg_count_ware 10

# Number of virtual users for parallel data loading
# More users = faster loading, but more database load
diset tpcc pg_num_vu 4

# Use stored procedures for better benchmark performance
diset tpcc pg_storedprocs true

# Print configuration
puts "Configuration:"
puts "  Host: localhost:5432"
puts "  Database: tpcc"
puts "  Warehouses: 10"
puts "  Build Users: 4"

# Start the schema build
puts ""
puts "Starting schema build..."
puts "This may take several minutes depending on warehouse count."

buildschema

puts "Waiting for build to complete..."
vwait forever
