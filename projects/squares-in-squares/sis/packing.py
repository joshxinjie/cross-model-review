"""Decimal wire contract and deterministic grid construction (no metric imports)."""
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO
from math import isqrt
import re

COLUMNS = ['id', 'n', 'square_id', 'x', 'y', 'angle']
LITERAL = re.compile(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')


def literal(text, limit=10000):
    if not isinstance(text, str) or len(text) > 100 or not LITERAL.fullmatch(text):
        raise ValueError('expected a decimal literal of at most 100 characters')
    try:
        value = Decimal(text)
    except InvalidOperation as e:
        raise ValueError('invalid decimal literal') from e
    if not value.is_finite() or value.copy_abs() > limit:
        raise ValueError('literal out of range')
    # Avoid resource exhaustion in rational conversion of underflow exponents.
    # Deliberately stricter than the official parser; no useful baseline needs this.
    if value and abs(value.as_tuple().exponent) > 1000:
        raise ValueError('exponent out of local range')
    return value


@dataclass(frozen=True)
class Square:
    x: str
    y: str
    angle: str = '0'

    def __post_init__(self):
        literal(self.x)
        literal(self.y)
        literal(self.angle, 100)


def puzzle_number(n):
    if type(n) is not int or not 1 <= n <= 1000:
        raise ValueError('n must be an integer in 1..1000')
    return n


def grid(n):
    puzzle_number(n)
    width = isqrt(n - 1) + 1
    return tuple(Square(f'{i % width}.5', f'{i // width}.5') for i in range(n))


def serialize(puzzles):
    """Lossless decimal strings, sorted puzzles, sequential integer row IDs."""
    out = StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(COLUMNS)
    row_id = 0
    for n, squares in sorted(puzzles.items()):
        puzzle_number(n)
        if len(squares) != n:
            raise ValueError('wrong square count')
        for sid, s in enumerate(squares):
            Square(s.x, s.y, s.angle)
            writer.writerow([row_id, n, sid, s.x, s.y, s.angle])
            row_id += 1
    return out.getvalue()


def deserialize(text):
    reader = csv.DictReader(StringIO(text, newline=''))
    if reader.fieldnames != COLUMNS:
        raise ValueError('expected exact CSV header')
    groups, ids = {}, set()
    try:
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('malformed CSV row')
            for name in COLUMNS[:3]:
                if not re.fullmatch(r'0|[1-9][0-9]*', row[name]):
                    raise ValueError('IDs must be canonical nonnegative integers')
            rid, n, sid = (int(row[k]) for k in COLUMNS[:3])
            puzzle_number(n)
            if rid in ids or sid in groups.setdefault(n, {}) or not 0 <= sid < n:
                raise ValueError('duplicate or out of range ID')
            ids.add(rid)
            groups[n][sid] = Square(row['x'], row['y'], row['angle'])
        if any(set(rows) != set(range(n)) for n, rows in groups.items()):
            raise ValueError('incomplete puzzle')
        return {n: tuple(rows[i] for i in range(n)) for n, rows in sorted(groups.items())}
    except (TypeError, KeyError) as e:
        raise ValueError('malformed CSV') from e
