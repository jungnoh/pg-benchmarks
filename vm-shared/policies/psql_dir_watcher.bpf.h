#ifndef __BPF_PSQL_DIR_WATCHER_H
#define __BPF_PSQL_DIR_WATCHER_H

#include "vmlinux.h"
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include "psql_dir_watcher.common.h"

#ifndef likely
#define likely(x) __builtin_expect(!!(x), 1)
#endif
#ifndef unlikely
#define unlikely(x) __builtin_expect(!!(x), 0)
#endif

#define FMODE_CREATED 0x100000 /* linux: include/linux/fs.h */

// Read-only variable, filled by loader
const volatile char watch_dir_path[BPF_PATH_MAX] = {0};
const volatile size_t watch_dir_path_len = 0;

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, __u64);
    // Value indicates whether this inode is a WAL file.
    __type(value, struct watchlist_state);
    __uint(max_entries, 9999999);
} inode_watchlist SEC(".maps");

static inline struct watchlist_state* lookup_ino(u64 inode_no) {
    return (struct watchlist_state*)bpf_map_lookup_elem(&inode_watchlist, &inode_no);
};

static inline int strncmp(const char *s1, const volatile char *s2, int n) {
	while (n && *s1 && (*s1 == *s2)) {
		++s1;
		++s2;
		--n;
	}

	if (n == 0)
		return 0;

	return *s1 - *s2;
}

// Use a fexit probe to track file opens
SEC("fexit/vfs_open")
int BPF_PROG(vfs_open_exit, struct path *path, struct file *file, long ret) {
    // If file was not opened, return
    if (ret < 0) return 0;


    // {0} required due to verifier bug in Linux 6.6.8 compared to 6.6.14
    char filepath[BPF_PATH_MAX] = {0};
    long err;
    if ((err = bpf_d_path(path, filepath, sizeof(filepath))) < 0) {
        bpf_printk("Failed to get file path: %ld\n", err);
        return 0;
    }
    int path_length = err;

    u64 inode_no = file->f_inode->i_ino;

    // Check if file is in our desired directory tree
    if (unlikely(!watch_dir_path_len)) {
        bpf_printk("watch_dir_path_len is 0!!\n");
        return 0;
    }
    if (strncmp(filepath, watch_dir_path, watch_dir_path_len) != 0) return 0;

    // Add inode to inode_watchlist
    struct watchlist_state map_value = {
        .is_wal_file = is_wal_filename(filepath, path_length)
    };
    err = bpf_map_update_elem(&inode_watchlist, &inode_no, &map_value, BPF_ANY);
    if (err != 0) {
        bpf_printk("Failed to add inode to inode_watchlist: %ld\n", err);
        return 0;
    }

    return 0;
}

#endif /* __BPF_DIR_WATCHER_H */
