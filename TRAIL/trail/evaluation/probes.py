"""Small hand-written probes, scored by likelihood: the model "answers" by assigning the highest probability to the correct continuation.
They are authored for TRAIL and are NOT in any training corpus. A micro model is expected to score near chance; the point is that the instrument
exists, is honest, and records history so progress at larger scales is measurable."""

REASONING = [  # (prompt, [candidates], index_of_correct)
    ("If 3 + 4 = 7 then 4 + 3 =", [" 7", " 8", " 6", " 12"], 0),
    ("The next number in 2, 4, 6, 8 is", [" 10", " 9", " 3", " 12"], 0),
    ("All cats are animals. Tom is a cat. So Tom is an", [" animal", " plant", " rock", " engine"], 0),
    ("5 - 2 =", [" 3", " 7", " 2", " 5"], 0),
    ("The opposite of hot is", [" cold", " warm", " red", " fast"], 0),
    ("If it rains the ground gets", [" wet", " dry", " loud", " square"], 0),
    ("10 divided by 2 is", [" 5", " 20", " 12", " 8"], 0),
    ("Monday, Tuesday, Wednesday, then", [" Thursday", " Sunday", " January", " Summer"], 0),
    ("1, 2, 3, 4,", [" 5", " 9", " 0", " 7"], 0),
    ("A triangle has", [" three sides", " five sides", " no sides", " ten sides"], 0),
    ("2 * 3 =", [" 6", " 5", " 8", " 23"], 0),
    ("water freezes when it is very", [" cold", " hot", " loud", " green"], 0),
]
CODING = [
    ("def add(a, b):\n    return a", [" + b", " - b", " * b + 7", " and"], 0),
    ("for i in range(10):\n    print(", ["i)", "i", "10", "range"], 0),
    ("import os\nprint(os.path.", ["join(", "(((", "= =", "->"], 0),
    ("def is_even(n):\n    return n % 2 ==", [" 0", " 'a'", " [", " None."], 0),
    ("x = [1, 2, 3]\nx.append(", ["4)", "4]", "}4", ";4"], 0),
    ("if x > 0:\n    y = 1\n", ["else:", "elsewhere", "else[", "end if"], 0),
    ("class Dog:\n    def __init__(", ["self):", "self]:", "this):", "def):"], 0),
    ("while True:\n    break\nprint(", ["'done')", "'done'}", "'done']", "'done'>"], 0),
    ('{"name": "trail", "version":', [' "1"', " ,,", " }}", " ]["], 0),
    ("try:\n    risky()\n", ["except Exception:", "catch (e) {", "rescue =>", "on error"], 0),
]
