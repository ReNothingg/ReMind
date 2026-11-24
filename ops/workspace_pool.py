import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Generate an additional ReMind Compose workspace pool")
parser.add_argument("slots", type=int, choices=range(2, 257), metavar="2..256")
parser.add_argument("output", type=Path)
parser.add_argument("--development", action="store_true")
args = parser.parse_args()
servers = [f"workspace-{n}" for n in range(1, args.slots + 1)]
app = "backend" if args.development else "app"
networks = {f"agent-slot-{n}": {"internal": True} for n in range(3, args.slots + 1)}
volumes = {f"workspace_{n}_data": {} for n in range(3, args.slots + 1)}
services = {
    app: {"environment": {"AGENT_SLOT_COUNT": str(args.slots)}},
    "agent-router": {
        "environment": {
            "AGENT_SLOT_TARGETS": ",".join("http://" + name + ":8092" for name in servers)
        },
        "networks": list(networks),
    },
}
if not args.development:
    services["telegram-bot"] = {"environment": {"AGENT_SLOT_COUNT": str(args.slots)}}
for n in range(3, args.slots + 1):
    services[f"workspace-{n}"] = {
        "image": "remind-workspace:local",
        "command": ["node", "/opt/remind/codex/slot.mjs"],
        "restart": "unless-stopped",
        "read_only": True,
        "cap_drop": ["ALL"],
        "cap_add": ["SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 256,
        "mem_limit": "${AGENT_SLOT_MEMORY:-1536m}",
        "cpus": "${AGENT_SLOT_CPUS:-1.5}",
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=192m"],
        "environment": {
            "REMIND_SLOT_ID": str(n),
            "REMIND_CONTROL_URL": "http://agent-router:8090/control/",
            "REMIND_EGRESS_PROXY": "http://agent-router:8090",
        },
        "networks": [f"agent-slot-{n}"],
        "volumes": [f"workspace_{n}_data:/data"],
        "healthcheck": {
            "test": [
                "CMD",
                "node",
                "-e",
                "fetch('http://127.0.0.1:8092/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
            ],
            "interval": "30s",
            "timeout": "5s",
            "retries": 3,
        },
    }
args.output.write_text(
    json.dumps({"services": services, "networks": networks, "volumes": volumes}, indent=2) + "\n"
)
