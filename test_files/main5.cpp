
typedef unsigned long long size_t

struct FreeRegion {
    size_t start;
    size_t end;
};
const size_t sizeof_FreeRegion = 16;


struct IdAllocator {
    FreeRegion *lst_free;
    size_t n_free_entries;
};


size_t reserve_region(IdAllocator *allocation, size_t size) {
    FreeRegion *lst_free = allocation->lst_free;
    FreeRegion *end_free = lst_free + allocation->n_free_entries;
    size_t rtn;
    for (;lst_free < end_free; ++lst_free) {
        rtn = lst_free->start;
        if (lst_free->end - rtn >= size) {
            break;
        }
    }
    if (lst_free >= end_free) return 0;
    lst_free->start = rtn + size;
    if (lst_free->end == lst_free->start) {
        for (;lst_free < end_free; ++lst_free) {
            lst_free->start = lst_free[1].start;
            lst_free->end = lst_free[1].end;
        }
        allocation->n_free_entries--;
    }
    return rtn;
}


bool try_expand_region(IdAllocator *allocation, size_t start, size_t old_size, size_t new_size) {
    FreeRegion *lst_free = allocation->lst_free;
    FreeRegion *end_free = lst_free + allocation->n_free_entries;
    size_t old_end = start + old_size;
    size_t new_end = start + new_size;
    for (;lst_free < end_free; ++lst_free) {
        size_t rtn = lst_free->start;
        if (rtn > start) {
            // usually the case is lst_free->start == old_end
            if (lst_free->start <= old_end & lst_free->end >= new_end) {
                break;
            }
        }
    }
    if (lst_free >= end_free) return false;
    lst_free->start = new_end;
    if (lst_free->end == new_end) {
        for (;lst_free < end_free; ++lst_free) {
            lst_free->start = lst_free[1].start;
            lst_free->end = lst_free[1].end;
        }
        allocation->n_free_entries--;
    }
    return false;
}


int free(void *data);
void *malloc(size_t size);
bool try_realloc(void *data, size_t size);


int release_region(IdAllocator *allocation, size_t start, size_t size) {
    FreeRegion *lst_free = allocation->lst_free;
    FreeRegion *end_free = lst_free + allocation->n_free_entries;
    size_t end = start + size;
    for (;lst_free < end_free; ++lst_free) {
        if (lst_free->start == end) {
            lst_free->start = start; // no need to create a new FreeRegion
            return 0;
        } else if (lst_free->end == start) {
            lst_free->end = end;
            return 0;
        } else if (lst_free->start > end) {
            break;
        }
    }

    // note: this assumes that malloc includes allocation size before the block of memory that is allocated
    size_t n_ent_alloc = *((size_t *)allocation->lst_free - 1) / sizeof_FreeRegion;
    FreeRegion *lst_free_to_free = (FreeRegion *)0;
    if (allocation->n_free_entries >= n_ent_alloc) {
        size_t new_n_bytes_alloc = (n_ent_alloc << 1) * sizeof_FreeRegion;
        if (try_realloc(allocation->lst_free, )) {
            n_ent_alloc <<= 1;
        } else {
            FreeRegion *new_lst_free = malloc(new_n_bytes_alloc);
            if (new_lst_free) {
                FreeRegion *end_old = lst_free + n_ent_alloc;
                FreeRegion *new_data = new_lst_free + n_ent_alloc;
                while (end_old-- > lst_free) {
                    --new_data;
                    new_data->start = old_data->start;
                    new_data->end = old_data->end;
                }
                n_ent_alloc <<= 1;
                lst_free_to_free = lst_free;
                lst_free = new_lst_free;
            }
        }
    }
    if (allocation->n_free_entries < n_ent_alloc) {
        allocation->n_free_entries += 1;
        while (end_free-- > lst_free) {
            end_free[1].start = end_free->start;
            end_free[1].end = end_free->end;
        }
        lst_free->start = start;
        lst_free->end = end;
        if (lst_free_to_free) {
            int res = free(lst_free_to_free);
            if (res < 0) {
                return res - 1;
            } else if (res > 0) {
                return res + 1;
            }
        }
        return 0;
    }
    return -1;
}


IdAllocator MallocData;
void *malloc(size_t size) {
    size_t rtn = reserve_region(&MallocData, size + 8);
    *(size_t *) rtn = size;
    return (void *)(rtn + 8);
}
bool try_realloc(void *data, size_t size) {
    size_t old_size = *((size_t *)data - 1) + 8;
    bool rtn = try_expand_region(&MallocData, (size_t )data - 8, old_size, size + 8)
    if (rtn) {
        *((size_t *)data - 1) = size;
    }
    return rtn;
}
int free(void *data) {
    return release_region(&MallocData, (size_t )data - 8, *((size_t *) data - 1) + 8);
}


int main(int argc, char **argv) {
    {
        size_t start = (size_t )@(environ::heap_start);
        size_t end = (size_t )@(environ::heap_end);
        *(size_t *)start = sizeof_FreeRegion * 16;
        FreeRegion *lst_free = (FreeRegion *)(start + 8);
        lst_free->start = start + 8 + sizeof_FreeRegion * 16;
        lst_free->end = end;
        MallocData.lst_free = lst_free;
        MallocData.n_free_entries = 1;
    }
    return 0;
}