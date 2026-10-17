"""Create a verified did-to-device registry from a Geek backup or MijiaFlow read."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mijia_rule_kit import unpack_bak  # noqa: E402


def rule_name(rule: dict) -> str:
    return rule.get("cfg", {}).get("userData", {}).get("name", "")


def model_from_urn(urn: str | None) -> str | None:
    parts = (urn or "").split(":")
    return parts[5] if len(parts) > 5 else None


def references(snapshot: dict) -> dict[str, dict]:
    devices: dict[str, dict] = {}
    for rule in snapshot.get("rules", []):
        for node in rule.get("nodes", []):
            props, cfg = node.get("props", {}), node.get("cfg", {})
            did = props.get("did")
            if not did:
                continue
            urn = cfg.get("urn")
            item = devices.setdefault(
                str(did),
                {
                    "did": str(did),
                    "urn": urn,
                    "model": model_from_urn(urn),
                    "name": None,
                    "room": None,
                    "channels": [],
                    "status": "unresolved",
                    "evidence": [{"source": "backup"}],
                    "references": [],
                },
            )
            item["references"].append(
                {
                    "ruleId": str(rule.get("id", "")),
                    "ruleName": rule_name(rule),
                    "nodeId": node.get("id"),
                    "nodeType": node.get("type"),
                    "siid": props.get("siid"),
                    "piid": props.get("piid"),
                    "aiid": props.get("aiid"),
                    "eiid": props.get("eiid"),
                }
            )
    return devices


def blank_device(did: str, urn: str | None = None) -> dict:
    return {
        "did": did,
        "urn": urn,
        "model": model_from_urn(urn),
        "name": None,
        "room": None,
        "channels": [],
        "status": "unresolved",
        "evidence": [],
        "references": [],
    }


def merge_mijiaflow_devices(devices: dict[str, dict], path: Path) -> None:
    """Merge a saved ``mijia_read(resource='devices')`` result.

    MijiaFlow receives the complete device dictionary in one authenticated
    gateway response, so its did/name/room association is direct evidence.
    It does not expose user-assigned per-channel labels; retain channels only
    when those labels were observed elsewhere.
    """
    document = json.loads(path.read_text("utf-8"))
    # 不同 AI 保存工具结果的方式不一样：可能带 structuredContent 外壳，也可能存成列表。
    for _ in range(3):  # 剥掉常见外壳：structuredContent / data / MCP content[0].text
        if not isinstance(document, dict):
            break
        if isinstance(document.get("structuredContent"), dict):
            document = document["structuredContent"]
        elif isinstance(document.get("data"), (dict, list)):
            document = document["data"]
        elif isinstance(document.get("content"), list) and document["content"] and isinstance(document["content"][0], dict) \
                and isinstance(document["content"][0].get("text"), str):
            document = json.loads(document["content"][0]["text"])
        else:
            break
    entries = document.get("devices", document) if isinstance(document, dict) else document
    if isinstance(entries, list):
        entries = {str(x.get("did")): x for x in entries if isinstance(x, dict) and x.get("did")}
    if not isinstance(entries, dict) or not entries:
        raise ValueError("MijiaFlow 设备文件应为以 did 为键的 JSON 对象，或带 did 字段的设备列表")
    for raw_did, raw in entries.items():
        if not isinstance(raw, dict):
            raise ValueError(f"MijiaFlow 设备 {raw_did} 格式无效")
        did = str(raw_did)
        urn = raw.get("urn")
        item = devices.setdefault(did, blank_device(did, urn))
        item["urn"] = urn or item.get("urn")
        item["model"] = raw.get("model") or item.get("model") or model_from_urn(item["urn"])
        item["name"] = raw.get("name")
        item["room"] = raw.get("roomName")
        item["status"] = "confirmed"
        item["evidence"] = [{"source": "mijiaflow", "method": "getDevList"}]
        item["live"] = {
            key: raw[key]
            for key in ("modelName", "roomId", "online", "pushAvailable", "specV2Access", "specV3Access")
            if key in raw
        }


def parse_assignment(text: str) -> tuple[str, str, str | None, list[str]]:
    try:
        did, detail = text.split("=", 1)
        name, room, *channels = [part.strip() for part in detail.split("|")]
    except ValueError as error:
        raise ValueError("--set 格式应为 DID=设备名|房间|按键1,按键2") from error
    if not did or not name:
        raise ValueError("--set 必须提供 did 和设备名")
    channel_names = [x.strip() for x in (channels[0].split(",") if channels else []) if x.strip()]
    return did.strip(), name, room or None, channel_names


def main() -> None:
    parser = argparse.ArgumentParser(description="从 .bak 或 MijiaFlow 设备读取创建 did 台账")
    parser.add_argument("backup", nargs="?", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--mijiaflow-devices", type=Path, metavar="DEVICES.json",
        help="保存的 MijiaFlow mijia_read(devices) 结果；直接确认 did、名称与房间",
    )
    parser.add_argument(
        "--set", action="append", default=[], metavar="DID=名称|房间|按键1,按键2",
        help="仅用于已在网关页面逐项确认的映射",
    )
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # 非中文 Windows 控制台
    except Exception:
        pass

    if args.backup is None and args.mijiaflow_devices is None:
        parser.error("需要提供 .bak 或 --mijiaflow-devices")
    snapshot = unpack_bak(args.backup) if args.backup else {"rules": []}
    output = args.out or (args.backup.with_name("设备台账.json") if args.backup else Path("设备台账.json"))
    previous = {}
    if output.exists():
        previous = {str(x["did"]): x for x in json.loads(output.read_text("utf-8")).get("devices", [])}

    devices = references(snapshot)
    for did, current in devices.items():
        old = previous.get(did, {})
        for key in ("name", "room", "channels", "status", "evidence"):
            if old.get(key):
                current[key] = old[key]

    if args.mijiaflow_devices:
        merge_mijiaflow_devices(devices, args.mijiaflow_devices)
    # 重新读取设备时保留之前用 --set 确认过的按键名（MijiaFlow 不提供按键名）
    for did, old in previous.items():
        if did in devices and old.get("channels") and not devices[did].get("channels"):
            devices[did]["channels"] = old["channels"]

    for assignment in args.set:
        did, name, room, channels = parse_assignment(assignment)
        if did not in devices:
            raise ValueError(f"{did} 不在备份引用或 MijiaFlow 读取的设备中，不能写入台账")
        devices[did].update(
            {
                "name": name,
                "room": room,
                "channels": channels,
                "status": "confirmed",
                "evidence": [{"source": "gateway-ui", "method": "operator-confirmed"}],
            }
        )

    registry = {
        "schemaVersion": 2,
        "sourceBackup": args.backup.name if args.backup else None,
        "sourceMijiaFlowDevices": args.mijiaflow_devices.name if args.mijiaflow_devices else None,
        "devices": sorted(devices.values(), key=lambda item: item["did"]),
    }
    output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unresolved = sum(item["status"] != "confirmed" for item in registry["devices"])
    print(f"{output}: {len(registry['devices'])} 个设备，{unresolved} 个待确认")


if __name__ == "__main__":
    main()
