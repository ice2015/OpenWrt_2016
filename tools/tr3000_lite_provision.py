#!/usr/bin/env python3
"""Offline inventory validation and staging bundle rendering for TR3000 Lite."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys


def is_valid_b64_key(key: str) -> bool:
    if not isinstance(key, str) or len(key) != 44 or not key.endswith("="):
        return False
    try:
        decoded = base64.b64decode(key.encode("ascii"), validate=True)
        return len(decoded) == 32
    except Exception:
        return False


def is_valid_hostname(host: str) -> bool:
    if not host or len(host) > 253 or host.startswith((".", "-")) or host.endswith((".", "-")):
        return False
    allowed = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
    return all(allowed.match(x) for x in host.split("."))


def validate_inventory(data: dict) -> None:
    if data.get("schema_version") != 1:
        raise ValueError("Invalid schema_version; expected 1")
    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        raise ValueError("Inventory must contain non-empty 'devices' list")

    seen_ids = set()
    seen_hostnames = set()
    seen_direct_addrs = set()
    seen_vps_addrs = set()
    seen_peer_ips = set()

    for dev in devices:
        did = dev.get("device_id")
        if not did or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", did):
            raise ValueError(f"Invalid device_id: {did!r}")
        if did in seen_ids:
            raise ValueError(f"Duplicate device_id: {did}")
        seen_ids.add(did)

        host = dev.get("ddns_hostname")
        if not host or not is_valid_hostname(host):
            raise ValueError(f"Device {did}: invalid ddns_hostname {host!r}")
        if host in seen_hostnames:
            raise ValueError(f"Duplicate ddns_hostname: {host}")
        seen_hostnames.add(host)

        # direct_address
        da = dev.get("direct_address", "")
        if not da.endswith("/32"):
            raise ValueError(f"Device {did}: direct_address must be an IPv4 /32")
        ipaddress.IPv4Interface(da)
        if da in seen_direct_addrs:
            raise ValueError(f"Duplicate direct_address: {da}")
        seen_direct_addrs.add(da)

        # vps_address
        va = dev.get("vps_address", "")
        if not va.endswith("/32"):
            raise ValueError(f"Device {did}: vps_address must be an IPv4 /32")
        ipaddress.IPv4Interface(va)
        if va in seen_vps_addrs:
            raise ValueError(f"Duplicate vps_address: {va}")
        seen_vps_addrs.add(va)

        # port
        port = dev.get("direct_listen_port")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError(f"Device {did}: invalid direct_listen_port {port!r}")

        # vps_endpoint
        ep = dev.get("vps_endpoint", "")
        if ":" not in ep:
            raise ValueError(f"Device {did}: vps_endpoint must be host:port")
        ep_host, ep_port = ep.rsplit(":", 1)
        if not ep_port.isdigit() or not (1 <= int(ep_port) <= 65535):
            raise ValueError(f"Device {did}: invalid vps_endpoint port in {ep!r}")

        # vps_public_key
        vpk = dev.get("vps_public_key")
        if not is_valid_b64_key(vpk):
            raise ValueError(f"Device {did}: invalid vps_public_key")

        # device_public_keys
        dpk = dev.get("device_public_keys", {})
        if not is_valid_b64_key(dpk.get("direct")) or not is_valid_b64_key(dpk.get("vps")):
            raise ValueError(f"Device {did}: missing or invalid device_public_keys")

        # plant_cidr
        pc = dev.get("plant_cidr", "")
        if "/" not in pc:
            raise ValueError(f"Device {did}: invalid plant_cidr {pc!r}")
        ipaddress.IPv4Network(pc, strict=True)

        # check remote_peers
        for k in ("remote_peers", "vps_remote_peers"):
            for p in dev.get(k, []):
                pub = p.get("public_key")
                if not is_valid_b64_key(pub):
                    raise ValueError(f"Device {did}: invalid peer public_key {pub!r}")
                for ip in p.get("allowed_ips", []):
                    if not ip.endswith("/32"):
                        raise ValueError(f"Device {did}: peer allowed_ips must be exact /32, got {ip!r}")
                    ipaddress.IPv4Interface(ip)
                    if ip in seen_peer_ips:
                        raise ValueError(f"Duplicate or overlapping peer IP across inventory: {ip}")
                    seen_peer_ips.add(ip)


def render_device(data: dict, device_id: str, output_dir: Path) -> None:
    validate_inventory(data)
    target = None
    for d in data["devices"]:
        if d["device_id"] == device_id:
            target = d
            break
    if not target:
        raise ValueError(f"Device ID {device_id!r} not found in inventory")

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = output_dir / "bundle"
    bundle_dir.mkdir(mode=0o700, exist_ok=True)

    # 1. Render bundle configs
    # network config snippet for tr3000-lite
    network_lines = [
        f"config interface 'wg_direct'",
        f"\toption proto 'wireguard'",
        f"\toption listen_port '{target['direct_listen_port']}'",
        f"\tlist addresses '{target['direct_address']}'",
        "",
        f"config interface 'wg_vps'",
        f"\toption proto 'wireguard'",
        f"\tlist addresses '{target['vps_address']}'",
        "",
        f"config wireguard_wg_vps 'peer_vps'",
        f"\toption public_key '{target['vps_public_key']}'",
        f"\toption endpoint_host '{target['vps_endpoint'].split(':')[0]}'",
        f"\toption endpoint_port '{target['vps_endpoint'].split(':')[1]}'",
        f"\toption route_allowed_ips '1'",
        f"\toption persistent_keepalive '25'",
        f"\tlist allowed_ips '{target['vps_address']}'",
        "",
    ]
    for i, peer in enumerate(target.get("remote_peers", [])):
        network_lines.extend([
            f"config wireguard_wg_direct 'peer_direct_{i}'",
            f"\toption public_key '{peer['public_key']}'",
            f"\toption route_allowed_ips '1'",
        ])
        for ip in peer.get("allowed_ips", []):
            network_lines.append(f"\tlist allowed_ips '{ip}'")
        network_lines.append("")

    network_content = "\n".join(network_lines)
    network_file = bundle_dir / "network"
    network_file.write_text(network_content, encoding="utf-8")
    network_file.chmod(0o600)

    # remote access config snippet
    vps_sources = []
    for peer in target.get("vps_remote_peers", []):
        vps_sources.extend(peer.get("allowed_ips", []))
    remote_lines = [
        "config access 'access'",
        "\toption allow_luci '0'",
        "\toption allow_plant '0'",
    ]
    for s in vps_sources:
        remote_lines.append(f"\tlist vps_remote_source '{s}'")
    remote_lines.append("")
    remote_file = bundle_dir / "tr3000-lite-remote"
    remote_file.write_text("\n".join(remote_lines), encoding="utf-8")
    remote_file.chmod(0o600)

    # manifest
    manifest_files = {}
    for f in (network_file, remote_file):
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        manifest_files[f.name] = {"sha256": sha}

    manifest = {
        "schema_version": 1,
        "device_id": device_id,
        "files": manifest_files,
    }
    manifest_file = bundle_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_file.chmod(0o600)

    # 2. Render VPS snippet
    vps_dir = output_dir / "vps"
    vps_dir.mkdir(parents=True, exist_ok=True)
    vps_conf = [
        "# TR3000 Device Peer Snippet for VPS",
        "[Peer]",
        f"PublicKey = {target['device_public_keys']['vps']}",
        f"AllowedIPs = {target['vps_address']}",
        "",
    ]
    (vps_dir / "peer.conf").write_text("\n".join(vps_conf), encoding="utf-8")

    # 3. Render Windows client templates
    win_dir = output_dir / "windows"
    win_dir.mkdir(parents=True, exist_ok=True)

    direct_peer_ip = "10.10.1.250/32"
    if target.get("remote_peers") and target["remote_peers"][0].get("allowed_ips"):
        direct_peer_ip = target["remote_peers"][0]["allowed_ips"][0]

    vps_peer_ip = "10.20.1.250/32"
    if target.get("vps_remote_peers") and target["vps_remote_peers"][0].get("allowed_ips"):
        vps_peer_ip = target["vps_remote_peers"][0]["allowed_ips"][0]

    plant_cidr = target.get("plant_cidr", "192.168.10.0/24")

    direct_tmpl = [
        f"# exclusive_group={device_id}",
        "[Interface]",
        "PrivateKey = <CLIENT_PRIVATE_KEY_FILL_LOCALLY>",
        f"Address = {direct_peer_ip}",
        "DNS = 1.1.1.1",
        "",
        "[Peer]",
        f"PublicKey = {target['device_public_keys']['direct']}",
        f"Endpoint = {target['ddns_hostname']}:{target['direct_listen_port']}",
        f"AllowedIPs = {target['direct_address']}, {plant_cidr}",
        "",
    ]
    (win_dir / f"TR3000-{device_id}-Direct.conf").write_text("\n".join(direct_tmpl), encoding="utf-8")

    vps_tmpl = [
        f"# exclusive_group={device_id}",
        "[Interface]",
        "PrivateKey = <CLIENT_PRIVATE_KEY_FILL_LOCALLY>",
        f"Address = {vps_peer_ip}",
        "DNS = 1.1.1.1",
        "",
        "[Peer]",
        f"PublicKey = {target['vps_public_key']}",
        f"Endpoint = {target['vps_endpoint']}",
        f"AllowedIPs = {target['vps_address']}, {plant_cidr}",
        "",
    ]
    (win_dir / f"TR3000-{device_id}-VPS.conf").write_text("\n".join(vps_tmpl), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    val = sub.add_parser("validate", help="Validate offline inventory")
    val.add_argument("--inventory", required=True, type=Path)

    rnd = sub.add_parser("render", help="Render bundle and client templates")
    rnd.add_argument("--inventory", required=True, type=Path)
    rnd.add_argument("--device-id", required=True, type=str)
    rnd.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()

    if not args.inventory.is_file():
        sys.stderr.write(f"Error: inventory file not found: {args.inventory}\n")
        sys.exit(1)

    try:
        data = json.loads(args.inventory.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"Error parsing inventory JSON: {e}\n")
        sys.exit(1)

    try:
        if args.subcommand == "validate":
            validate_inventory(data)
            sys.exit(0)
        elif args.subcommand == "render":
            render_device(data, args.device_id, args.output)
            sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Validation/Render Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
