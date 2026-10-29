"""Store layout, SKUs, modes and demand curve for MUM-114 (Andheri East), evening peak."""
import math

START = 18 * 3600 + 30 * 60      # sim t=0 is 18:30:00
HORIZON = 7200                   # two-hour evening shift
SPEED_PX = 28                    # walking speed, px per second
DWELL = 10                       # seconds at a slot for the first unit
PACK = 18                        # seconds to pack a bag
BUFFER = 45                      # minimum time buffer an order keeps when batched
PX_M = 0.05                      # metres per px

CROSS_Y = 400
HOME = {"x": 500, "y": 445}
SLOT_Y = [120, 210, 300]
FWD_Y = 350


def rack_x(i):
    return 70 + (i - 1) * 104


def cx(i):
    return rack_x(i) + 66


MODES = ["trough", "normal", "peak", "surge"]
MODE_LABEL = {"trough": "Trough", "normal": "Normal", "peak": "Peak", "surge": "Surge"}
MODE_METHOD = {"trough": "Discrete", "normal": "Cluster", "peak": "Cluster", "surge": "Zone pick-and-merge"}
LIMITS = {"trough": {"max": 1, "hold": 0}, "normal": {"max": 3, "hold": 30},
          "peak": {"max": 4, "hold": 75}, "surge": {"max": 4, "hold": 90}}
MODE_UP = {"normal": 0.5, "peak": 0.8, "surge": 0.92}
OPS_BOUNDS = {"max_batch": 4, "hold_s": 90}
PICKERS = ["Ravi", "Sunita", "Imran", "Asha", "Deepak", "Manoj"]
FAST_MOVERS = ["chips", "cola", "popcorn"]
# On-demand hourly pickers (gig pool). Assumed rate and limits for the prototype.
GIG = {"rate": 180, "leadS": 600, "maxOnFloor": 4, "maxSpend": 2000,
       "names": ["Arjun", "Pooja", "Salim", "Rekha", "Vikram", "Farah", "Kunal", "Meena"]}

# id, name, aisle, slot, temp, price, category, kg, popularity, shelf, backroom, starting trust
SKU_DEFS = [
    ["bread", "White bread 400 g", 1, 0, "amb", 45, "bread", 0.4, 6, 14, 40, 0.9],
    ["breadb", "Brown bread 400 g", 1, 1, "amb", 50, "bread", 0.4, 4, 10, 30, 0.66],
    ["breadm", "Multigrain bread 400 g", 1, 2, "amb", 55, "bread", 0.4, 2, 8, 20, 0.9],
    ["atta", "Atta 5 kg", 2, 0, "amb", 265, "atta", 5, 3, 12, 30, 0.94],
    ["dal", "Toor dal 1 kg", 2, 1, "amb", 160, "dal", 1, 3, 14, 30, 0.93],
    ["oil", "Sunflower oil 1 L", 2, 2, "amb", 150, "oil", 0.9, 3, 12, 30, 0.95],
    ["tea", "Tea 250 g", 3, 0, "amb", 140, "tea", 0.25, 3, 12, 30, 0.9],
    ["biscuit", "Biscuits, family pack", 3, 1, "amb", 40, "biscuit", 0.3, 6, 24, 60, 0.9],
    ["coffee", "Instant coffee 50 g", 3, 2, "amb", 160, "coffee", 0.05, 2, 10, 20, 0.62],
    ["chips", "Salted chips 90 g", 4, 0, "amb", 40, "chips", 0.09, 7, 20, 60, 0.9],
    ["chipsm", "Masala chips 90 g", 4, 1, "amb", 40, "chips", 0.09, 5, 18, 50, 0.88],
    ["popcorn", "Popcorn 60 g", 4, 2, "amb", 50, "popcorn", 0.06, 3, 12, 30, 0.68],
    ["cola", "Cola 750 ml", 5, 0, "amb", 45, "cola", 0.8, 7, 24, 60, 0.9],
    ["colaz", "Cola zero 750 ml", 5, 1, "amb", 45, "cola", 0.8, 3, 12, 30, 0.9],
    ["water", "Water 1 L", 5, 2, "amb", 20, "water", 1, 5, 30, 60, 0.95],
    ["milk", "Toned milk 500 ml", 6, 0, "chill", 29, "milk", 0.5, 10, 24, 40, 0.92],
    ["milkfc", "Full-cream milk 500 ml", 6, 1, "chill", 35, "milk", 0.5, 4, 18, 30, 0.9],
    ["curd", "Curd 400 g", 6, 2, "chill", 45, "curd", 0.4, 5, 14, 30, 0.88],
    ["paneer", "Paneer 200 g", 7, 0, "chill", 90, "paneer", 0.2, 4, 10, 0, 0.8],
    ["eggs", "Eggs, 6 pack", 7, 1, "chill", 48, "eggs", 0.4, 6, 20, 40, 0.9],
    ["butter", "Butter 100 g", 7, 2, "chill", 58, "butter", 0.1, 4, 16, 30, 0.86],
    ["icv", "Vanilla ice cream 700 ml", 8, 0, "frozen", 180, "ice", 0.6, 3, 10, 20, 0.85],
    ["icc", "Chocolate ice cream 700 ml", 8, 1, "frozen", 200, "ice", 0.6, 2, 8, 20, 0.9],
    ["peas", "Frozen peas 500 g", 8, 2, "frozen", 95, "peas", 0.5, 2, 10, 20, 0.92],
]
# Hidden shrink: the shelf quietly drops (theft, damage, mis-put-away) while the record does not.
SHRINK = [[1560, "milk", 0], [2640, "chips", 0], [3240, "paneer", 0], [3960, "cola", 1]]


def lambda_at(t):
    """Orders per minute at sim time t: base load plus an 8 PM bell curve."""
    m = t / 60
    return 1.6 + 2.8 * math.exp(-(((m - 45) / 17) ** 2))


def fmt(t):
    s = START + int(t)
    return "%02d:%02d:%02d" % ((s // 3600) % 24, (s // 60) % 60, s % 60)


def mmss(s):
    s = max(0, round(s))
    return "%d:%02d" % (s // 60, s % 60)


def inr(n):
    """Indian digit grouping, e.g. 2000 -> '2,000', 125000 -> '1,25,000'."""
    n = int(n)
    neg, s = n < 0, str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + s


def f2(x, n=2):
    return f"{x:.{n}f}"


def pystr(v):
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)
