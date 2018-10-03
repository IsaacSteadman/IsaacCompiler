int print(const char *str);

unsigned long long TestFn(unsigned long long Num, char *Str, unsigned long long MaxLen) {
    unsigned long long c = MaxLen - 1;
    for (unsigned long long i = 0; i < MaxLen; i += 1) {
        Str[i] = 0;
    }
    Str[0] = 'a';
    Str[1] = 'c';
    Str[2] = 'd';
    Str[3] = 'i';
    return
}