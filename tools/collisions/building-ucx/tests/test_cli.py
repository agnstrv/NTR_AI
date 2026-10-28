import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from building_ucx.geometry import volume


class CliTests(unittest.TestCase):
    def run_cli(self, data, budget=999, existing=False):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source, output = folder/'input.json', folder/'output.json'
            source.write_text(json.dumps(data), encoding='utf-8')
            if existing:
                output.write_text('preserve me', encoding='utf-8')
            result = subprocess.run([sys.executable, '-m', 'building_ucx', str(source),
                                     str(output), '--max-parts', str(budget)],
                                    capture_output=True, text=True)
            return result, output.read_text(encoding='utf-8') if output.exists() else None

    def shape(self):
        return {'outline': [[0,0],[8,0],[8,4],[4,4],[4,7],[0,7]], 'bottom': 0, 'top': 5}

    def test_cli_build(self):
        result, output = self.run_cli(self.shape())
        self.assertEqual(result.returncode, 0, result.stderr)
        parts = json.loads(output)['parts']
        self.assertGreater(len(parts), 1)
        self.assertLessEqual(len(parts), 999)
        self.assertAlmostEqual(sum(volume(p) for p in parts), 220, places=6)

    def test_budget_refusal_writes_nothing(self):
        result, output = self.run_cli(self.shape(), budget=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)

    def test_no_overwrite(self):
        result, output = self.run_cli(self.shape(), existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, 'preserve me')

    def test_infinite_height_rejected(self):
        data = self.shape(); data['top'] = float('inf')
        result, output = self.run_cli(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)
