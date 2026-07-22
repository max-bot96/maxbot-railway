import random
from datetime import datetime, timezone

QUIZ_QUESTIONS = [
    {
        "id": 1,
        "category": "Python Internals",
        "question": "```python\nclass A:\n    def show(self): print(\"A\")\nclass B(A):\n    def show(self): print(\"B\")\nclass C(A):\n    def show(self): print(\"C\")\nclass D(B, C):\n    pass\n\nD().show()\n```",
        "options": ["A", "B", "C", "D"],
        "correct": 1,
        "explanation": "ترتيب MRO: D → B → C → A — B أولاً لأنها اليسار",
        "hint": "تذكر Method Resolution Order"
    },
    {
        "id": 2,
        "category": "Python Internals",
        "question": "```python\nimport threading\n\ncounter = 0\ndef inc():\n    global counter\n    for _ in range(1000000):\n        counter += 1\n\nt1 = threading.Thread(target=inc)\nt2 = threading.Thread(target=inc)\nt1.start(); t2.start()\nt1.join(); t2.join()\nprint(counter)\n```",
        "options": ["2000000", "أقل من 2000000", "أكثر من 2000000", "خطأ"],
        "correct": 1,
        "explanation": "GIL يمنع التزامن الحقيقي — counter += 1 ليس atomic operation",
        "hint": "GIL — ماذا يفعل للـ threads؟"
    },
    {
        "id": 3,
        "category": "Python Internals",
        "question": "```python\nclass Meta(type):\n    def __new__(cls, name, bases, dict):\n        dict['extra'] = 42\n        return super().__new__(cls, name, bases, dict)\n\nclass MyClass(metaclass=Meta):\n    pass\n\nprint(MyClass.extra)\n```",
        "options": ["42", "AttributeError", "None", "خطأ في التعريف"],
        "correct": 0,
        "explanation": "Metaclass تُضيف 'extra' للـ dict أثناء إنشاء الكلاس نفسه",
        "hint": "Metaclass تُنشئ الكلاسات — ماذا تفعل مع dict؟"
    },
    {
        "id": 4,
        "category": "Python Internals",
        "question": "```python\nclass Descriptor:\n    def __get__(self, obj, objtype=None):\n        return \"got it\"\n\nclass MyClass:\n    attr = Descriptor()\n\nobj = MyClass()\nprint(obj.attr)\nprint(MyClass.attr)\n```",
        "options": ["got it مرتين", "got it ثم <Descriptor object>", "<Descriptor object> ثم got it", "خطأ"],
        "correct": 0,
        "explanation": "Descriptor Protocol يُستدعى في كلا الحالتين — مع obj وبدون obj",
        "hint": "Descriptor Protocol — __get__ يستقبل obj و objtype"
    },
    {
        "id": 5,
        "category": "Python Internals",
        "question": "```python\ngen = (x*2 for x in range(5))\nlst = [x*2 for x in range(5)]\nprint(type(gen), type(lst))\nprint(sum(gen), sum(lst))\n```",
        "options": ["generator list — 20 20", "generator list — 20 0", "generator list — 0 20", "خطأ"],
        "correct": 1,
        "explanation": "Generator يُستهلك بعد أول استخدام — sum(gen) lần 1 = 20، sum(gen) lần 2 = 0",
        "hint": "Generator vs List — ما الفرق في الذاكرة؟"
    },
    {
        "id": 6,
        "category": "Python المتقدم",
        "question": "```python\ndef repeat(times):\n    def decorator(func):\n        def wrapper(*args, **kwargs):\n            result = None\n            for _ in range(times):\n                result = func(*args, **kwargs)\n            return result\n        return wrapper\n    return decorator\n\n@repeat(times=3)\ndef greet(name):\n    print(f\"Hi {name}\")\n    return name\n\nresult = greet(\"Ali\")\n```",
        "options": ["يطبع Hi Ali 3 مرات، result = Ali", "يطبع Hi Ali مرة واحدة، result = Ali", "خطأ", "يطبع 3 مرات، result = None"],
        "correct": 0,
        "explanation": "wrapper يُكرر 3 مرات، last return يُعاد — result = last call's return",
        "hint": "Decorator with arguments — wrapper يكرر كم مرة؟"
    },
    {
        "id": 7,
        "category": "Python المتقدم",
        "question": "```python\nclass CM:\n    def __enter__(self):\n        print(\"enter\")\n        return self\n    def __exit__(self, *args):\n        print(\"exit\")\n        return True\n\nwith CM() as cm:\n    raise ValueError(\"error\")\nprint(\"done\")\n```",
        "options": ["enter → exit → خطأ", "enter → exit → done", "enter → خطأ", "enter → done"],
        "correct": 1,
        "explanation": "__exit__ يُعيد True فيُكبت الاستثناء — يطبع done",
        "hint": "__exit__ ماذا يفعل عندما يُعيد True؟"
    },
    {
        "id": 8,
        "category": "Python المتقدم",
        "question": "```python\nclass Point:\n    __slots__ = ('x', 'y')\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n\np = Point(1, 2)\np.z = 3\n```",
        "options": ["يعمل عادي", "AttributeError", "يُنشئ attribute جديد", "خطأ في التعريف"],
        "correct": 1,
        "explanation": "__slots__ يمنع إنشاء attributes جديدة خارج القائمة المحددة",
        "hint": "__slots__ — ماذا يُنشئ وماذا يمنع؟"
    },
    {
        "id": 9,
        "category": "Python المتقدم",
        "question": "```python\nimport asyncio\n\nasync def foo():\n    print(\"1\")\n    await asyncio.sleep(0)\n    print(\"2\")\n\nasync def bar():\n    print(\"3\")\n    await foo()\n    print(\"4\")\n\nasyncio.run(bar())\n```",
        "options": ["1 2 3 4", "3 1 2 4", "3 1 4 2", "1 3 2 4"],
        "correct": 1,
        "explanation": "bar() يبدأ أولاً (print 3)، ثم foo() (print 1)، ثم await (print 2)، ثم bar() (print 4)",
        "hint": "async/await — أيهما يبدأ أولاً bar() أم foo()؟"
    },
    {
        "id": 10,
        "category": "Python المتقدم",
        "question": "```python\ndata = [1, 2, 3, 4, 5]\nresult = [y for x in data if (y := x * 2) > 6]\nprint(result)\n```",
        "options": ["[8, 10]", "[2, 4, 6, 8, 10]", "[7, 8, 9, 10]", "خطأ"],
        "correct": 0,
        "explanation": "Walrus operator يُخزن y = x*2، ثم يُقارن > 6 — x=4 → y=8، x=5 → y=10",
        "hint": "Walrus operator (:=) — ماذا يفعل قبل المقارنة؟"
    },
    {
        "id": 11,
        "category": "Python عالي المستوى",
        "question": "```python\nfrom abc import ABC, abstractmethod\n\nclass Shape(ABC):\n    @abstractmethod\n    def area(self):\n        pass\n\nclass Circle(Shape):\n    def __init__(self, r):\n        self.r = r\n\nc = Circle(5)\nprint(c.area())\n```",
        "options": ["78.5", "AttributeError", "TypeError", "NotImplementedError"],
        "correct": 2,
        "explanation": "لا يمكن عمل instantiate لـ Circle لأنها لم تُنفذ method 'area' — TypeError",
        "hint": "Abstract Base Class — ماذا يحدث إذا لم تُنفذ method؟"
    },
    {
        "id": 12,
        "category": "Python عالي المستوى",
        "question": "```python\nfrom dataclasses import dataclass, field\n\n@dataclass(order=True)\nclass Student:\n    sort_index: float = field(init=False, repr=False)\n    name: str\n    gpa: float\n    \n    def __post_init__(self):\n        self.sort_index = self.gpa\n\ns1 = Student(\"Ali\", 3.5)\ns2 = Student(\"Omar\", 3.8)\nprint(s1 < s2)\n```",
        "options": ["True", "False", "خطأ", "True لأن s1.gpa < s2.gpa"],
        "correct": 0,
        "explanation": "order=True + sort_index = gpa — المقارنة تتم بالـ gpa تلقائياً",
        "hint": "Dataclass order=True — ما الذي يُقارن؟"
    },
    {
        "id": 13,
        "category": "Python عالي المستوى",
        "question": "```python\nclass Singleton:\n    _instance = None\n    def __new__(cls):\n        if cls._instance is None:\n            cls._instance = super().__new__(cls)\n        return cls._instance\n    def __init__(self):\n        self.id = id(self)\n\na = Singleton()\nb = Singleton()\nprint(a.id == b.id)\nprint(a is b)\n```",
        "options": ["True True", "False True", "True False", "False False"],
        "correct": 0,
        "explanation": "Singleton يُعيد نفس الكائن — __init__ يُستدعى مرتين لكن id نفسهم",
        "hint": "Singleton pattern — __new__ يُنشئ كائناً جديداً كل مرة؟"
    },
    {
        "id": 14,
        "category": "خوارزميات",
        "question": "```python\ndef mystery(n):\n    count = 0\n    i = 1\n    while i < n:\n        j = 1\n        while j < n:\n            count += 1\n            j *= 2\n        i *= 2\n    return count\n```",
        "options": ["O(n)", "O(n²)", "O(log²n)", "O(n log n)"],
        "correct": 2,
        "explanation": "كل loop يكرر log(n) مرة — الأول log(n) والثاني log(n) → O(log²n)",
        "hint": "كم مرة تتكرر كل loop؟ — i*=2 و j*=2"
    },
    {
        "id": 15,
        "category": "Git",
        "question": "```bash\ngit reset --soft HEAD~1\n```",
        "options": ["يحذف آخر commit ويرجع للـ working directory", "يحذف آخر commit ويبقي في الـ staging area", "يحذف كل شيء", "يُلغي آخر commit"],
        "correct": 1,
        "explanation": "--soft يُبقي التغييرات في staging area — لا يحذفها",
        "hint": "Git reset — ما الفرق بين --soft و --hard؟"
    }
]


def get_question(num):
    if 0 <= num < len(QUIZ_QUESTIONS):
        return QUIZ_QUESTIONS[num]
    return None


def check_answer(question_id, answer_index):
    for q in QUIZ_QUESTIONS:
        if q["id"] == question_id:
            return answer_index == q["correct"]
    return False


def get_level(score):
    if score >= 50:
        return "خبير برمجي", "👑"
    elif score >= 40:
        return "مطور متقدم", "🥇"
    elif score >= 30:
        return "مطور متوسط", "🥈"
    elif score >= 15:
        return "مطور مبتدئ", "🥉"
    else:
        return "يحتاج تعلم", "📘"


def get_badge(score):
    if score >= 50:
        return "👑"
    elif score >= 40:
        return "🥇"
    elif score >= 30:
        return "🥈"
    elif score >= 15:
        return "🥉"
    else:
        return "📘"


def get_category_analysis(questions, answers):
    categories = {}
    for q, a in zip(questions, answers):
        cat = q["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "correct": 0}
        categories[cat]["total"] += 1
        if a == q["correct"]:
            categories[cat]["correct"] += 1
    return categories


_quiz_cache = {}

def save_quiz_score(guild_id, user_id, score, time_minutes, hints_used):
    global _quiz_cache
    gid = str(guild_id)
    uid = str(user_id)

    if gid not in _quiz_cache:
        _quiz_cache[gid] = {}

    existing = _quiz_cache[gid].get(uid, {})
    if score > existing.get("score", 0):
        _quiz_cache[gid][uid] = {
            "score": score,
            "time": round(time_minutes, 1),
            "hints": hints_used,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "level": get_level(score)[0]
        }

    try:
        import main
        main._quiz_scores_cache = _quiz_cache
    except Exception:
        pass


def load_quiz_scores(data):
    global _quiz_cache
    _quiz_cache = data


def get_leaderboard(guild_id):
    scores = _quiz_cache.get(str(guild_id), {})
    sorted_scores = sorted(scores.items(), key=lambda x: x[1].get("score", 0), reverse=True)
    return [(int(uid), info) for uid, info in sorted_scores[:10]]
