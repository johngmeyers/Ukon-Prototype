"""EDR device inventory (JSON) -> fraction of endpoints with an active agent."""

import json
from pathlib import Path

from coverage_readiness.parsers import EvidenceParseError
from coverage_readiness.schema import ControlId, EvidencedControl


def parse_edr_inventory(path: Path) -> list[EvidencedControl]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise EvidenceParseError(path, f"cannot read file ({e.strerror})") from e
    except json.JSONDecodeError as e:
        raise EvidenceParseError(path, f"invalid JSON at line {e.lineno}: {e.msg}") from e

    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list) or not devices:
        raise EvidenceParseError(path, "expected a non-empty 'devices' list")
    for i, device in enumerate(devices):
        if not isinstance(device, dict) or not {"hostname", "agent_status"} <= device.keys():
            raise EvidenceParseError(path, f"device {i}: missing 'hostname' or 'agent_status'")

    gaps = [d for d in devices if d["agent_status"] != "active"]
    active, total = len(devices) - len(gaps), len(devices)
    coverage = active / total
    vendor = data.get("vendor", "EDR")
    detail = f"{vendor} active on {active} of {total} devices ({coverage:.0%})"
    if gaps:
        detail += "; gaps: " + ", ".join(f"{d['hostname']} ({d['agent_status']})" for d in gaps)
    return [
        EvidencedControl(
            control_id=ControlId.EDR_ALL_ENDPOINTS,
            value=coverage,
            source=path.name,
            detail=detail,
        )
    ]
