int __svm_clz4(unsigned int x) {
    int n = 32;
    while (x != 0) {
        n = n - 1;
        x = x >> 1;
    }
    return n;
}

int __svm_clz8(unsigned long long x) {
    int n = 64;
    while (x != 0) {
        n = n - 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ctz4(unsigned int x) {
    int n = 0;
    if (x == 0) {
        return 32;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ctz8(unsigned long long x) {
    int n = 0;
    if (x == 0) {
        return 64;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_popcnt4(unsigned int x) {
    int n = 0;
    while (x != 0) {
        n = n + (x & 1);
        x = x >> 1;
    }
    return n;
}

int __svm_popcnt8(unsigned long long x) {
    int n = 0;
    while (x != 0) {
        n = n + (x & 1);
        x = x >> 1;
    }
    return n;
}

unsigned short __svm_bswap2(unsigned short x) {
    unsigned short out = 0;
    int i = 0;
    while (i < 2) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

unsigned int __svm_bswap4(unsigned int x) {
    unsigned int out = 0;
    int i = 0;
    while (i < 4) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

unsigned long long __svm_bswap8(unsigned long long x) {
    unsigned long long out = 0;
    int i = 0;
    while (i < 8) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

int __svm_ffs4(unsigned int x) {
    int n = 1;
    if (x == 0) {
        return 0;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ffs8(unsigned long long x) {
    int n = 1;
    if (x == 0) {
        return 0;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}
