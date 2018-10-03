int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);

unsigned long long StrFromNumber(unsigned long long Num, char *Str, unsigned long long MaxLen) {
    unsigned long long c = MaxLen - 1;
    memset(Str, '0', c);
    Str[c] = '\0';
    while ((c > 0) & (Num > 0)) {
        --c;
        Str[c] = Num % 10 + '0';
        Num /= 10;
    }
    if (Num) return 0xFFFFFFFFFFFFFFFF;
    if (c) {
        memmove(Str, Str + c, MaxLen - c);
        /*for (unsigned long long i = c; i < MaxLen; ++i) {
            Str[i - c] = Str[i];
        }*/
    }
    c = MaxLen - c;
    return c;
}
int main(int argc, char **argv) {
    char b[20];
    // memset(b, '0', 19);
    // b[19] = 0;
    print("Some Numbers:\n");
    StrFromNumber(12248, b, 20);
    print(b);
    print("\nDONE\n");
    return 0;
}
// size without memmove: 1317?