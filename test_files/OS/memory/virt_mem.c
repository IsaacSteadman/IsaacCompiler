typedef unsigned long long size_t;
typedef signed long long ptrdiff_t;


struct VM_FreeRegion {
    size_t start, end;
};

struct VM_FreeRegion *lst_free;
VM_FreeRegion free_regions[1024];
size_t num_free_regions;

bool request_region(size_t size) {
    ;
}

bool request_free(size_t start, size_t end) {
    size_t c = 0;
    for (; c < num_free_regions; ++c) {
        VM_FreeRegion &fr = free_regions[c];
        if (fr.start >= start) {
            break;
        }
    }
    if (c >= num_free_regions) {
    // for some reason parentheses are required otherwise you get an error saying dot operator is not supported on array of 102 struct free_regions
        if ((free_regions[c]).end < start) {
            if (num_free_regions < 1024) {
                (free_regions[c]).start = start;
                (free_regions[c]).end = end;
            } else {
                return false; // too many free regions to add another
            }
        }
    }
}

/*
assuming 4 lvl 9 bit mode
*/
void init_virt_mem(size_t start_direct, size_t end_direct) {

    // enable virtual memory
    // basic process is as follows
    //   1) configure all page tables
    //   2) set top level PTE
    //   3) enable virtual memory
    // potentially below the virtual memory layer you will disable virtual memory mode
    // also in kernel space the memory manager's code will be direct mapped so that a
    //   enabling or disabling virtual memory does not change location in memory of
    //   the code and data
    asm (arch="StackVM-64",name="init_virt_mem",display_links=true) {
        "LOAD-SYSREG-FLAGS",
        "8b0010000000000",
        "OR8",
        "STOR-SYSREG-FLAGS",
    }
}

int main(int argc, char **argv) {
    char *h = "hello";
    asm (arch="StackVM-64",name="main",display_links=true) {
        "LOAD-SYSREG-FLAGS",
        "8b0010000000000", // enable virtual memory 4-lvl 9 bit per lvl 12 bit passthru
        "OR8",
        "STOR-SYSREG-FLAGS",
        "4d0", // allocate space for return
        "@$3?Pch"
        "gRa*?FPCczprint",
        "1d12",
        "RST_SP1"
    }
    return 0;
}