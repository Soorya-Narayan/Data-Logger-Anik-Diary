"""
PLC Auto-Detection and Tag Discovery Module for Allen-Bradley Micro850.
Supports EtherNet/IP broadcast discovery and online tag listing via pylogix.
"""

import re
import json
import yaml
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config/config.yaml"
TAGS_PATH = PROJECT_ROOT / "config/tags.json"

# Heuristic patterns for automatic tag matching matching canonical keys in tags.json
TAG_MATCH_RULES = {
    "milk_flow": [
        r"flow.*rate", r"fit.*101", r"fit_101", r"milk.*flow", r"flow", r"lph", r"discharge"
    ],
    "holding_in_temp": [
        r"holding.*in", r"tt.*101", r"tt_101", r"temp.*in", r"inlet.*temp", r"pasteur.*in"
    ],
    "holding_out_temp": [
        r"holding.*out", r"tt.*102", r"tt_102", r"temp.*out", r"outlet.*temp", r"pasteur.*out"
    ],
    "product": [
        r"recipe.*product", r"product.*name", r"recipe", r"batch.*name", r"product", r"prod.*id", r"material"
    ],
    "status": [
        r"system.*process", r"process.*status", r"status.*desc", r"sys.*status"
    ],
    "fdv1_status": [
        r"fdv1.*forward", r"fdv.*1", r"fdv1", r"divert.*1", r"inlet.*divert", r"valve.*1"
    ],
    "fdv1_reason": [
        r"fdv1.*reason", r"divert1.*reason"
    ],
    "fdv2_status": [
        r"fdv2.*forward", r"fdv.*2", r"fdv2", r"divert.*2", r"outlet.*divert", r"valve.*2"
    ],
    "fdv2_reason": [
        r"fdv2.*reason", r"divert2.*reason"
    ],
    "cip_status": [
        r"cip.*active", r"cip.*system", r"cip.*status", r"cip.*state", r"cip.*mode", r"cip"
    ],
    "cip_step": [
        r"cip.*step", r"cip.*phase"
    ]
}


def discover_plcs_on_network() -> List[Dict[str, Any]]:
    """
    Broadcasts EtherNet/IP ListIdentity requests (port 44818) to discover
    all Allen-Bradley / Rockwell PLCs on the local subnet.
    """
    devices = []
    try:
        from pylogix import PLC
        comm = PLC()
        response = comm.Discover()
        if response and response.Value:
            for dev in response.Value:
                devices.append({
                    "ip": getattr(dev, "IPAddress", None) or getattr(dev, "IP", "Unknown"),
                    "product_name": getattr(dev, "ProductName", "Unknown"),
                    "vendor": getattr(dev, "Vendor", "Rockwell Automation/Allen-Bradley"),
                    "revision": getattr(dev, "Revision", ""),
                    "serial": getattr(dev, "SerialNumber", "")
                })
        comm.Close()
    except Exception as exc:
        print(f"[Discovery Error] Broadcast scan failed: {exc}")
    
    return devices


def fetch_tags_from_plc(ip_address: str, is_micro800: bool = True) -> Dict[str, Any]:
    """
    Connects to the specified PLC and extracts all Controller/Program tags.
    Returns dictionary with raw tag list and best-match suggestions.
    """
    tags_found = []
    error = None

    try:
        from pylogix import PLC
        comm = PLC()
        comm.IPAddress = ip_address
        comm.Micro800 = is_micro800
        comm.SocketTimeout = 4.0

        resp = comm.GetTagList(allTags=True)
        if resp and resp.Value:
            for t in resp.Value:
                tag_name = getattr(t, "TagName", str(t))
                data_type = getattr(t, "DataType", "UNKNOWN")
                tags_found.append({
                    "name": tag_name,
                    "data_type": str(data_type)
                })
        elif resp and resp.Status:
            error = f"PLC returned status: {resp.Status}"
        else:
            error = "No tags returned or connection timed out."
        comm.Close()
    except Exception as exc:
        error = str(exc)

    # Sort tags alphabetically
    tags_found.sort(key=lambda x: x["name"].lower())

    # Generate heuristic match suggestions
    all_names = [t["name"] for t in tags_found]
    suggestions = auto_match_tags(all_names)

    return {
        "ip": ip_address,
        "success": len(tags_found) > 0,
        "total_tags": len(tags_found),
        "tags": tags_found,
        "suggestions": suggestions,
        "error": error
    }


def auto_match_tags(tag_names: List[str]) -> Dict[str, Optional[str]]:
    """
    Matches discovered PLC tag names to required Pasteurizer SCADA fields
    using regex and keyword heuristics.
    """
    matched: Dict[str, Optional[str]] = {}

    for field, patterns in TAG_MATCH_RULES.items():
        best_match = None
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)
            for name in tag_names:
                if regex.search(name):
                    best_match = name
                    break
            if best_match:
                break
        matched[field] = best_match

    return matched


def test_tag_read(ip_address: str, tag_mapping: Dict[str, str], is_micro800: bool = True) -> Dict[str, Any]:
    """
    Attempts to read all mapped tags once from the PLC to verify live data.
    """
    results = {}
    errors = {}

    try:
        from pylogix import PLC
        comm = PLC()
        comm.IPAddress = ip_address
        comm.Micro800 = is_micro800
        comm.SocketTimeout = 4.0

        for field, tag_name in tag_mapping.items():
            if not tag_name:
                continue
            try:
                ret = comm.Read(tag_name)
                if ret and ret.Status == "Success":
                    results[field] = {
                        "tag": tag_name,
                        "value": ret.Value,
                        "status": "OK"
                    }
                else:
                    errors[field] = {
                        "tag": tag_name,
                        "status": getattr(ret, "Status", "Read Failed")
                    }
            except Exception as e:
                errors[field] = {
                    "tag": tag_name,
                    "status": str(e)
                }
        comm.Close()
    except Exception as exc:
        return {
            "success": False,
            "error": f"Connection failed to {ip_address}: {exc}",
            "results": results,
            "errors": errors
        }

    return {
        "success": len(results) > 0,
        "results": results,
        "errors": errors
    }


def save_and_apply_plc_config(
    ip_address: str,
    tag_mapping: Dict[str, str],
    mode: str = "live",
    restart_service: bool = True
) -> Dict[str, Any]:
    """
    Saves the new IP and Tag mapping to config/config.yaml and config/tags.json,
    and restarts the poller service if requested.
    """
    # 1. Update config/tags.json preserving {"_comment": ..., "tags": {...}} structure
    existing_tags = {}
    if TAGS_PATH.exists():
        try:
            with open(TAGS_PATH, "r") as f:
                existing_tags = json.load(f)
        except Exception:
            existing_tags = {}

    if "tags" not in existing_tags or not isinstance(existing_tags["tags"], dict):
        existing_tags["tags"] = {}

    for field, plc_tag in tag_mapping.items():
        if not plc_tag:
            continue
        if field in existing_tags["tags"] and isinstance(existing_tags["tags"][field], dict):
            existing_tags["tags"][field]["plc_tag"] = plc_tag
        else:
            dtype = "REAL" if ("temp" in field or "flow" in field) else ("BOOL" if "status" in field else "STRING")
            unit = "°C" if "temp" in field else ("L/hr" if "flow" in field else "")
            existing_tags["tags"][field] = {
                "plc_tag": plc_tag,
                "data_type": dtype,
                "unit": unit,
                "description": f"Configured {field} sensor/actuator"
            }

    with open(TAGS_PATH, "w") as f:
        json.dump(existing_tags, f, indent=2)

    # 2. Update config/config.yaml
    config_data = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                config_data = yaml.safe_load(f) or {}
        except Exception:
            config_data = {}

    if "plc" not in config_data:
        config_data["plc"] = {}

    config_data["plc"]["ip"] = ip_address
    config_data["plc"]["mode"] = mode.lower()

    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config_data, f, default_flow_style=False)

    # 3. Restart poller service if running under systemd
    restarted = False
    restart_err = None
    if restart_service:
        try:
            res = subprocess.run(
                ["sudo", "systemctl", "restart", "pasteurizer-poller.service"],
                capture_output=True,
                text=True,
                timeout=10
            )
            restarted = res.returncode == 0
            if not restarted:
                restart_err = res.stderr
        except Exception as e:
            restart_err = str(e)

    return {
        "success": True,
        "mode": mode,
        "ip": ip_address,
        "tags_saved": len(tag_mapping),
        "service_restarted": restarted,
        "service_error": restart_err
    }
