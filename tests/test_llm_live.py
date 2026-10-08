"""One real API call on one fixture. Excluded by default; run with `uv run pytest -m live`."""

from pathlib import Path

import pytest
import yaml

from coverage_readiness.llm.client import AnthropicClient, RunLog
from coverage_readiness.llm.mapper import map_application
from coverage_readiness.schema import ControlId

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.live
def test_live_map_application_acme_carrier_a(tmp_path):
    carrier = yaml.safe_load((FIXTURES / "carriers" / "carrier_a.yaml").read_text())
    app_path = FIXTURES / "businesses" / "acme_dental" / "application_carrier_a.yaml"
    application = yaml.safe_load(app_path.read_text())
    log = RunLog(tmp_path / "live.jsonl")

    claims = {
        c.control_id: c for c in map_application(AnthropicClient(), carrier, application, log)
    }

    assert claims[ControlId.MFA_EMAIL].value is True
    assert claims[ControlId.EDR_ALL_ENDPOINTS].value is True
    assert claims[ControlId.CRITICAL_PATCH_DAYS].value == 14
    [record] = log.read()
    assert record["ok"] and record["input_tokens"] > 0 and record["cost_usd"] > 0
