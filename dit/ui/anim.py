"""Easing curves and a small spring for the card stack."""
import math


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def progress(now, start, duration):
    if duration <= 0:
        return 1.0
    return clamp((now - start) / duration)


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    return t ** 3


def ease_in_out_cubic(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t, overshoot=1.4):
    c3 = overshoot + 1
    return 1 + c3 * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def ease_out_expo(t):
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def pulse(now, period=1.4):
    return 0.5 - 0.5 * math.cos(2 * math.pi * (now % period) / period)


def mix(c1, c2, t):
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


def with_alpha(color, alpha_mult):
    r, g, b, a = color
    return (r, g, b, int(clamp(alpha_mult) * a))


class Spring:
    """Critically-damped-ish spring: smooth reflow when cards above appear, grow, or leave."""

    def __init__(self, value, stiffness=420.0, damping=38.0):
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0
        self.stiffness = stiffness
        self.damping = damping

    def step(self, dt):
        steps = max(1, int(dt / 0.008))
        h = dt / steps
        for _ in range(steps):
            force = self.stiffness * (self.target - self.value) - self.damping * self.velocity
            self.velocity += force * h
            self.value += self.velocity * h
        if abs(self.target - self.value) < 0.05 and abs(self.velocity) < 0.5:
            self.value, self.velocity = self.target, 0.0

    def snap(self, value=None):
        self.value = self.target = float(self.target if value is None else value)
        self.velocity = 0.0

    @property
    def settled(self):
        return self.value == self.target and self.velocity == 0.0
