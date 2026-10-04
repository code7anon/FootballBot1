from backend.app.services.edge import implied_probability, kelly_fraction
from backend.app.services.model import poisson_1x2

p = poisson_1x2(1.4, 1.0)
assert abs(sum(p) - 1) < 1e-6
assert abs(implied_probability(2.0) - 0.5) < 1e-9
assert kelly_fraction(0.60, 2.0) > 0
print('smoke tests OK')
