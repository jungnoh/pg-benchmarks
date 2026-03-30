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
unsigned long wal_last_accessed_ino = 0;


static inline struct watchlist_state* lookup_folio(struct folio *folio)
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

    // If state is NULL the folio is either anonymous (mapping==NULL) or
    // belongs to a file whose inode was not in inode_watchlist at open time
    // (e.g. WAL segments pre-opened by Postgres before the BPF probe was
    // attached).  Anonymous pages are skipped; file-backed pages are added
    // to the general list so they remain reclaimable by the policy.
    if (state == NULL) {
        if (!folio || folio->mapping == NULL || folio->mapping->host == NULL)
            return;  // anonymous or no inode — skip
        unsigned long ino = folio->mapping->host->i_ino;
        if (ino_is_wal_file(ino)) {
            // Untracked WAL inode (opened before probe attached): evict like tracked WAL.
            if (bpf_cache_ext_list_add_tail(wal_lru_list, folio) != 0)
                bpf_printk("cache_ext: Failed to add untracked WAL folio to wal_lru_list\n");
            WRITE_ONCE(wal_last_accessed_ino, ino);
        } else {
            if (bpf_cache_ext_list_add_tail(general_lru_list, folio) != 0)
                bpf_printk("cache_ext: Failed to add untracked folio to general_lru_list\n");
        }
        return;
	}

    int ret;
    unsigned long ino = folio->mapping->host->i_ino;
    if (state->is_wal_file) {
        ret = bpf_cache_ext_list_add_tail(wal_lru_list, folio);
        WRITE_ONCE(wal_last_accessed_ino, ino);
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

    int ret;
    if (state == NULL) {
        if (!folio || folio->mapping == NULL || folio->mapping->host == NULL)
            return;
        unsigned long ino = folio->mapping->host->i_ino;
        if (ino_is_wal_file(ino)) {
            ret = bpf_cache_ext_list_move(wal_lru_list, folio, true);
            WRITE_ONCE(wal_last_accessed_ino, ino);
            if (ret != 0)
                bpf_printk("cache_ext: Failed to move untracked WAL folio in wal_lru_list\n");
        } else {
            ret = bpf_cache_ext_list_move(general_lru_list, folio, true);
            if (ret != 0)
                bpf_printk("cache_ext: Failed to move untracked folio in general_lru_list\n");
        }
        return;
    }

    unsigned long ino = folio->mapping->host->i_ino;
    if (state->is_wal_file) {
        dbg_printk("cache_ext: WAL LRU folio accessed - ino %lu\n", ino);
        ret = bpf_cache_ext_list_move(wal_lru_list, folio, true);
        if (ret != 0) {
            // Folio was likely added to general_lru_list before this inode
            // was registered as WAL (late registration after probe attach).
            // Migrate it to wal_lru_list.
            bpf_cache_ext_list_del(folio);
            ret = bpf_cache_ext_list_add_tail(wal_lru_list, folio);
        }
        WRITE_ONCE(wal_last_accessed_ino, ino);
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
	// Remove from whichever list the folio is on.  list_del does not need
	// mapping/host — only the folio pointer.  Skipping the call when mapping
	// is NULL (e.g. after truncation) would leak the node in the list.
	if (!folio)
		return;
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
	if (ino == READ_ONCE(wal_last_accessed_ino)) {
	    return CACHE_EXT_CONTINUE_ITER;
	}
	// bpf_printk("cache_ext: Evicting WAL folio for ino %lu\n", ino);
	return CACHE_EXT_EVICT_NODE;
}

static int iterate_general_lru_list(int idx, struct cache_ext_list_node *node)
{
	if (node->folio == NULL) {
		return CACHE_EXT_CONTINUE_ITER;
	}
	if (!folio_test_uptodate(node->folio) || !folio_test_lru(node->folio)) {
		return CACHE_EXT_CONTINUE_ITER;
	}
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(wal_lru_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
	       struct mem_cgroup *memcg)
{
	dbg_printk("cache_ext: Hi from the wal_lru_evict_folios hook! :D\n");

	// Drain ALL stale WAL segments (pages from any ino != wal_last_accessed_ino)
	// regardless of how many the kernel requested.  This keeps the WAL list
	// from accumulating across calls; the general list handles the actual
	// kernel-requested quota below.
	// Skip the WAL drain when wal_last_accessed_ino is still 0 (no WAL access
	// recorded yet) — otherwise every WAL page would be evicted since no real
	// inode has i_ino == 0.
	unsigned long orig_request = eviction_ctx->request_nr_folios_to_evict;
	if (READ_ONCE(wal_last_accessed_ino) != 0) {
		eviction_ctx->request_nr_folios_to_evict = (unsigned long)-1 >> 1;
		int wal_ret = bpf_cache_ext_list_iterate(memcg, wal_lru_list, iterate_wal_lru_list,
						     eviction_ctx);
		eviction_ctx->request_nr_folios_to_evict = orig_request;
		if (wal_ret < 0) {
			bpf_printk("cache_ext: Failed to evict WAL folios\n");
		}
		if (eviction_ctx->nr_folios_to_evict >= orig_request) {
			return;
		}
	}

	int ret = bpf_cache_ext_list_iterate(memcg, general_lru_list, iterate_general_lru_list,
					     eviction_ctx);
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
