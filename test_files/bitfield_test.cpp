int print(const char *str);
void *memset(void *ptr, unsigned char value, unsigned long long num);
void *memmove(void *dest, void *src, unsigned long long num);

unsigned long long StrFromNumber(unsigned long long Num, char *Str, unsigned long long MaxLen)
{
    if (Num == 0)
    {
        Str[0] = '0';
        Str[1] = '\0';
        return 2;
    }
    unsigned long long c = MaxLen - 1;
    memset(Str, '0', c);
    Str[c] = '\0';
    while ((c > 0) & (Num > 0))
    {
        --c;
        Str[c] = Num % 10 + '0';
        Num /= 10;
    }
    if (Num)
        return 0xFFFFFFFFFFFFFFFF;
    if (c)
    {
        memmove(Str, Str + c, MaxLen - c);
    }
    c = MaxLen - c;
    return c;
}

/* -------------------------------------------------- */
/* Test 1: two 4-bit fields in one byte (iphdr style) */
/* -------------------------------------------------- */
struct iphdr
{
    unsigned char ihl : 4;
    unsigned char version : 4;
    unsigned char tos;
};

/* -------------------------------------------------------- */
/* Test 2: multiple 1-bit flags packed in an unsigned int   */
/* -------------------------------------------------------- */
struct sk_buff
{
    unsigned int pkt_type : 3;
    unsigned int ignore_df : 1;
    unsigned int nf_trace : 1;
};

/* ------------------------------------------- */
/* Test 3: zero-width bit field forces new unit */
/* ------------------------------------------- */
struct with_zero_bf
{
    unsigned char a : 4;
    unsigned char : 0; /* force next field to start at a new byte */
    unsigned char b : 4;
};

/* ------------------------------------------- */
/* Helper: print label + decimal number + '\n' */
/* ------------------------------------------- */
void print_num(const char *label, unsigned long long val)
{
    char buf[24];
    print(label);
    print(": ");
    StrFromNumber(val, buf, 24);
    print(buf);
    print("\n");
}

int main(int argc, char **argv)
{
    char buf[24];

    /* ---------- Test 1 ---------- */
    print("=== Test 1: iphdr bit fields ===\n");
    struct iphdr hdr;
    hdr.ihl = 5;
    hdr.version = 4;
    hdr.tos = 0xAB;

    print_num("ihl", hdr.ihl);         /* expect 5  */
    print_num("version", hdr.version); /* expect 4  */
    print_num("tos", hdr.tos);         /* expect 171 (0xAB) */

    /* ihl and version share the same byte; writing one must not corrupt the other */
    hdr.ihl = 15;
    print_num("ihl after set to 15", hdr.ihl);      /* expect 15 */
    print_num("version after ihl=15", hdr.version); /* expect 4 (unchanged) */

    hdr.version = 6;
    print_num("version after set to 6", hdr.version); /* expect 6  */
    print_num("ihl after version=6", hdr.ihl);        /* expect 15 (unchanged) */

    /* ---------- Test 2 ---------- */
    print("=== Test 2: sk_buff flags ===\n");
    struct sk_buff skb;
    skb.pkt_type = 3;
    skb.ignore_df = 1;
    skb.nf_trace = 0;

    print_num("pkt_type", skb.pkt_type);   /* expect 3 */
    print_num("ignore_df", skb.ignore_df); /* expect 1 */
    print_num("nf_trace", skb.nf_trace);   /* expect 0 */

    skb.nf_trace = 1;
    skb.pkt_type = 5;
    print_num("nf_trace after set to 1", skb.nf_trace); /* expect 1 */
    print_num("pkt_type after set to 5", skb.pkt_type); /* expect 5 */
    print_num("ignore_df unchanged", skb.ignore_df);    /* expect 1 */

    /* ---------- Test 3 ---------- */
    print("=== Test 3: zero-width separator ===\n");
    struct with_zero_bf z;
    z.a = 7;
    z.b = 3;
    print_num("a", z.a); /* expect 7 */
    print_num("b", z.b); /* expect 3 */

    /* a and b are in *different* bytes due to :0 */
    z.a = 15;
    print_num("a after set to 15", z.a); /* expect 15 */
    print_num("b after a=15", z.b);      /* expect 3 (unchanged) */

    print("DONE\n");
    return 0;
}
