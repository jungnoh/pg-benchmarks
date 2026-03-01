#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "psql_dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";


#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))

// #define DEBUG
#ifdef DEBUG
#define dbg_printk(fmt, ...) bpf_printk(fmt, ##__VA_ARGS__)
#else
#define dbg_printk(fmt, ...)
#endif


inline bool is_folio_relevant(struct folio *folio)
{
	if (!folio) {
		return false;
	}
	if (folio->mapping == NULL) {
		return false;
	}
	if (folio->mapping->host == NULL) {
		return false;
	}
	bool res = inode_in_watchlist(folio->mapping->host->i_ino);
	return res;
}

// Assumes that is_folio_relevant is true
inline bool is_wal_folio(struct folio *folio)
{

}

__u64 lru_list;

s32 BPF_STRUCT_OPS_SLEEPABLE(wal_lru_init, struct mem_cgroup *memcg)
{
	dbg_printk("cache_ext: Hi from the wal_lru_init hook! :D\n");
	lru_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (lru_list == 0) {
		bpf_printk("cache_ext: Failed to create lru_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created lru_list: %llu\n", lru_list);
	return 0;
}

void BPF_STRUCT_OPS(wal_lru_folio_added, struct folio *folio)
{
	dbg_printk("cache_ext: Hi from the wal_lru_folio_added hook! :D\n");
	if (!is_folio_relevant(folio)) {
		return;
	}

	int ret = bpf_cache_ext_list_add_tail(lru_list, folio);
	if (ret != 0) {
		bpf_printk("cache_ext: Failed to add folio to lru_list\n");
		return;
	}
	dbg_printk("cache_ext: Added folio to lru_list\n");
}

void BPF_STRUCT_OPS(wal_lru_folio_accessed, struct folio *folio)
{
	int ret;
	dbg_printk("cache_ext: Hi from the wal_lru_folio_accessed hook! :D\n");

	if (!is_folio_relevant(folio)) {
		return;
	}

	ret = bpf_cache_ext_list_move(lru_list, folio, true);
	if (ret != 0) {
		bpf_printk("cache_ext: Failed to move folio to lru_list tail\n");
		return;
	}

	dbg_printk("cache_ext: Moved folio to lru_list tail\n");
}

void BPF_STRUCT_OPS(wal_lru_folio_evicted, struct folio *folio)
{
	dbg_printk("cache_ext: Hi from the wal_lru_folio_evicted hook! :D\n");
	bpf_cache_ext_list_del(folio);
}

static int iterate_wal_lru(int idx, struct cache_ext_list_node *node)
{
	if ((idx < 200) && (!folio_test_uptodate(node->folio) || !folio_test_lru(node->folio))) {
		return CACHE_EXT_CONTINUE_ITER;
	}
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(wal_lru_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
	       struct mem_cgroup *memcg)
{
	dbg_printk("cache_ext: Hi from the wal_lru_evict_folios hook! :D\n");
	int ret = bpf_cache_ext_list_iterate(memcg, lru_list, iterate_wal_lru,
					     eviction_ctx);
	// Check that the right amount of folios were evicted
	if (ret < 0) {
		bpf_printk("cache_ext: Failed to evict folios\n");
	}
	if (eviction_ctx->request_nr_folios_to_evict > eviction_ctx->nr_folios_to_evict) {
		bpf_printk("cache_ext: Didn't evict enough folios. Requested: %d, Evicted: %d\n",
			   eviction_ctx->request_nr_folios_to_evict,
			   eviction_ctx->nr_folios_to_evict);
	}
}

SEC(".struct_ops.link")
struct cache_ext_ops wal_lru_ops = {
	.init = (void *)wal_lru_init,
	.evict_folios = (void *)wal_lru_evict_folios,
	.folio_accessed = (void *)wal_lru_folio_accessed,
	.folio_evicted = (void *)wal_lru_folio_evicted,
	.folio_added = (void *)wal_lru_folio_added,
};
