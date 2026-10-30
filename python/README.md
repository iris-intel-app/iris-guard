# iris-guard (Python)

Stop buying bundled tokens. One line before every buy.

```python
from iris_guard import create_guard

guard = create_guard()  # reads IRIS_API_KEY; without one, free mode
if not guard.check(mint).allow:
    return
```

The full documentation (policy, free and full mode, examples, CLI) is in the repository's main
README. Pricing and API keys: https://iriscan.app/pricing.

CLI: `python -m iris_guard <mint>` (or `iris-guard <mint>` once installed) prints ALLOW or BLOCK
and exits 0 or 1.
