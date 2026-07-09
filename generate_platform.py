#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from scenario import SCENARIO


def replica_label(i: int, names: list[str]) -> str:
    if names and i < len(names):
        return names[i]
    return f"replica_{i}"


def generate_platform_xml(
    replicas: int,
    slots_per_replica: int,
    replica_speed: str = "1Gf",
    replica_core: int = 1,
    network_bandwidth: str = "100Gbps",
    network_latency: str = "1us",
    replica_names: list[str] | None = None,
) -> str:
    replica_names = replica_names or []
    hosts = []
    routes = []

    hosts.append('    <host id="master_host" speed="1Gf" core="1"/>')

    for r in range(replicas):
        label = escape(replica_label(r, replica_names))
        for s in range(slots_per_replica):
            host_id = f"replica_{r}_slot_{s}"
            hosts.append(
                f'    <host id="{host_id}" speed="{escape(replica_speed)}" core="{int(replica_core)}">\n'
                f'      <prop id="logical_replica" value="{r}"/>\n'
                f'      <prop id="replica_label" value="{label}"/>\n'
                f'      <prop id="slot" value="{s}"/>\n'
                f'    </host>'
            )

    link = f'    <link id="link0" bandwidth="{escape(network_bandwidth)}" latency="{escape(network_latency)}" />'

    for r in range(replicas):
        for s in range(slots_per_replica):
            host_id = f"replica_{r}_slot_{s}"
            routes.append(
                f'    <route src="master_host" dst="{host_id}">\n'
                f'      <link_ctn id="link0"/>\n'
                f'    </route>'
            )

    return "\n".join(
        [
            "<?xml version='1.0'?>",
            '<!DOCTYPE platform SYSTEM "https://simgrid.org/simgrid.dtd">',
            '<platform version="4.1">',
            '  <zone id="AS0" routing="Full">',
            *hosts,
            link,
            *routes,
            '  </zone>',
            '</platform>',
            '',
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    p = SCENARIO["platform"]
    replicas = int(p["replicas"])
    slots = int(p.get("slots_per_replica", 1))

    out = Path(args.out) if args.out else Path("platforms") / f"platform_{replicas}replicas_{slots}slots.xml"
    out.parent.mkdir(parents=True, exist_ok=True)

    xml = generate_platform_xml(
        replicas=replicas,
        slots_per_replica=slots,
        replica_speed=str(p.get("replica_speed", "1Gf")),
        replica_core=int(p.get("replica_core", 1)),
        network_bandwidth=str(p.get("network_bandwidth", "100Gbps")),
        network_latency=str(p.get("network_latency", "1us")),
        replica_names=list(p.get("replica_names", [])),
    )

    out.write_text(xml)
    print(f"Wrote platform: {out}")
    print(f"Logical replicas: {replicas}")
    print(f"Slots per replica: {slots}")
    print(f"Batsim compute resources: {replicas * slots}")


if __name__ == "__main__":
    main()