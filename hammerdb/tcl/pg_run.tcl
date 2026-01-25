#!/bin/tclsh
# HammerDB TPC-C Benchmark Run Script for PostgreSQL
# This is a template script - the run_benchmark.sh script generates
# a configured version at runtime.
#
# To run manually:
#   cd hammerdb && ./hammerdbcli auto ../tcl/pg_run.tcl

puts "=== HammerDB TPC-C Benchmark ==="

# Set database type
dbset db pg
dbset bm TPC-C

# Connection settings - modify these for your environment
diset connection pg_host localhost
diset connection pg_port 5432

# Driver settings
diset tpcc pg_driver timed
diset tpcc pg_user postgres
diset tpcc pg_pass postgres
diset tpcc pg_dbase tpcc

# Must match the warehouse count used in schema build
diset tpcc pg_count_ware 10

# Use stored procedures (must match schema build setting)
diset tpcc pg_storedprocs true

# Timing settings
# Ramp-up: warm-up period before measurement starts (minutes)
diset tpcc pg_rampup 2
# Duration: how long to run the actual measurement (minutes)
diset tpcc pg_duration 5

# Distribution settings
# false = each user gets dedicated warehouses (better for scaling tests)
# true = users can access all warehouses (more contention)
diset tpcc pg_allwarehouse false

# Disable time profiling for cleaner output
diset tpcc pg_timeprofile false

# Load the PostgreSQL TPC-C driver script
loadscript

# Virtual user settings
# Number of concurrent users to simulate
set num_vu 4

puts "Configuration:"
puts "  Host: localhost:5432"
puts "  Database: tpcc"
puts "  Virtual Users: $num_vu"
puts "  Ramp-up: 2 minutes"
puts "  Duration: 5 minutes"

# Configure virtual users
vuset vu $num_vu
vuset logtotemp 1
vuset unique 1

# Create virtual users
puts ""
puts "Creating virtual users..."
vucreate

# Start the benchmark
puts "Starting benchmark..."
vurun

# Wait for the test to complete
# Total time = ramp-up + duration + buffer
set wait_time [expr {(2 + 5 + 1) * 60000}]
runtimer $wait_time

# Clean up
puts "Cleaning up..."
vudestroy
after 5000

puts ""
puts "=== Benchmark Complete ==="
puts "Check output for TEST RESULT line with NOPM and TPM metrics."
