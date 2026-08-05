"""Failed profiles must not go back into the pool, or the poisoned state sticks."""

import os
import tempfile

import solver


def test_profile_recycling() -> None:
    root = tempfile.mkdtemp()
    os.environ["TS_PROFILE_DIR"] = os.path.join(root, "p")
    solver._profile_pool.clear()

    good = solver._acquire_profile()
    os.makedirs(good, exist_ok=True)
    solver._release_profile(good, keep=True)
    assert solver._acquire_profile() == good

    bad = solver._acquire_profile()
    os.makedirs(bad, exist_ok=True)
    solver._release_profile(bad, keep=False)
    assert not os.path.exists(bad)
    assert bad not in solver._profile_pool


if __name__ == "__main__":
    test_profile_recycling()
    print("ok")
