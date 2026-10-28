"""Convert an explicitly supplied footprint to candidate convex prisms."""
import argparse
import json
import math
from pathlib import Path
from shapely.geometry import Polygon
from .contours import convex_parts, prism


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--max-parts', type=int, required=True)
    args = parser.parse_args()
    if args.max_parts < 1:
        parser.error('--max-parts must be positive')
    data = json.loads(args.input.read_text(encoding='utf-8'))
    polygon = Polygon(data['outline'], data.get('holes', []))
    low, high = float(data['bottom']), float(data['top'])
    if not polygon.is_valid or polygon.is_empty or not all(map(math.isfinite, (low, high))) or not low < high:
        parser.error('A valid nonempty footprint and bottom < top are required')
    parts = [prism(p, low, high, 'body') for p in convex_parts(polygon)]
    if not parts or len(parts) > args.max_parts:
        parser.error(f'Candidate count {len(parts)} outside 1..{args.max_parts}; nothing written')
    payload = {'status': 'prototype-candidates', 'gap_applied': False,
               'source_deviation_verified': False, 'parts': parts}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
    print(f'Wrote {len(parts)} candidate solids to {args.output}')


if __name__ == '__main__':
    main()
