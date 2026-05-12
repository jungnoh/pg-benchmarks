# Baseline (no cache-ext policy).
python hammerdb.py run tpcc-48-final2-baseline --samples=4 --no-cep && \

# Our policy: v1 (INDEX-only hot) + N1 (WAL-eject-first) +
# N2 (broad insert-TTL pin, 30s) + N5 (WAL high-watermark, 8-folio trail).
python hammerdb.py run tpcc-48-final2-policy_tpcc --samples=4 \
    --cep --cep-binary=cache_ext_psql_tpcc 
