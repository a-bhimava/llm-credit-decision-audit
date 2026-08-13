"""Real provider adapters.

Nothing in this package may read :attr:`ModelRequest.env_state`. An adapter sees rendered text
and tool results, exactly as a hosted model would; reaching into the environment would let a
"real" run quietly cheat by consulting ground truth. ``tests/model/test_provider_isolation.py``
asserts this statically over every file here, in the same defence-by-static-check style as the
numeric lint in ``policy/loader.py``.

Provider SDKs are optional extras. Importing this package must not require them, so each
adapter imports its SDK inside its constructor and fails with an instruction rather than an
ImportError traceback.
"""
