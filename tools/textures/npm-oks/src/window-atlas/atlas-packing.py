"""Pack rectangular texture regions into a fixed atlas area without rotation.

sizes contains (content_width, content_height) integer pixel pairs. Returned
origins are lower-left interior origins in the same order as sizes. Padding is
reserved on all four sides of each region. None means the deterministic
heuristics did not find a placement, not a proof that no packing exists.

This module is independent of Blender and performs no file or scene writes.
"""
from numbers import Integral


def _prune(rectangles):
    # Larger free rectangles first makes containment checks cheaper. Exact
    # duplicates are removed before the quadratic containment pass.
    ordered = sorted(set(rectangles), key=lambda r: r[2] * r[3], reverse=True)
    kept = []
    for x, y, w, h in ordered:
        if any(x >= a and y >= b and x + w <= a + c and y + h <= b + d
               for a, b, c, d in kept):
            continue
        kept.append((x, y, w, h))
    return kept


def _place(order, padded, width, height, score_kind):
    free = [(0, 0, width, height)]
    origins = [None] * len(padded)
    for index in order:
        w, h = padded[index]
        best = None
        for x, y, fw, fh in free:
            if w > fw or h > fh:
                continue
            dx, dy = fw - w, fh - h
            if score_kind == 'short':
                score = (min(dx, dy), max(dx, dy), y, x)
            elif score_kind == 'area':
                score = (fw * fh - w * h, min(dx, dy), y, x)
            else:
                score = (y + h, x, min(dx, dy), max(dx, dy))
            if best is None or score < best[0]:
                best = (score, x, y)
        if best is None:
            return None
        _, px, py = best
        origins[index] = (px, py)
        right, top = px + w, py + h
        remaining = []
        # Free rectangles may overlap each other; split *every* intersected
        # free rectangle so no future placement can overlap this allocation.
        for x, y, fw, fh in free:
            r, t = x + fw, y + fh
            if px >= r or right <= x or py >= t or top <= y:
                remaining.append((x, y, fw, fh))
                continue
            if px > x:
                remaining.append((x, y, px - x, fh))
            if right < r:
                remaining.append((right, y, r - right, fh))
            if py > y:
                remaining.append((x, y, fw, py - y))
            if top < t:
                remaining.append((x, top, fw, t - top))
        free = _prune(remaining)
    return origins


def pack_rectangles(sizes, width=1024, height=2048, padding=3):
    """Return padded content origins [(x,y), ...] or None, without rotation."""
    if not all(isinstance(v, Integral) and not isinstance(v, bool)
               for v in (width, height, padding)):
        raise ValueError('width, height, padding must be integers')
    if width <= 0 or height <= 0 or padding < 0:
        raise ValueError('positive width/height and nonnegative padding required')
    sizes = list(sizes)
    padded = []
    for size in sizes:
        if len(size) != 2 or not all(isinstance(v, Integral) and not isinstance(v, bool) and v > 0 for v in size):
            raise ValueError('each size must contain two positive integers')
        padded.append((int(size[0]) + padding * 2, int(size[1]) + padding * 2))
    if not padded:
        return []
    if any(w > width or h > height for w, h in padded):
        return None
    if sum(w * h for w, h in padded) > width * height:
        return None
    keys = [
        lambda i: (max(padded[i]), min(padded[i]), padded[i][0] * padded[i][1]),
        lambda i: (padded[i][0] * padded[i][1], max(padded[i]), padded[i][1]),
        lambda i: (padded[i][1], padded[i][0]),
        lambda i: (padded[i][0], padded[i][1]),
    ]
    orders = []
    for key in keys:
        order = sorted(range(len(padded)), key=key, reverse=True)
        if order not in orders:
            orders.append(order)
    for score in ('short', 'area', 'bottom'):
        for order in orders:
            result = _place(order, padded, width, height, score)
            if result is not None:
                return [(x + padding, y + padding) for x, y in result]
    return None
