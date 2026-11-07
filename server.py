#!/usr/bin/env python3
"""Read-only LAN prototype. Python standard library only; run as an ordinary user."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
import diagnostics
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

BASE = Path(__file__).resolve().parent


def read_text(path):
    return Path(path).read_text(errors='replace').strip()


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=5)
        return {'available': p.returncode == 0, 'output': p.stdout.strip(),
                'error': p.stderr.strip() if p.returncode else None}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'output': '', 'error': str(exc)}


def cpu_ticks():
    values = list(map(int, read_text('/proc/stat').splitlines()[0].split()[1:]))
    # guest/guest_nice are already included in user/nice.
    return sum(values[:8]), values[3] + values[4]


def system_info():
    total1, idle1 = cpu_ticks()
    time.sleep(0.15)
    total2, idle2 = cpu_ticks()
    delta = total2 - total1
    memory = {}
    for line in read_text('/proc/meminfo').splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0]) * 1024
    disks = []
    for label, path in [('系統磁碟', '/'), ('開發磁碟', str(BASE))]:
        usage = shutil.disk_usage(path)
        disks.append(dict(label=label, path=path, total=usage.total,
                          used=usage.used, free=usage.free))
    network = []
    for line in read_text('/proc/net/dev').splitlines()[2:]:
        name, values = line.split(':', 1)
        values = values.split()
        name = name.strip()
        state = Path('/sys/class/net') / name / 'operstate'
        try:
            interface_state = read_text(state)
        except OSError:
            interface_state = 'unavailable'
        network.append(dict(name=name, rx_bytes=int(values[0]), tx_bytes=int(values[8]),
                            state=interface_state))
    temperatures = []
    for zone in sorted(Path('/sys/class/thermal').glob('thermal_zone*')):
        try:
            temperatures.append({'name': read_text(zone / 'type'),
                                 'celsius': int(read_text(zone / 'temp')) / 1000})
        except (OSError, ValueError):
            continue
    model = Path('/sys/firmware/devicetree/base/model')
    return dict(timestamp=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                hostname=socket.gethostname(), kernel=platform.release(),
                os=platform.freedesktop_os_release().get('PRETTY_NAME', platform.system()),
                model=read_text(model).rstrip('\x00') if model.exists() else platform.machine(),
                uptime_seconds=float(read_text('/proc/uptime').split()[0]),
                cpu=dict(count=os.cpu_count(), percent=round(100 * (1 - (idle2-idle1)/delta), 1) if delta else 0,
                         load_average=list(os.getloadavg())),
                memory=dict(total=memory['MemTotal'], available=memory['MemAvailable'],
                            used=memory['MemTotal']-memory['MemAvailable'],
                            swap_total=memory['SwapTotal'], swap_free=memory['SwapFree']),
                disks=disks, network=network, temperatures=temperatures,
                throttled=command(['vcgencmd', 'get_throttled']))


def dmesg_info(lines):
    result = command(['dmesg', '--color=never'])
    content = result.pop('output').splitlines()
    result.update(lines=content[-lines:], total_lines=len(content), requested_lines=lines)
    return result


diagnostics_routes = {
    '/api/network': diagnostics.network_details,
    '/api/services': diagnostics.failed_services,
    '/api/processes': diagnostics.process_rankings,
    '/api/usb': diagnostics.usb_devices,
}


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, data):
        self.send_body(status, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def do_GET(self):
        url = urlsplit(self.path)
        static = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        try:
            if url.path in static:
                filename, mime = static[url.path]
                self.send_body(200, (BASE / filename).read_bytes(), mime)
            elif url.path == '/api/health':
                self.json_response(200, {'status': 'ok'})
            elif url.path == '/api/system':
                self.json_response(200, system_info())
            elif url.path in diagnostics_routes:
                data = diagnostics_routes[url.path]()
                self.json_response(200 if data['available'] else 503, data)
            elif url.path == '/api/dmesg':
                try:
                    lines = int(parse_qs(url.query).get('lines', ['200'])[0])
                    if not 1 <= lines <= 1000:
                        raise ValueError()
                except ValueError:
                    self.json_response(400, {'error': 'lines 必須是 1 到 1000 的整數'})
                    return
                data = dmesg_info(lines)
                self.json_response(200 if data['available'] else 503, data)
            else:
                self.json_response(404, {'error': 'Not found'})
        except (OSError, ValueError, KeyError) as exc:
            self.log_error('Data collection failed: %s', exc)
            self.json_response(500, {'error': '系統資料讀取失敗，請查看伺服器日誌'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'System dashboard: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
