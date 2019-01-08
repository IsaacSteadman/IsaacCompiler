int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);
void *memcpy(void *dest, const void *src, unsigned long long size);
typedef unsigned long long size_t;
typedef signed long long ptrdiff_t;
// int memcmp ( const void * ptr1, const void * ptr2, size_t num );
// double pow(double base, int exponent); // no longer imported
double pow(double base, int exponent) {
    double rtn = 1.0;
    bool is_neg = exponent < 0;
    int exp = exponent;
    if (is_neg) {
        exp = 1 + ~exponent;
    }
    double tmp = base;
    while (exp > 0) {
        if ((exp & 1) != 0) {
            rtn *= tmp;
        }
        tmp *= tmp;
        exp /= 2;
        // exp = exp >> 1;
        // exp >>= 1;
    }
    return rtn;
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

struct HelloStruct {
    double x, y, z;
    /* HelloStruct(double in_x, double in_y, double in_z) {
        this->x = in_x;
        this->y = in_y;
        this->z = in_z;
    }*/
}

// driver program to test above funtion
int main(int argc, char **argv)
{
    // HelloStruct zzyz = {0.1, 0.2, 0.3};
    HelloStruct zzyz;
    zzyz.x = 0.1;
    zzyz.y = 0.2;
    zzyz.z = 0.3;
    char res[40];
    float n = 0.453454;// 233.007;
    ftoa(n, res, 9);
    print("\nthe float value=");
    print(res);
    dtoa(1.23432458237409, res, 17);
    print("\nthe double value=");
    print(res);
    print("\n");
    double n1 = zzyz.x;
    dtoa(n1, res, 17);
    print("\nzzyz.x = ");
    print(res);
    double n2 = zzyz.y;
    dtoa(n2, res, 17);
    print("\nzzyz.y = ");
    print(res);
    double n3 = zzyz.z;
    dtoa(n3, res, 17);
    print("\nzzyz.z = ");
    print(res);
    print("\n");
    return 0;
}