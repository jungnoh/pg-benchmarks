#ifndef __PSQL_DIR_WATCHER_COMMON_H
#define __PSQL_DIR_WATCHER_COMMON_H

#define BPF_PATH_MAX 128

#ifndef __always_inline
#define __always_inline inline __attribute__((always_inline))
#endif

struct watchlist_state {
    bool is_wal_file;
};

static __always_inline bool is_wal_filename(const char *filepath, int len) {
    /* Promote to 64-bit so the compiler never inserts <<32 / s>>32
     * sign-extension, which resets the verifier's bounds tracking. */
    long path_len = len;
    if (path_len < 24 || path_len > BPF_PATH_MAX) return false;

    /* WAL filenames are exactly 24 characters, so we can compute
     * the start of the name directly instead of scanning for '/'. */
    long name_start = path_len - 24;

    /* Bitwise AND gives the verifier a hard umax=127 that survives
        * register reloads.  Conditional checks get lost when the compiler
        * re-derives name_start from the original (unbounded) register;
        * AND is a single insn the verifier always tracks. */
    name_start &= (BPF_PATH_MAX - 1);   /* 0x7f, so umax=127 */

    /* If there is a directory component, require a '/' right before
        * the 24-char filename. */
    if (name_start > 0) {
        long slash_pos = name_start - 1;
        if (filepath[slash_pos] != '/') return false;
    }

    /* Check that the first 7 characters of the filename are '0'. */
    if (name_start + 7 > BPF_PATH_MAX) return false;
    for (long i = 0; i < 7; i++) {
        long idx = name_start + i;
        if (idx >= BPF_PATH_MAX || idx < 0) return false;
        if (filepath[idx] != '0') return false;
    }

    return true;
}

#endif
