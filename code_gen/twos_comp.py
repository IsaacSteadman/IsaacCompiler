

def twos_comp(i, n_bits):
    sign = int(i < 0)
    if sign:
        i = abs(i)
        i -= 1
    bits = [0] * n_bits
    bits[0] = sign
    for c in range(n_bits - 1, 0, -1):
        bits[c] = (i & 1) ^ sign
        i >>= 1
    return bits
