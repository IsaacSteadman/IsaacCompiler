// Verify variadic: sum_ints(3, 10, 20, 30) should produce 60
int print(const char *str);

int sum_ints(int count, ...)
{
    va_list ap;
    va_start(ap, count);
    int total = 0;
    int i = 0;
    while (i < count)
    {
        total = total + va_arg(ap, int);
        i = i + 1;
    }
    va_end(ap);
    return total;
}

int main(int argc, char **argv)
{
    int result;
    result = sum_ints(3, 10, 20, 30);
    if (result == 60)
    {
        print("OK: sum_ints returned 60\n");
    }
    else
    {
        print("FAIL: sum_ints returned wrong value\n");
    }
    return result;
}
