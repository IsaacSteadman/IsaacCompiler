/*
 * Freestanding runtime helpers for StackVM.
 *
 * Keep this file self-contained: it is compiled by the IsaacCompiler test
 * harness and linked on demand as runtime_extern_deps.
 */

#include <stackvm.h>
#include <stdarg.h>

int __svm_clz4(unsigned int x) {
    int n = 32;
    while (x != 0) {
        n = n - 1;
        x = x >> 1;
    }
    return n;
}

int __svm_clz8(unsigned long long x) {
    int n = 64;
    while (x != 0) {
        n = n - 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ctz4(unsigned int x) {
    int n = 0;
    if (x == 0) {
        return 32;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ctz8(unsigned long long x) {
    int n = 0;
    if (x == 0) {
        return 64;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_popcnt4(unsigned int x) {
    int n = 0;
    while (x != 0) {
        n = n + (x & 1);
        x = x >> 1;
    }
    return n;
}

int __svm_popcnt8(unsigned long long x) {
    int n = 0;
    while (x != 0) {
        n = n + (x & 1);
        x = x >> 1;
    }
    return n;
}

unsigned short __svm_bswap2(unsigned short x) {
    unsigned short out = 0;
    int i = 0;
    while (i < 2) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

unsigned int __svm_bswap4(unsigned int x) {
    unsigned int out = 0;
    int i = 0;
    while (i < 4) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

unsigned long long __svm_bswap8(unsigned long long x) {
    unsigned long long out = 0;
    int i = 0;
    while (i < 8) {
        out = (out << 8) | (x & 0xff);
        x = x >> 8;
        i = i + 1;
    }
    return out;
}

int __svm_ffs4(unsigned int x) {
    int n = 1;
    if (x == 0) {
        return 0;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

int __svm_ffs8(unsigned long long x) {
    int n = 1;
    if (x == 0) {
        return 0;
    }
    while ((x & 1) == 0) {
        n = n + 1;
        x = x >> 1;
    }
    return n;
}

unsigned long long strlen(const char *str) {
    unsigned long long n = 0;
    while (str[n] != 0) {
        n = n + 1;
    }
    return n;
}

int memcmp(const void *ptr1, const void *ptr2, unsigned long long num) {
    const unsigned char *a = (const unsigned char *)ptr1;
    const unsigned char *b = (const unsigned char *)ptr2;
    unsigned long long i = 0;
    while (i < num) {
        unsigned char av = a[i];
        unsigned char bv = b[i];
        if (av != bv) {
            return (int)av - (int)bv;
        }
        i = i + 1;
    }
    return 0;
}

int strcmp(const char *s1, const char *s2) {
    unsigned long long i = 0;
    while (s1[i] != 0) {
        if (s1[i] != s2[i]) {
            break;
        }
        i = i + 1;
    }
    return (int)((unsigned char)s1[i]) - (int)((unsigned char)s2[i]);
}

int strncmp(const char *s1, const char *s2, unsigned long long num) {
    unsigned long long i = 0;
    while (i < num) {
        unsigned char a = (unsigned char)s1[i];
        unsigned char b = (unsigned char)s2[i];
        if (a != b) {
            return (int)a - (int)b;
        }
        if (a == 0) {
            return 0;
        }
        i = i + 1;
    }
    return 0;
}

char *strcpy(char *dest, const char *src) {
    unsigned long long i = 0;
    while (1) {
        dest[i] = src[i];
        if (src[i] == 0) {
            return dest;
        }
        i = i + 1;
    }
}

char *strncpy(char *dest, const char *src, unsigned long long num) {
    unsigned long long i = 0;
    while (i < num) {
        if (src[i] == 0) {
            break;
        }
        dest[i] = src[i];
        i = i + 1;
    }
    while (i < num) {
        dest[i] = 0;
        i = i + 1;
    }
    return dest;
}

size_t __svm_printf_emit(char *out, size_t out_size, size_t count, char ch) {
    if (out_size != 0) {
        if (count + 1 < out_size) {
            out[count] = ch;
        }
    }
    return count + 1;
}

size_t __svm_printf_repeat(
    char *out,
    size_t out_size,
    size_t count,
    char ch,
    int n
) {
    while (n > 0) {
        count = __svm_printf_emit(out, out_size, count, ch);
        n = n - 1;
    }
    return count;
}

int __svm_printf_strlen_limited(const char *str, int precision) {
    int n = 0;
    while (str[n] != 0) {
        if (precision >= 0) {
            if (n >= precision) {
                break;
            }
        }
        n = n + 1;
    }
    return n;
}

int __svm_printf_digit_count(unsigned long long value, unsigned int base) {
    int count = 1;
    while ((value / (unsigned long long)base) != 0) {
        value = value / (unsigned long long)base;
        count = count + 1;
    }
    return count;
}

size_t __svm_printf_emit_unsigned(
    char *out,
    size_t out_size,
    size_t count,
    unsigned long long value,
    unsigned int base,
    int uppercase,
    int digits_count
) {
    unsigned long long div = 1;
    int i = 1;
    const char *digits = "0123456789abcdef";
    if (uppercase) {
        digits = "0123456789ABCDEF";
    }
    while (i < digits_count) {
        div = div * (unsigned long long)base;
        i = i + 1;
    }
    while (digits_count > 0) {
        int digit = (int)(value / div);
        count = __svm_printf_emit(out, out_size, count, digits[digit]);
        value = value % div;
        div = div / (unsigned long long)base;
        digits_count = digits_count - 1;
    }
    return count;
}

size_t __svm_printf_emit_string(
    char *out,
    size_t out_size,
    size_t count,
    const char *str,
    int width,
    int precision,
    int left
) {
    int len = __svm_printf_strlen_limited(str, precision);
    int pad = width - len;
    int i = 0;
    if (left == 0) {
        count = __svm_printf_repeat(out, out_size, count, ' ', pad);
    }
    while (i < len) {
        count = __svm_printf_emit(out, out_size, count, str[i]);
        i = i + 1;
    }
    if (left) {
        count = __svm_printf_repeat(out, out_size, count, ' ', pad);
    }
    return count;
}

size_t __svm_printf_emit_char_field(
    char *out,
    size_t out_size,
    size_t count,
    char ch,
    int width,
    int left,
    char pad_ch
) {
    int pad = width - 1;
    if (left == 0) {
        count = __svm_printf_repeat(out, out_size, count, pad_ch, pad);
    }
    count = __svm_printf_emit(out, out_size, count, ch);
    if (left) {
        count = __svm_printf_repeat(out, out_size, count, ' ', pad);
    }
    return count;
}

size_t __svm_printf_emit_number(
    char *out,
    size_t out_size,
    size_t count,
    unsigned long long value,
    int negative,
    int is_signed,
    unsigned int base,
    int uppercase,
    int width,
    int precision,
    int left,
    int plus,
    int space,
    int alt,
    int zero,
    int pointer_format,
    char spec
) {
    int sign_len = 0;
    int prefix_len = 0;
    int digits_count = 0;
    int zero_count = 0;
    int field_len = 0;
    int pad = 0;
    char pad_ch = ' ';

    if (negative) {
        sign_len = 1;
    } else if (is_signed & plus) {
        sign_len = 1;
    } else if (is_signed & space) {
        sign_len = 1;
    }

    if (pointer_format) {
        prefix_len = 2;
    } else if ((spec == 'x') | (spec == 'X')) {
        if (alt & (value != 0)) {
            prefix_len = 2;
        }
    } else if (spec == 'o') {
        if (alt & (value != 0)) {
            prefix_len = 1;
        }
    }

    if ((precision == 0) & (value == 0)) {
        digits_count = 0;
    } else {
        digits_count = __svm_printf_digit_count(value, base);
    }
    if (precision > digits_count) {
        zero_count = precision - digits_count;
    }

    field_len = sign_len + prefix_len + zero_count + digits_count;
    pad = width - field_len;
    if (zero & (left == 0) & (precision < 0)) {
        pad_ch = '0';
    }

    if (pad_ch == ' ') {
        count = __svm_printf_repeat(out, out_size, count, ' ', pad);
    }

    if (negative) {
        count = __svm_printf_emit(out, out_size, count, '-');
    } else if (is_signed & plus) {
        count = __svm_printf_emit(out, out_size, count, '+');
    } else if (is_signed & space) {
        count = __svm_printf_emit(out, out_size, count, ' ');
    }

    if (prefix_len == 2) {
        count = __svm_printf_emit(out, out_size, count, '0');
        if (uppercase) {
            count = __svm_printf_emit(out, out_size, count, 'X');
        } else {
            count = __svm_printf_emit(out, out_size, count, 'x');
        }
    } else if (prefix_len == 1) {
        count = __svm_printf_emit(out, out_size, count, '0');
    }

    if (pad_ch == '0') {
        count = __svm_printf_repeat(out, out_size, count, '0', pad);
    }
    count = __svm_printf_repeat(out, out_size, count, '0', zero_count);
    if (digits_count > 0) {
        count = __svm_printf_emit_unsigned(
            out,
            out_size,
            count,
            value,
            base,
            uppercase,
            digits_count
        );
    }
    if (left) {
        count = __svm_printf_repeat(out, out_size, count, ' ', pad);
    }
    return count;
}

int __svm_vformat(char *out, size_t out_size, const char *fmt, va_list ap) {
    size_t count = 0;
    size_t i = 0;
    while (fmt[i] != 0) {
        if (fmt[i] != '%') {
            count = __svm_printf_emit(out, out_size, count, fmt[i]);
            i = i + 1;
        } else {
            int left = 0;
            int plus = 0;
            int space = 0;
            int alt = 0;
            int zero = 0;
            int width = 0;
            int precision = -1;
            int length = 0;
            char spec = 0;

            i = i + 1;
            while (
                (fmt[i] == '-') |
                (fmt[i] == '+') |
                (fmt[i] == ' ') |
                (fmt[i] == '#') |
                (fmt[i] == '0')
            ) {
                if (fmt[i] == '-') {
                    left = 1;
                } else if (fmt[i] == '+') {
                    plus = 1;
                } else if (fmt[i] == ' ') {
                    space = 1;
                } else if (fmt[i] == '#') {
                    alt = 1;
                } else {
                    zero = 1;
                }
                i = i + 1;
            }

            if (fmt[i] == '*') {
                width = va_arg(ap, int);
                if (width < 0) {
                    left = 1;
                    width = 0 - width;
                }
                i = i + 1;
            } else {
                while ((fmt[i] >= '0') & (fmt[i] <= '9')) {
                    width = (width * 10) + ((int)fmt[i] - (int)'0');
                    i = i + 1;
                }
            }

            if (fmt[i] == '.') {
                i = i + 1;
                precision = 0;
                if (fmt[i] == '*') {
                    precision = va_arg(ap, int);
                    if (precision < 0) {
                        precision = -1;
                    }
                    i = i + 1;
                } else {
                    while ((fmt[i] >= '0') & (fmt[i] <= '9')) {
                        precision = (precision * 10) + ((int)fmt[i] - (int)'0');
                        i = i + 1;
                    }
                }
            }

            if (fmt[i] == 'h') {
                i = i + 1;
                if (fmt[i] == 'h') {
                    length = 1;
                    i = i + 1;
                } else {
                    length = 2;
                }
            } else if (fmt[i] == 'l') {
                i = i + 1;
                if (fmt[i] == 'l') {
                    length = 4;
                    i = i + 1;
                } else {
                    length = 3;
                }
            } else if (fmt[i] == 'z') {
                length = 5;
                i = i + 1;
            } else if (fmt[i] == 't') {
                length = 6;
                i = i + 1;
            }

            spec = fmt[i];
            if (spec == 0) {
                break;
            }
            i = i + 1;

            if (spec == 's') {
                count = __svm_printf_emit_string(
                    out,
                    out_size,
                    count,
                    va_arg(ap, const char *),
                    width,
                    precision,
                    left
                );
            } else if (spec == 'c') {
                count = __svm_printf_emit_char_field(
                    out,
                    out_size,
                    count,
                    (char)va_arg(ap, int),
                    width,
                    left,
                    ' '
                );
            } else if (spec == '%') {
                char pad_ch = ' ';
                if (zero) {
                    pad_ch = '0';
                }
                count = __svm_printf_emit_char_field(
                    out,
                    out_size,
                    count,
                    '%',
                    width,
                    left,
                    pad_ch
                );
            } else if (
                (spec == 'd') |
                (spec == 'i') |
                (spec == 'u') |
                (spec == 'x') |
                (spec == 'X') |
                (spec == 'o') |
                (spec == 'p')
            ) {
                unsigned long long value = 0;
                long long signed_value = 0;
                int negative = 0;
                int is_signed = (spec == 'd') | (spec == 'i');
                int pointer_format = spec == 'p';
                unsigned int base = 10;
                int uppercase = 0;

                if ((spec == 'x') | (spec == 'X') | (spec == 'p')) {
                    base = 16;
                } else if (spec == 'o') {
                    base = 8;
                }
                if (spec == 'X') {
                    uppercase = 1;
                }

                if (pointer_format) {
                    value = (unsigned long long)va_arg(ap, size_t);
                } else if (is_signed) {
                    if (length == 1) {
                        signed_value = (long long)((signed char)va_arg(ap, int));
                    } else if (length == 2) {
                        signed_value = (long long)((short)va_arg(ap, int));
                    } else if (length == 3) {
                        signed_value = (long long)va_arg(ap, long);
                    } else if (length == 4) {
                        signed_value = va_arg(ap, long long);
                    } else if (length == 5) {
                        signed_value = va_arg(ap, long long);
                    } else if (length == 6) {
                        signed_value = va_arg(ap, long long);
                    } else {
                        signed_value = (long long)va_arg(ap, int);
                    }
                    if (signed_value < 0) {
                        negative = 1;
                        value = (~((unsigned long long)signed_value)) + 1;
                    } else {
                        value = (unsigned long long)signed_value;
                    }
                } else {
                    if (length == 1) {
                        value = (unsigned long long)((unsigned char)va_arg(ap, unsigned int));
                    } else if (length == 2) {
                        value = (unsigned long long)((unsigned short)va_arg(ap, unsigned int));
                    } else if (length == 3) {
                        value = (unsigned long long)va_arg(ap, unsigned long);
                    } else if (length == 4) {
                        value = va_arg(ap, unsigned long long);
                    } else if (length == 5) {
                        value = (unsigned long long)va_arg(ap, size_t);
                    } else if (length == 6) {
                        value = va_arg(ap, unsigned long long);
                    } else {
                        value = (unsigned long long)va_arg(ap, unsigned int);
                    }
                }

                count = __svm_printf_emit_number(
                    out,
                    out_size,
                    count,
                    value,
                    negative,
                    is_signed,
                    base,
                    uppercase,
                    width,
                    precision,
                    left,
                    plus,
                    space,
                    alt,
                    zero,
                    pointer_format,
                    spec
                );
            } else {
                count = __svm_printf_emit(out, out_size, count, '%');
                count = __svm_printf_emit(out, out_size, count, spec);
            }
        }
    }

    if (out_size != 0) {
        if (count < out_size) {
            out[count] = 0;
        } else {
            out[out_size - 1] = 0;
        }
    }
    return (int)count;
}

int vsnprintf(char *out, size_t out_size, const char *fmt, va_list ap) {
    return __svm_vformat(out, out_size, fmt, ap);
}

int snprintf(char *out, size_t out_size, const char *fmt, ...) {
    va_list ap;
    int result;
    va_start(ap, fmt);
    result = __svm_vformat(out, out_size, fmt, ap);
    va_end(ap);
    return result;
}

int sprintf(char *out, const char *fmt, ...) {
    va_list ap;
    int result;
    va_start(ap, fmt);
    result = __svm_vformat(out, (size_t)-1, fmt, ap);
    va_end(ap);
    return result;
}

unsigned long long div64_u64(
    unsigned long long dividend,
    unsigned long long divisor
) {
    return dividend / divisor;
}

unsigned long long div_u64_rem(
    unsigned long long dividend,
    unsigned int divisor,
    unsigned int *remainder
) {
    unsigned long long quotient = dividend / (unsigned long long)divisor;
    *remainder = (unsigned int)(dividend % (unsigned long long)divisor);
    return quotient;
}
