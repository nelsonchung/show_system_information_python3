import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_command_failure_timeout_and_environment(self):
        with patch('diagnostics.subprocess.run', side_effect=FileNotFoundError('missing')):
            self.assertFalse(diagnostics.failed_services()['available'])
        with patch('diagnostics.subprocess.run', side_effect=subprocess.TimeoutExpired('ps', 5)):
            self.assertFalse(diagnostics.process_rankings()['available'])
        result = subprocess.CompletedProcess([], 1, '', 'access denied')
        with patch('diagnostics.subprocess.run', return_value=result) as run:
            self.assertEqual(diagnostics.failed_services()['error'], 'access denied')
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_network_addresses_and_signal(self):
        output = json.dumps([{'ifname': 'wlan0', 'addr_info': [
            {'family': 'inet', 'local': '192.168.8.235', 'prefixlen': 24},
            {'family': 'inet6', 'local': 'fe80::1', 'prefixlen': 64}]}])
        with tempfile.TemporaryDirectory() as tmp:
            wireless = Path(tmp) / 'wireless'
            wireless.write_text('Inter-| sta-| Quality\n face | tus | link level\n wlan0: 0000 53. -57. -256 0\n')
            with patch('diagnostics.WIRELESS_PATH', wireless), patch('diagnostics._command', return_value=(output, None)):
                data = diagnostics.network_details()
            self.assertTrue(data['available'])
            self.assertTrue(data['wifi_available'])
            self.assertEqual(data['interfaces'][0]['addresses'], ['192.168.8.235/24', 'fe80::1/64'])
            self.assertEqual(data['interfaces'][0]['signal_dbm'], -57)

    def test_network_optional_wireless_and_invalid_ip(self):
        with patch('diagnostics._wireless_signals', return_value=({}, 'permission denied')):
            with patch('diagnostics._command', return_value=('[{"ifname":"eth0"}]', None)):
                data = diagnostics.network_details()
                self.assertTrue(data['available'])
                self.assertFalse(data['wifi_available'])
                self.assertEqual(data['wifi_error'], 'permission denied')
            for output in ['bad json', '{}', '[{}]', '[{"ifname":4}]']:
                with patch('diagnostics._command', return_value=(output, None)):
                    self.assertFalse(diagnostics.network_details()['available'])
        with patch('diagnostics._wireless_signals', return_value=({'wlan0': -60}, None)), patch('diagnostics._command', return_value=(None, 'ip missing')):
            data = diagnostics.network_details()
            self.assertFalse(data['available'])
            self.assertEqual(data['interfaces'][0]['signal_dbm'], -60)

    def test_wireless_malformed_and_unsigned_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            wireless = Path(tmp) / 'wireless'
            with patch('diagnostics.WIRELESS_PATH', wireless):
                self.assertIsNotNone(diagnostics._wireless_signals()[1])
                wireless.write_text('Inter-| sta-|\nheader\nwlan0: broken\n')
                self.assertIsNotNone(diagnostics._wireless_signals()[1])
                wireless.write_text('Inter-| sta-|\nheader\nwlan0: 0000 53. 199. -256\n')
                self.assertEqual(diagnostics._wireless_signals()[0]['wlan0'], -57)

    def test_failed_service_empty_failure_and_description(self):
        with patch('diagnostics._command', return_value=('', None)):
            self.assertEqual(diagnostics.failed_services(), {'available': True, 'error': None, 'units': []})
        with patch('diagnostics._command', return_value=('example.service loaded failed failed Example worker service', None)):
            data = diagnostics.failed_services()
            self.assertTrue(data['available'])
            self.assertEqual(data['units'][0]['name'], 'example.service')
            self.assertEqual(data['units'][0]['description'], 'Example worker service')
        with patch('diagnostics._command', return_value=('unexpected output', None)):
            self.assertFalse(diagnostics.failed_services()['available'])

    def test_process_sorting_and_names_with_spaces(self):
        rows = ['10 worker with spaces 130.5 2.0 123', '11 memory-heavy 1.1 5.0 1024']
        rows += [f'{pid} small 0.0 0.0 1' for pid in range(12, 25)]
        with patch('diagnostics._command', return_value=('\n'.join(rows), None)):
            data = diagnostics.process_rankings()
        self.assertTrue(data['available'])
        self.assertEqual(data['total'], 15)
        self.assertEqual(len(data['cpu_top']), 10)
        self.assertEqual(data['cpu_top'][0]['pid'], 10)
        self.assertEqual(data['cpu_top'][0]['name'], 'worker with spaces')
        self.assertEqual(data['memory_top'][0]['pid'], 11)
        self.assertEqual(data['memory_top'][0]['rss_bytes'], 1024 * 1024)
        self.assertEqual(data['cpu_basis'], 'lifetime_average_one_core_100_percent')

    def test_process_bad_output_does_not_become_empty_success(self):
        for output in ['', 'bad row', '1 worker nan 1.0 10', '1 worker 1 1 -10']:
            with patch('diagnostics._command', return_value=(output, None)):
                self.assertFalse(diagnostics.process_rankings()['available'])

    def test_usb_descriptors_optional_fields_and_hotplug(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usb = root / '1-1'
            usb.mkdir()
            for name, value in {'idVendor': 'abcd', 'idProduct': '1234', 'busnum': '1', 'devnum': '2', 'product': 'USB disk', 'speed': '480'}.items():
                (usb / name).write_text(value)
            (root / '1-1:1.0').mkdir()
            (root / 'vanished').symlink_to(root / 'missing')
            with patch('diagnostics.USB_ROOT', root):
                data = diagnostics.usb_devices()
            self.assertTrue(data['available'])
            self.assertEqual(len(data['devices']), 1)
            device = data['devices'][0]
            self.assertEqual(device['product'], 'USB disk')
            self.assertIsNone(device['manufacturer'])
            self.assertEqual(device['speed_mbps'], 480)
            self.assertNotIn('serial', device)
            (usb / 'idVendor').write_text('bad')
            with patch('diagnostics.USB_ROOT', root):
                data = diagnostics.usb_devices()
                self.assertTrue(data['available'])
                self.assertEqual(data['devices'], [])
                self.assertIsNotNone(data['error'])
        with patch('diagnostics.USB_ROOT', Path(tmp) / 'missing'):
            self.assertFalse(diagnostics.usb_devices()['available'])


if __name__ == '__main__':
    unittest.main()
