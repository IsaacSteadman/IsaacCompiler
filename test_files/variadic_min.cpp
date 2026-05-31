// Minimal variadic test: sum_ints(1, 42) should return 42
int sum_one(int count, ...)
{
    va_list ap;
    va_start(ap, count);
    int val;
    val = va_arg(ap, int);
    va_end(ap);
    return val;
}

int main(int argc, char **argv)
{
    return sum_one(1, 42);
}
