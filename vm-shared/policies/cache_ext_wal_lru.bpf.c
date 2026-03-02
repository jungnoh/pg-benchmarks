#include "psql_dir_watcher.bpf.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "vmlinux.h"

char _license[] SEC("license") = "GPL";


// #define DEBUG
#ifdef DEBUG
#define dbg_printk(fmt, ...) bpf_printk(fmt, ##__VA_ARGS__)
#else
#define dbg_printk(fmt, ...)
#endif

__u64 general_lru_list;
__u64 wal_lru_list;
unsigned long wal_inode_lru[2];

inline void wal_lru_inode_accessed(unsigned long ino) {
    if (wal_inode_lru[0] == ino) {
        return;
    }
    wal_inode_lru[1] = wal_inode_lru[0];
    wal_inode_lru[0] = ino;
}

inline bool inode_in_wal_lru(unsigned long ino) {
    return ino == wal_inode_lru[0] || ino == wal_inode_lru[1];
}

inline struct watchlist_state* lookup_folio(struct folio *folio)
{
	if (!folio) {
		return NULL;
	}
	if (folio->mapping == NULL) {
		return NULL;
	}
	if (folio->mapping->host == NULL) {
		return NULL;
	}
	return lookup_ino(folio->mapping->host->i_ino);
}


s32 BPF_STRUCT_OPS_SLEEPABLE(wal_lru_init, struct mem_cgroup *memcg)
{
	general_lru_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (general_lru_list == 0) {
		bpf_printk("cache_ext: Failed to create general_lru_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created general_lru_list: %llu\n", general_lru_list);

	wal_lru_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (wal_lru_list == 0) {
		bpf_printk("cache_ext: Failed to create wal_lru_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created wal_lru_list: %llu\n", wal_lru_list);

	return 0;
}

void BPF_STRUCT_OPS(wal_lru_folio_added, struct folio *folio)
{
    struct watchlist_state* state = lookup_folio(folio);
    if (state == NULL) {
		return;
	}

    int ret;
    if (state->is_wal_file) {
        ret = bpf_cache_ext_list_add_tail(wal_lru_list, folio);
        wal_lru_inode_accessed(folio->mapping->host->i_ino);
    } else {
        ret = bpf_cache_ext_list_add_tail(general_lru_list, folio);
    }

	if (ret != 0) {
		bpf_printk("cache_ext: Failed to add folio to lru_list\n");
		return;
	}
	dbg_printk("cache_ext: Added folio to lru_list\n");
}

void BPF_STRUCT_OPS(wal_lru_folio_accessed, struct folio *folio)
{
	dbg_printk("cache_ext: Hi from the wal_lru_folio_accessed hook! :D\n");


	struct watchlist_state* state = lookup_folio(folio);
    if (state == NULL) {
        return;
    }

    int ret;
    if (state->is_wal_file) {
        bpf_printk("cache_ext: WAL LRU folio accessed - ino %lu\n", folio->mapping->host->i_ino);
        ret = bpf_cache_ext_list_move(wal_lru_list, folio, true);
        wal_lru_inode_accessed(folio->mapping->host->i_ino);
    } else {
        ret = bpf_cache_ext_list_move(general_lru_list, folio, true);
    }

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

static int iterate_wal_lru_list(int idx, struct cache_ext_list_node *node)
{
    // Check if the folio of the node is file-backed.
    // This shouldn't hit considering the nature of folios in the list, but just being safe
    if (node->folio == NULL || node->folio->mapping == NULL || node->folio->mapping->host == NULL) {
	    return CACHE_EXT_CONTINUE_ITER;
	}
	if (!folio_test_uptodate(node->folio) || !folio_test_lru(node->folio)) {
		return CACHE_EXT_CONTINUE_ITER;
	}
	unsigned long ino = node->folio->mapping->host->i_ino;
	if (inode_in_wal_lru(ino)) {
	    return CACHE_EXT_CONTINUE_ITER;
	}
	bpf_printk("cache_ext: Evicting WAL folio for ino %lu\n", ino);
	return CACHE_EXT_EVICT_NODE;
}

static int iterate_general_lru_list(int idx, struct cache_ext_list_node *node)
{
	if (!folio_test_uptodate(node->folio) || !folio_test_lru(node->folio)) {
		return CACHE_EXT_CONTINUE_ITER;
	}
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(wal_lru_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
	       struct mem_cgroup *memcg)
{
	dbg_printk("cache_ext: Hi from the wal_lru_evict_folios hook! :D\n");
	int ret = bpf_cache_ext_list_iterate(memcg, wal_lru_list, iterate_wal_lru_list,
					     eviction_ctx);
	if (ret < 0) {
		bpf_printk("cache_ext: Failed to evict folios\n");
	}
	if (eviction_ctx->request_nr_folios_to_evict <= eviction_ctx->nr_folios_to_evict) {
		return;
	}

	ret = bpf_cache_ext_list_iterate(memcg, general_lru_list, iterate_general_lru_list,
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
