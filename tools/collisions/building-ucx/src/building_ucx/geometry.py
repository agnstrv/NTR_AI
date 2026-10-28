"""Portable extraction of the double-precision hull/Boolean experiment.

Inputs to Boolean operations MUST be convex solids. rebuild intentionally takes
the convex hull; it must never be used to certify an arbitrary source mesh.
All coordinates must use one Cartesian frame and metres.
"""
import numpy as np
from scipy.spatial import ConvexHull
from . import _legacy


def rebuild(poly):
    vertices = np.unique(np.round(np.asarray(poly['vertices'], dtype=float), 8), axis=0)
    hull = ConvexHull(vertices)  # Degenerate input raises QhullError.
    used = np.unique(hull.simplices)
    mapping = {old: new for new, old in enumerate(used)}
    center = vertices.mean(axis=0)
    faces = []
    for triangle in hull.simplices:
        points = vertices[triangle]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        if normal @ (points.mean(axis=0) - center) < 0:
            triangle = triangle[::-1]
        faces.append([mapping[index] for index in triangle])
    return {'vertices': vertices[used], 'faces': faces}


def planes(poly):
    hull = ConvexHull(np.asarray(poly['vertices'], dtype=float))
    seen, result = set(), []
    for equation in hull.equations:
        key = tuple(np.round(equation, 7))
        if key not in seen:
            result.append((equation[:3], float(-equation[3])))
            seen.add(key)
    return result


# Preserve the historical subtraction algorithm, replacing its unstable
# first-triangle plane estimator with double-precision supporting planes.
_legacy.planes = planes


def volume(poly):
    return float(ConvexHull(np.asarray(poly['vertices'], dtype=float)).volume)


def clip(poly, normal, offset):
    normal = np.asarray(normal, dtype=float)
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length == 0:
        raise ValueError('A finite nonzero plane normal is required')
    result = _legacy.clip(rebuild(poly), normal / length, float(offset) / length)
    return None if result is None else rebuild(result)


def subtract(a, b, *, epsilon=1e-6, minimum_volume=1e-5):
    """Return convex pieces of a minus b, plus explicitly reported discarded volume.

    Numerical epsilon and minimum_volume are experimental settings, not the
    architectural deviation allowance. A removed sliver needs coverage review.
    """
    pieces, discarded = [], 0.0
    for raw in _legacy.subtract(rebuild(a), rebuild(b), eps=epsilon):
        part = rebuild(raw)
        size = volume(part)
        if size <= minimum_volume:
            discarded += size
        else:
            pieces.append(part)
    return pieces, discarded


def split_with_gap(poly, normal, offset, gap):
    """Cut an already convex solid about one plane, closing both resulting pieces."""
    if not np.isfinite(gap) or gap < 0:
        raise ValueError('gap must be finite and nonnegative')
    normal = np.asarray(normal, dtype=float)
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length == 0:
        raise ValueError('A finite nonzero plane normal is required')
    normal, offset = normal / length, float(offset) / length
    return (clip(poly, normal, offset - gap / 2),
            clip(poly, -normal, -offset - gap / 2))
