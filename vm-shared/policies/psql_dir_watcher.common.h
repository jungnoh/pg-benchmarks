#ifndef __PSQL_DIR_WATCHER_COMMON_H
#define __PSQL_DIR_WATCHER_COMMON_H

struct watchlist_state {
    bool is_wal_file;
};

inline bool is_wal_filename(const char *filepath, int len) {
    int last_part_index = 0;
    for (int i = 0; i < len && filepath[i]; i++) {
        if (filepath[i] == '/') {
            last_part_index = i;
        }
    }
    last_part_index++;
    filepath += last_part_index;
    len -= last_part_index;
    if (len != 24) {
        return false;
    }
    for (int i = 0; i < 7; i++) {
        if (filepath[i] != '0') {
            return false;
        }
    }
    return true;
}


#endif
