# python hammerdb.py run run07-vanilla --samples=3 --no-cep &&
# python hammerdb.py run run07-psql-noop --samples=3 --cep --cep-binary=cache_ext_psql_noop
python hammerdb.py run run07-psql-lru-hot5pct --samples=3 --cep --cep-binary=cache_ext_psql_lru --cep-extra-args="--hot_cap_pct 5"
