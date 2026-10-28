import unittest
from collections import Counter
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from building_ucx.geometry import rebuild, volume, subtract, split_with_gap
from building_ucx.contours import convex_parts


def box(low, high):
    return rebuild({'vertices': [[x, y, z] for x in (low, high)
                                for y in (0, 1) for z in (0, 1)]})


class GeometryTests(unittest.TestCase):
    def assert_closed(self, part):
        edges = Counter(tuple(sorted((a, b))) for face in part['faces']
                        for a, b in zip(face, face[1:] + face[:1]))
        self.assertTrue(all(count == 2 for count in edges.values()))

    def test_subtraction_volume_and_closure(self):
        pieces, discarded = subtract(box(0, 2), box(1, 3))
        self.assertAlmostEqual(sum(map(volume, pieces)), 1, places=6)
        self.assertEqual(discarded, 0)
        for part in pieces:
            self.assert_closed(part)

    def test_containment_removes_all(self):
        self.assertEqual(subtract(box(0, 1), box(-1, 2))[0], [])

    def test_rotated_split_gap(self):
        angle = .37
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                             [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
        part = box(0, 2)
        part['vertices'] = part['vertices'] @ rotation.T
        normal = rotation[:, 0]
        a, b = split_with_gap(part, normal * 3, 3, .002)
        self.assertAlmostEqual(min(b['vertices'] @ normal) - max(a['vertices'] @ normal), .002, places=7)
        self.assertAlmostEqual(volume(a) + volume(b), 1.998, places=6)
        self.assert_closed(a)
        self.assert_closed(b)

    def test_hole_is_not_filled(self):
        polygon = Polygon([(0,0),(5,0),(5,5),(0,5)], [[(1,1),(1,3),(3,3),(3,1)]])
        parts = convex_parts(polygon)
        self.assertLess(unary_union(parts).symmetric_difference(polygon).area, 1e-6)
        self.assertTrue(all(p.convex_hull.area - p.area < 1e-6 for p in parts))

    def test_zero_normal_rejected(self):
        with self.assertRaises(ValueError):
            split_with_gap(box(0, 1), [0,0,0], 0, .002)

    def test_two_millimetre_hole_survives_merge(self):
        hole = Polygon([(1,1),(1.002,1),(1.002,1.002),(1,1.002)])
        polygon = Polygon([(0,0),(4,0),(4,4),(0,4)], [list(hole.exterior.coords)])
        result = unary_union(convex_parts(polygon))
        self.assertLess(result.intersection(hole).area, 1e-10)

    def test_precision_can_split_narrow_bridge(self):
        from shapely.geometry import box as rectangle
        polygon = unary_union([rectangle(0,0,2,2), rectangle(4,0,6,2),
                               rectangle(2,.9999,4,1.0001)])
        parts = convex_parts(polygon)
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(sum(p.area for p in parts), 8)


if __name__ == '__main__':
    unittest.main()
