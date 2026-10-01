import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent.parent / "deploy" / "cloudflare-sync" / "test" / "sync.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_the_sync_service_passes_its_own_tests():
    result = subprocess.run(["node", "--test", str(TESTS)], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fail 0" in result.stdout
