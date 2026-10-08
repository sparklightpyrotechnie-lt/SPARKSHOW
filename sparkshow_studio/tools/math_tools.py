import itertools

import numpy as np


def get_prime_factors(n: int) -> list[int]:
    i = 2
    factors: list[int] = []
    while i * i <= n:
        if n % i:
            i += 1
        else:
            n //= i
            factors.append(i)
    if n > 1:
        factors.append(n)
    return factors


def get_divisors(n: int) -> set[int]:
    prime_factors = get_prime_factors(n)

    divisors = {1}
    for i in range(len(prime_factors)):
        for divisor_factors in itertools.combinations(prime_factors, i + 1):
            divisor = int(np.prod(divisor_factors))
            divisors.add(divisor)
    return divisors


def get_filtered_divisors(n: int, max_divisor: int) -> list[int]:
    divisors = get_divisors(n)
    return sorted(filter(lambda x: x <= max_divisor and n // x <= max_divisor, divisors))
