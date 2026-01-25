#!/bin/bash

LOGFILE="${1:-/dev/stdin}"
SEARCH_PATH="/mnt/psql"

while IFS= read -r line; do
    [[ $line =~ ^@ino_writes\[([0-9]+)\]:\ ([0-9]+)$ ]] || continue
    
    inode="${BASH_REMATCH[1]}"
    count="${BASH_REMATCH[2]}"
    
    file=$(find "$SEARCH_PATH" -inum "$inode" 2>/dev/null | head -1)
    
    printf "%s\t%s\t%s\n" "$inode" "$count" "${file:--}"
done < "$LOGFILE"
