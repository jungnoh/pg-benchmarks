# python hammerdb.py run run07-vanilla --samples=3 --no-cache-ext-policy &&
# python hammerdb.py run run07-psql-noop --samples=3 --cache-ext-policy --cache-ext-policy-binary=cache_ext_psql_noop
python hammerdb.py run run07-psql-lru --samples=3 --cache-ext-policy --cache-ext-policy-binary=cache_ext_psql_lru
