"""Fixed, read-only Linux diagnostics; no elevated privileges or third-party packages."""
import json
import math
import os
from pathlib import Path
import subprocess

USB_ROOT = Path('/sys/bus/usb/devices')
WIRELESS_PATH = Path('/proc/net/wireless')


def _command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=5,
                                env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_COLORS': '0'})
        if result.returncode:
            return None, result.stderr.strip() or f'{args[0]} exited with status {result.returncode}'
        return result.stdout, None
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def _wireless_signals():
    try:
        lines = WIRELESS_PATH.read_text(errors='replace').splitlines()
        if len(lines) < 2 or 'Inter-' not in lines[0]:
            raise ValueError('Unrecognized /proc/net/wireless format')
        signals = {}
        for line in lines[2:]:
            if not line.strip():
                continue
            name, raw = line.split(':', 1)
            level = float(raw.split()[2].rstrip('.'))
            # Wireless extensions can expose signed dBm as an unsigned byte.
            if 63 < level <= 255:
                level -= 256
            signals[name.strip()] = level if math.isfinite(level) and -255 < level < 0 else None
        return signals, None
    except (OSError, ValueError, IndexError) as exc:
        return {}, str(exc)


def network_details():
    signals, wifi_error = _wireless_signals()
    result = dict(available=False, error=None, interfaces=[],
                  wifi_available=wifi_error is None, wifi_error=wifi_error)
    output, error = _command(['ip', '-j', 'address', 'show'])
    if error:
        result['error'] = error
        result['interfaces'] = [dict(name=name, addresses=[], signal_dbm=level)
                                for name, level in signals.items()]
        return result
    try:
        interfaces = json.loads(output)
        if not isinstance(interfaces, list):
            raise ValueError('Expected an interface list from ip')
        for interface in interfaces:
            name = interface['ifname']
            if not isinstance(name, str):
                raise ValueError('Invalid interface name')
            addresses = []
            for addr in interface.get('addr_info', []):
                if addr.get('family') in ('inet', 'inet6'):
                    local, prefix = addr['local'], addr['prefixlen']
                    if not isinstance(local, str) or not isinstance(prefix, int):
                        raise ValueError('Invalid IP address data')
                    addresses.append(f'{local}/{prefix}')
            result['interfaces'].append(dict(name=name, addresses=addresses,
                                             signal_dbm=signals.get(name)))
        result['available'] = True
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result['interfaces'] = []
        result['error'] = f'Unable to parse IP addresses: {exc}'
    return result


def failed_services():
    output, error = _command(['systemctl', '--failed', '--type=service',
                              '--no-pager', '--no-legend', '--plain'])
    result = dict(available=False, error=error, units=[])
    if error:
        return result
    try:
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.lstrip().removeprefix('●').strip().split(None, 4)
            if len(fields) < 4 or not fields[0].endswith('.service'):
                raise ValueError('Unrecognized systemctl service row')
            name, load, active, sub = fields[:4]
            result['units'].append(dict(name=name, load=load, active=active,
                                        sub=sub, description=fields[4] if len(fields) == 5 else ''))
        result['available'] = True
    except ValueError as exc:
        result['units'] = []
        result['error'] = str(exc)
    return result


def process_rankings():
    """ps %CPU is a process lifetime average; 100% represents one CPU core."""
    output, error = _command(['ps', '-eo', 'pid=,comm=,pcpu=,pmem=,rss='])
    result = dict(available=False, error=error, cpu_top=[], memory_top=[], total=0,
                  cpu_basis='lifetime_average_one_core_100_percent')
    if error:
        return result
    try:
        processes = []
        for line in output.splitlines():
            if not line.strip():
                continue
            identity, cpu, memory, rss = line.rsplit(None, 3)
            pid, name = identity.split(None, 1)
            process = dict(pid=int(pid), name=name.strip(), cpu_percent=float(cpu),
                           memory_percent=float(memory), rss_bytes=int(rss) * 1024)
            if (process['pid'] < 1 or process['rss_bytes'] < 0 or
                    not all(math.isfinite(process[key]) and process[key] >= 0
                            for key in ('cpu_percent', 'memory_percent'))):
                raise ValueError('Invalid process resource value')
            processes.append(process)
        if not processes:
            raise ValueError('ps returned no visible processes')
        result.update(available=True, total=len(processes),
                      cpu_top=sorted(processes, key=lambda p: (-p['cpu_percent'], p['pid']))[:10],
                      memory_top=sorted(processes, key=lambda p: (-p['rss_bytes'], p['pid']))[:10])
    except (ValueError, TypeError) as exc:
        result['error'] = f'Unable to parse process list: {exc}'
    return result


def _optional_text(path):
    try:
        return path.read_text(errors='replace').strip() or None
    except OSError:
        return None


def usb_devices():
    result = dict(available=False, error=None, devices=[])
    try:
        entries = sorted(USB_ROOT.iterdir())
    except OSError as exc:
        result['error'] = str(exc)
        return result
    skipped = 0
    for entry in entries:
        if ':' in entry.name:
            continue
        try:
            vendor = (entry / 'idVendor').read_text().strip()
            product_id = (entry / 'idProduct').read_text().strip()
            if len(vendor) != 4 or len(product_id) != 4:
                raise ValueError('Invalid USB identifier')
            int(vendor, 16)
            int(product_id, 16)
            bus = int((entry / 'busnum').read_text().strip())
            device = int((entry / 'devnum').read_text().strip())
        except FileNotFoundError:
            # A device may be unplugged during collection.
            continue
        except (OSError, ValueError):
            skipped += 1
            continue
        speed = _optional_text(entry / 'speed')
        try:
            speed = float(speed) if speed is not None else None
            if speed is not None and (not math.isfinite(speed) or speed < 0):
                speed = None
        except ValueError:
            speed = None
        result['devices'].append(dict(path=entry.name, vendor_id=vendor, product_id=product_id,
                                      manufacturer=_optional_text(entry / 'manufacturer'),
                                      product=_optional_text(entry / 'product'),
                                      bus=bus, device=device, speed_mbps=speed))
    result['available'] = True
    if skipped:
        result['error'] = f'{skipped} USB device(s) had unreadable or invalid descriptors'
    return result
