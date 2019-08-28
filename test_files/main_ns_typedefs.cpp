typedef unsigned long long size_t, u64;
typedef signed long long ptrdiff_t, i64;
typedef unsigned int u32;
typedef signed int i32;
typedef unsigned short u16;
typedef signed short i16;
typedef unsigned char u8;
typedef signed char i8;

// int print(const char *str);
int print(const char *str);
// void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memset(void *ptr, u8 value, size_t num);
// void *memmove(void *dest, void *src, unsigned long long num);
void *memmove(void *dest, void *src, size_t num);
// void *memcpy(void *dest, const void *src, unsigned long long size);
void *memcpy(void *dest, const void *src, size_t size);
typedef struct {
    i32 a;
    i32 b;
} HelloStruct;


namespace my_ns {
    size_t StrFromNumber(u64 Num, char *Str, size_t MaxLen) {
        if (MaxLen < 2) {
            return 0xFFFFFFFFFFFFFFFF;
        }
        size_t c = MaxLen - 1;
        if (Num == 0) {
            Str[0] = '0';
            Str[1] = '\0';
            return 2;
        }
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
    int test_var = 12248;
    namespace ns1 {
        size_t strlen(const char *str) {
            const char *ptr = str;
            while (*ptr) {
                ++ptr;
            }
            return ptr - str;
        }
    }
}

int test_var1;

int test_var1;


int main(int argc, char **argv) {
    HelloStruct hs;
    char printData[64];
    char *prnData = "\nnumber: ";
    memcpy((void *)printData, (void *)prnData, my_ns::ns1::strlen(prnData));
    prnData = printData;
    prnData = prnData + my_ns::ns1::strlen(prnData);
    my_ns::StrFromNumber(hs.a, prnData, 55);
    print(printData);
    my_ns::StrFromNumber(hs.b, prnData, 55);
    print(printData);
    hs.a = 24423;
    my_ns::StrFromNumber(hs.a, prnData, 55);
    print(printData);
    my_ns::StrFromNumber(hs.b, prnData, 55);
    print(printData);
    hs.b = 52352;
    my_ns::StrFromNumber(hs.a, prnData, 55);
    print(printData);
    my_ns::StrFromNumber(hs.b, prnData, 55);
    print(printData);
    my_ns::StrFromNumber(my_ns::test_var, prnData, 55);
    print(printData);
    my_ns::test_var = 1452;
    my_ns::StrFromNumber(my_ns::test_var, prnData, 55);
    print(printData);
    my_ns::StrFromNumber(test_var1, prnData, 55);
    print(printData);
}