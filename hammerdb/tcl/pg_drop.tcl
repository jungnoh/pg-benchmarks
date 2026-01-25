#!/bin/tclsh
# HammerDB TPC-C Schema Drop Script for PostgreSQL
# Removes the TPC-C schema from the database
#
# To run:
#   cd hammerdb && ./hammerdbcli auto ../tcl/pg_drop.tcl

puts "=== HammerDB TPC-C Schema Drop ==="

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

puts "Dropping TPC-C schema..."
deleteschema

puts "Schema dropped."
