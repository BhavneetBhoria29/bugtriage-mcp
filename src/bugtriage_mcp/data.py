"""Synthetic bug reports and ECU logs for a vehicle connectivity module.

Everything here is generated. There is no real automotive data in this repo.
The generator is deliberately noisy (shared vocabulary across components,
label noise, vague reporter wording) so the classifier has something real
to learn and the eval numbers are not trivially 100%.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

COMPONENTS = {
    "lte_modem": {
        "terms": ["LTE", "modem", "attach", "APN", "PDN", "RSRP", "cell reselection", "SIM", "registration", "AT command"],
        "errors": ["PDN_CONNECT_REJECT", "RRC_CONN_FAIL", "SIM_NOT_READY", "AT_TIMEOUT", "NAS_REJECT cause=15"],
        "module": "modem_mgr",
    },
    "wifi": {
        "terms": ["WiFi", "hotspot", "WPA2", "SSID", "DHCP", "access point", "5GHz", "client association", "beacon"],
        "errors": ["WLAN_ASSOC_FAIL", "DHCP_NO_LEASE", "HOSTAPD_RESTART", "FW_CRASH wlan0", "4WAY_HANDSHAKE_TIMEOUT"],
        "module": "wlan_d",
    },
    "bluetooth": {
        "terms": ["Bluetooth", "pairing", "A2DP", "HFP", "phone", "BLE", "bonding", "audio stream", "link key"],
        "errors": ["BT_PAIR_FAIL", "HCI_TIMEOUT", "L2CAP_DISCONNECT reason=0x13", "SDP_QUERY_FAIL", "LINK_KEY_MISSING"],
        "module": "bt_stack",
    },
    "ecall": {
        "terms": ["eCall", "emergency call", "MSD", "crash sensor", "PSAP", "SOS button", "voice channel", "112"],
        "errors": ["MSD_TX_FAIL", "ECALL_NO_NETWORK", "PSAP_ACK_TIMEOUT", "SOS_BTN_DEBOUNCE_ERR", "ECALL_AUDIO_PATH_ERR"],
        "module": "ecall_svc",
    },
    "ota": {
        "terms": ["OTA", "software update", "download", "package", "signature", "flash", "rollback", "delta update", "campaign"],
        "errors": ["OTA_SIG_INVALID", "OTA_DL_INTERRUPTED", "FLASH_WRITE_FAIL", "ROLLBACK_TRIGGERED", "MANIFEST_PARSE_ERR"],
        "module": "ota_agent",
    },
    "can_gateway": {
        "terms": ["CAN", "gateway", "bus off", "signal", "PDU", "wake-up", "sleep", "network management", "frame"],
        "errors": ["CAN_BUS_OFF", "NM_TIMEOUT", "PDU_ROUTING_ERR", "WAKEUP_REASON_UNKNOWN", "E2E_CRC_FAIL"],
        "module": "can_gw",
    },
}

# Vocabulary that shows up in every component so the task is not keyword lookup.
SHARED = ["connection", "timeout", "reset", "after ignition", "intermittent", "network", "restart",
          "customer complaint", "field report", "after update", "cold start", "reboot", "lost"]

SYMPTOMS = [
    "{t1} fails {s1} and does not recover until {s2}",
    "intermittent {t1} problem, {t2} {s1}",
    "customer reports {t1} not working {s1}; log shows {e}",
    "{t1} drops during drive, {t2} unstable, {s2} fixes it",
    "after {s1} the {t1} shows {e} repeatedly",
    "{e} observed on test bench, {t1} and {t2} affected",
    "{t1} slow, sometimes {s2} needed, related to {t2}?",
    "field report: {s1}, {t1} {s2}. not reproducible on bench",
]

SEVERITY_BY_COMPONENT = {  # eCall problems skew critical, WiFi skews minor
    "ecall": [0.55, 0.35, 0.10],
    "ota": [0.30, 0.50, 0.20],
    "can_gateway": [0.30, 0.45, 0.25],
    "lte_modem": [0.20, 0.50, 0.30],
    "bluetooth": [0.05, 0.40, 0.55],
    "wifi": [0.05, 0.35, 0.60],
}
SEVERITIES = ["critical", "major", "minor"]
LOG_LEVELS = ["INFO", "WARN", "ERROR"]


@dataclass
class Bug:
    id: str
    title: str
    description: str
    component: str
    severity: str
    root_cause_id: str  # bugs sharing a root cause are "duplicates" for retrieval eval
    created: str


@dataclass
class LogLine:
    ts: str
    level: str
    module: str
    code: str
    message: str
    vin_suffix: str


TRIGGERS = ["in tunnel exit", "below -15C", "with iPhone 15", "with Pixel 8", "at highway speed",
            "during roaming", "after deep sleep", "on 12V dip", "near cell edge", "with trailer attached",
            "after 30 min parking", "during fast charging", "on first boot after flash", "in parking garage",
            "when nav active", "during voice call", "with 3 phones paired", "on Band 20", "in Denmark",
            "after battery disconnect"]


def _signature(rng: random.Random) -> dict:
    """What duplicates of one root cause share in reality: a firmware build and a trigger condition."""
    return {"fw": f"FW {rng.randint(3, 5)}.{rng.randint(0, 9)}.{rng.randint(0, 40)}", "trigger": rng.choice(TRIGGERS)}


def _render(rng: random.Random, comp: str, root_err: str, sig: dict | None = None) -> tuple[str, str]:
    spec = COMPONENTS[comp]
    # 20% of the time borrow a term from another component: realistic confusion
    other = rng.choice([c for c in COMPONENTS if c != comp])
    t_pool = spec["terms"] + (COMPONENTS[other]["terms"][:2] if rng.random() < 0.2 else [])
    t1, t2 = rng.sample(t_pool, 2)
    s1, s2 = rng.sample(SHARED, 2)
    err = root_err if rng.random() < 0.7 else rng.choice(spec["errors"])
    desc = rng.choice(SYMPTOMS).format(t1=t1, t2=t2, s1=s1, s2=s2, e=err)
    if sig:  # reporters mention these inconsistently, so they are strong but imperfect signals
        if rng.random() < 0.65:
            desc += f", seen {sig['trigger']}"
        if rng.random() < 0.55:
            desc += f" ({sig['fw']})"
    title = f"{t1} {rng.choice(['issue', 'failure', 'not working', 'unstable', 'error'])}"
    if rng.random() < 0.15:  # vague reporter, component terms only in description
        title = rng.choice(["connectivity problem", "customer complaint", "field issue", "system error"])
    return title, desc


def generate_bugs(n: int = 900, seed: int = 7, label_noise: float = 0.05) -> list[Bug]:
    rng = random.Random(seed)
    comps = list(COMPONENTS)
    # Root causes: each owns one error code; 3-8 bugs per root cause
    bugs: list[Bug] = []
    start = datetime(2026, 1, 1)
    rc_idx = 0
    while len(bugs) < n:
        comp = rng.choice(comps)
        root_err = rng.choice(COMPONENTS[comp]["errors"])
        rc = f"RC-{rc_idx:04d}"
        rc_idx += 1
        sig = _signature(rng)
        for _ in range(rng.randint(3, 8)):
            if len(bugs) >= n:
                break
            title, desc = _render(rng, comp, root_err, sig)
            sev = rng.choices(SEVERITIES, weights=SEVERITY_BY_COMPONENT[comp])[0]
            label = comp if rng.random() > label_noise else rng.choice(comps)  # mislabeled tickets
            bugs.append(Bug(
                id=f"CONMOD-{len(bugs) + 1:05d}", title=title, description=desc,
                component=label, severity=sev, root_cause_id=rc,
                created=(start + timedelta(hours=rng.randint(0, 24 * 240))).isoformat(),
            ))
    rng.shuffle(bugs)
    return bugs


def generate_logs(n: int = 20000, seed: int = 11) -> list[LogLine]:
    rng = random.Random(seed)
    start = datetime(2026, 9, 1)
    lines = []
    for i in range(n):
        comp = rng.choice(list(COMPONENTS))
        spec = COMPONENTS[comp]
        level = rng.choices(LOG_LEVELS, weights=[0.75, 0.17, 0.08])[0]
        if level == "ERROR":
            code = rng.choice(spec["errors"])
            msg = f"{code} while {rng.choice(spec['terms'])} {rng.choice(SHARED)}"
        else:
            code = "OK" if level == "INFO" else "DEGRADED"
            msg = f"{rng.choice(spec['terms'])} {rng.choice(['state change', 'retry', 'heartbeat', 'metrics', 'handover'])}"
        lines.append(LogLine(
            ts=(start + timedelta(seconds=i * 7 + rng.randint(0, 6))).isoformat(),
            level=level, module=spec["module"], code=code, message=msg,
            vin_suffix=f"{rng.randint(0, 999):03d}",
        ))
    return lines


def write_dataset(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bugs.jsonl").write_text("\n".join(json.dumps(asdict(b)) for b in generate_bugs()) + "\n")
    (out_dir / "logs.jsonl").write_text("\n".join(json.dumps(asdict(l)) for l in generate_logs()) + "\n")


def load_bugs(path: Path) -> list[Bug]:
    return [Bug(**json.loads(l)) for l in path.read_text().splitlines() if l.strip()]


def load_logs(path: Path) -> list[LogLine]:
    return [LogLine(**json.loads(l)) for l in path.read_text().splitlines() if l.strip()]


if __name__ == "__main__":
    import os
    out = Path(os.environ.get("BUGTRIAGE_DATA", Path(__file__).resolve().parents[2] / "data"))
    write_dataset(out)
    print(f"wrote {out}/bugs.jsonl and {out}/logs.jsonl")
