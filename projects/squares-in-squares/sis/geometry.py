"""Independent fail-closed certification, without official metric code.

Axis-aligned squares use exact rational rectangles and a sweep. Rotations use
interval corner projections on edge normals (SAT), escalating precision. No
floating tolerance is ever accepted as evidence of separation or containment.
"""
from fractions import Fraction as F
from mpmath.ctx_iv import MPIntervalContext

from .packing import Square, puzzle_number


def _rectangles(squares):
    h = F(1, 2)
    return [(F(s.x)-h, F(s.y)-h, F(s.x)+h, F(s.y)+h) for s in squares]


def _exact(squares, bounds):
    rects = sorted(_rectangles(squares))
    if bounds is not None:
        lo_x, lo_y, side = map(F, bounds)
        if side <= 0 or any(x < lo_x or y < lo_y or xx > lo_x+side or yy > lo_y+side
                            for x, y, xx, yy in rects):
            raise ValueError('outside container')
    active = []
    for rect in rects:
        x, y, xx, yy = rect
        active = [r for r in active if r[2] > x]
        if any(min(yy, r[3]) > max(y, r[1]) for r in active):
            raise ValueError('overlapping interiors')
        active.append(rect)
    return max(max(r[2] for r in rects)-min(r[0] for r in rects),
               max(r[3] for r in rects)-min(r[1] for r in rects))


def _corners(iv, square):
    x, y, a = (iv.mpf(t) for t in (square.x, square.y, square.angle))
    c, s, h = iv.cos(a), iv.sin(a), iv.mpf('0.5')
    return [(x+dx*c-dy*s, y+dx*s+dy*c) for dx, dy in [(h,h),(-h,h),(-h,-h),(h,-h)]]


def _rotated(squares, bounds, dps):
    iv = MPIntervalContext()
    iv.dps = dps
    corners = [_corners(iv, s) for s in squares]
    # Endpoints are outward rounded. Use them for a conservative broad phase.
    boxes = [(min(p[0].a for p in c), min(p[1].a for p in c),
              max(p[0].b for p in c), max(p[1].b for p in c), i)
             for i, c in enumerate(corners)]
    if bounds is not None:
        x, y, side = (iv.mpf(str(t)) for t in bounds)
        if not side.a > 0:
            return None
        for c in corners:
            if not all(px.a >= x.b and py.a >= y.b and px.b <= (x+side).a and py.b <= (y+side).a
                       for px, py in c):
                return None
    active = []
    for box in sorted(boxes, key=lambda b: b[0]):
        x, y, xx, yy, i = box
        active = [b for b in active if b[2] > x]
        for b in active:
            if b[3] <= y or yy <= b[1]:
                continue
            j = b[4]
            separated = False
            for c in (corners[i], corners[j]):
                for k in (0, 1):
                    # A normal to each of the two independent edges.
                    dx, dy = c[k+1][0]-c[k][0], c[k+1][1]-c[k][1]
                    pi = [px*(-dy)+py*dx for px, py in corners[i]]
                    pj = [px*(-dy)+py*dx for px, py in corners[j]]
                    if max(p.b for p in pi) <= min(p.a for p in pj) or max(p.b for p in pj) <= min(p.a for p in pi):
                        separated = True
                        break
                if separated:
                    break
            if not separated:
                return None
        active.append(box)
    # Return a conservative enclosing side, decimal text rounded upwards.
    span_x = max(b[2] for b in boxes)-min(b[0] for b in boxes)
    span_y = max(b[3] for b in boxes)-min(b[1] for b in boxes)
    upper = max(span_x.b, span_y.b)
    # Convert binary interval endpoint to an exact Fraction, without float loss.
    sign, mantissa, exponent, _ = upper._mpi_[1]
    return F((-1)**sign * mantissa) * F(2)**exponent


def validate(n, squares, bounds=None):
    """Return an exact upper bound on side; reject overlap or uncertain geometry.

    bounds = (origin_x, origin_y, side), all decimal strings. None measures a
    translation-invariant enclosing square. Touching is allowed when certified.
    """
    puzzle_number(n)
    if len(squares) != n:
        raise ValueError('wrong square count')
    for s in squares:
        Square(s.x, s.y, s.angle)
    if bounds is not None:
        from .packing import literal
        if len(bounds) != 3:
            raise ValueError('expected x,y,side')
        for t in bounds:
            literal(t)
    if all(F(s.angle) == 0 for s in squares):
        return _exact(squares, bounds)
    for dps in (50, 100, 200):
        result = _rotated(squares, bounds, dps)
        if result is not None:
            return result
    raise ValueError('rotation geometry overlaps, is out of bounds, or cannot be certified')
