int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);
void *memcpy(void *dest, const void *src, unsigned long long size);
double pow(double base, int exponent);

unsigned long long strlen(const char *str) {
    char *ptr = str;
    while (*ptr) {
        ++ptr;
    }
    return ptr - str;
}

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


// reverses a string 'str' of length 'len'
void reverse(char *str, int len)
{
    int i=0, j=len-1, temp;
    while (i<j)
    {
        temp = str[i];
        str[i] = str[j];
        str[j] = temp;
        i++; j--;
    }
}

 // Converts a given integer x to string str[].  d is the number
 // of digits required in output. If d is more than the number
 // of digits in x, then 0s are added at the beginning.
int intToStr(int x, char *str, int d)
{
    int i = 0;
    while (x)
    {
        str[i++] = (x%10) + '0';
        x = x/10;
    }

    // If number of digits required is more, then
    // add 0s at the beginning
    while (i < d)
        str[i++] = '0';

    reverse(str, i);
    str[i] = '\0';
    return i;
}

// Converts a floating point number to string.
void ftoa(float n, char *res, int afterpoint)
{
    // Extract integer part
    int ipart = (int)n;

    // Extract floating part
    float fpart = n - (float)ipart;

    // convert integer part to string
    int i = intToStr(ipart, res, 0);

    // check for display option after point
    if (afterpoint != 0)
    {
        res[i] = '.';  // add dot

        // Get the value of fraction part upto given no.
        // of points after dot. The third parameter is needed
        // to handle cases like 233.007
        fpart = fpart * pow(10, afterpoint);

        intToStr((int)fpart, res + i + 1, afterpoint);
    }
}

 // Converts a given integer x to string str[].  d is the number
 // of digits required in output. If d is more than the number
 // of digits in x, then 0s are added at the beginning.
long long longlongToStr(long long x, char *str, long long d)
{
    long long i = 0;
    while (x)
    {
        str[i++] = (x%10) + '0';
        x = x/10;
    }

    // If number of digits required is more, then
    // add 0s at the beginning
    while (i < d)
        str[i++] = '0';

    reverse(str, i);
    str[i] = '\0';
    return i;
}

// Converts a floating point number to string.
void dtoa(double n, char *res, int afterpoint)
{
    // Extract integer part
    long long ipart = (long long)n;

    // Extract floating part
    double fpart = n - (double)ipart;

    // convert integer part to string
    int i = longlongToStr(ipart, res, 0);

    // check for display option after point
    if (afterpoint != 0)
    {
        res[i] = '.';  // add dot

        // Get the value of fraction part upto given no.
        // of points after dot. The third parameter is needed
        // to handle cases like 233.007
        fpart = fpart * pow(10, afterpoint);

        longlongToStr((long long)fpart, res + i + 1, afterpoint);
    }
}

// driver program to test above funtion
int main(int argc, char **argv)
{
    char res[40];
    float n = 0.453454;// 233.007;
    ftoa(n, res, 9);
    print("\nthe float value=");
    print(res);
    dtoa(1.23432458237409, res, 17);
    print("\nthe double value=");
    print(res);
    print("\n");
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