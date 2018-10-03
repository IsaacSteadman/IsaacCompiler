int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);
void *memcpy(void *dest, const void *src, unsigned long long size);
struct HelloStruct {
    int a;
    int b;
};
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

unsigned long long strlen(const char *str) {
    char *ptr = str;
    while (*ptr) {
        ++ptr;
    }
    return ptr - str;
}
int main(int argc, char **argv) {
    HelloStruct hs;
    char printData[64];
    char *prnData = "\nnumber: ";
    memcpy((void *)printData, (void *)prnData, strlen(prnData));
    prnData = printData;
    prnData = prnData + strlen(prnData);
    StrFromNumber(hs.a, prnData, 55);
    print(printData);
    StrFromNumber(hs.b, prnData, 55);
    print(printData);
    hs.a = 24423;
    StrFromNumber(hs.a, prnData, 55);
    print(printData);
    StrFromNumber(hs.b, prnData, 55);
    print(printData);
    hs.b = 52352;
    StrFromNumber(hs.a, prnData, 55);
    print(printData);
    StrFromNumber(hs.b, prnData, 55);
    print(printData);
}