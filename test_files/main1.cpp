int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);
void *memcpy(void *dest, const void *src, unsigned long long size);

int hello(void *b) {
    print("int hello(void *b) called");
}

int hello(int b) {
    print("int hello(int b) called");
}

bool NumberFromStr(unsigned long long &Num, char *Str, unsigned long long Len) {
    Num = 0;
    for (unsigned long long c = 0; c < Len; c += 1) {
        Num *= 10;
        if (Str[c] < '0' | Str[c] > '9') return 0;
        Num += Str[c] - '0';
    }
    return 1;
}

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
    bool a = 1;
    // TODO: change back to using empty '[]'
    char b[12] = "hello world";
    if (a) {
        print("hello world");
    } else {
        print("not hello world");
    }
    print("My Numbers are: ");
    char b1[20];
    StrFromNumber(12248, b1, 20);
    /*b1[0] = 'h';
    b1[1] = 'e';
    b1[2] = 'l';
    b1[3] = 'l';
    b1[4] = 'o';
    b1[5] = 0;*/
    //b1[0] = 0;
    print(b1);
    char *b2 = b1;
    print("\n and \n b2 = ");
    print(b2);
    b2[0] = 0;
    print(b1);
    print("\n");
    print("\nhello(a): ");
    hello(a);
    print("\nhello(print): ");
    hello(print);
    print("\nhello(b): ");
    char *c = b;
    //hello((void *)c);
    hello(b);
    print("\nDONE");
    a = 2;
}
// size without memmove: 1317?
/* EXPECTED OUTPUT:
hello worldMy Numbers are: 12248
and
 b2 = 12248//NOTHING//

hello(a): int hello(int b) called
hello(print): int hello(void *b) called
hello(b): int hello(void *b) called
DONE
*/