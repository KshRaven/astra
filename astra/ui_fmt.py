"""Tiny formatting helpers shared by extensions."""


def human(n):
    n, i = float(n or 0), 0
    while n >= 1024 and i < 5:
        n /= 1024
        i += 1
    return (f"{n:.0f}" if i == 0 else f"{n:.1f}") + " " + ("B", "KB", "MB", "GB", "TB", "PB")[i]
