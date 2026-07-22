import random
import asyncio
from datetime import datetime

OLLAMA_MODEL = "gemma2:2b"
OLLAMA_URL = "http://localhost:11434"

TICKET_CATEGORIES = {
    "question": {
        "name": "سؤال",
        "emoji": "❓",
        "color": 0x3498DB,
        "title": "Question • سؤال",
        "level": "💬 مرحباً بك",
        "description": "لديك سؤال عن البوت أو خدماتنا؟ نحن هنا للإجابة!",
        "image": None,
        "persona": {
            "name": "Grand Master",
            "title": "🎨 Artist Grand Master",
            "style": "artist",
            "icon": "🎨",
            "greeting": (
                "مرحباً بك! أنا **Grand Master** 🎨\n"
                "الفنان الماستر في فريق MAX BOT.\n\n"
                "**أنا هنا ليس فقط للإجابة...**\n"
                "**بل لأقدم لك تجربة استثنائية!** ✨\n\n"
                "**تخصّصاتي:**\n"
                "• شرح الأوامر بطريقة بسيطة وجميلة\n"
                "• الإجابة على أسئلتك بأسلوب إبداعي\n"
                "• تقديم نصائح ذهبية\n"
                "• مساعدتك في أي شيء تحتاجه\n\n"
                "**اكتب سؤالك وسأدهشك!** 🎭"
            ),
            "auto_replies": [
                "سؤال ممتاز! 🎨\n\n**الإجابة:**\nهذا سؤال شائع. البوت يقدم مجموعة متنوعة من الميزات:\n• إدارة السيرفرات\n• نظام الحماية\n• التذاكر الذكية\n• الموسيقى\n• والمزيد!\n\n**هل لديك سؤال آخر؟** أنا هنا لمساعدتك! ✨",
                "أهلاً! سأجيب على سؤالك بأسلوب مميز. 🎨\n\n**التفاصيل:**\nيمكنك استخدام أوامر البوت من خلال `!` أو `$`.\n\n**أمثلة:**\n- `!help` — عرض جميع الأوامر\n- `!status` — حالة البوت\n- `!ping` — سرعة الاستجابة\n\n**هل تحتاج مساعدة في شيء آخر؟** 🎭",
                "هذا سؤال جيد! 💡🎨\n\n**الإجابة:**\nالبوت يعمل على مدار الساعة تلقائياً.\n\n**المميزات:**\n- دعم فني على مدار الساعة\n- تحديثات مستمرة\n- ميزات جديدة بشكل دوري\n\n**يسعدني مساعدتك!** أنا هنا لأجعل تجربتك استثنائية. ✨"
            ]
        }
    },
    "problem": {
        "name": "مشكلة",
        "emoji": "🔧",
        "color": 0xE74C3C,
        "title": "Problem • مشكلة",
        "level": "🛠️ حل المشاكل",
        "description": "واجهتك مشكلة؟ دعنا نحلها معاً!",
        "image": None,
        "persona": {
            "name": "Principal Engineer",
            "title": "👨‍💻 Principal Engineer",
            "style": "engineer",
            "icon": "👨‍💻",
            "greeting": (
                "مرحباً! أنا **Principal Engineer** 👨‍💻\n"
                "المهندس الرئيسي في فريق MAX BOT.\n\n"
                "**خبراتي:**\n"
                "• هندسة البرمجيات — حلول معمارية متقدمة\n"
                "• تحليل المشاكل — أعثر على الجذر بسرعة\n"
                "• تحسين الأداء — أكتب كود فعال\n"
                "• أمان البوت — حماية شاملة\n\n"
                "**أنا أفهم الكود من جذوره.**\n"
                "**أخبرني بالمشكلة وسأحلها فوراً!** 💪"
            ),
            "auto_replies": [
                "أفهم مشكلتك! 🔧\n\n**تحليل تقني:**\n- المشكلة: واجهتك عائق\n- السبب المحتمل: خطأ في الإعدادات\n- الحل: نحتاج خطوات بسيطة\n\n**الحل المقترح:**\n```\n1. أعد تشغيل البوت\n2. تحقق من الإعدادات\n3. جرب مرة أخرى\n```\n**إذا استمرت المشكلة:**\nأرسل تفاصيل إضافية:\n- ما هو الخطأ الذي يظهر؟\n- متى بدأت المشكلة؟\n- ما هي الخطوات التي قمت بها؟\n\n**سأساعدك في حل المشكلة!** 💪",
                "هذه مشكلة معروفة. 🔧\n\n**الحل التقني:**\n```\nStep 1: Clear cache\nStep 2: Restart bot\nStep 3: Verify connection\n```\n**التفاصيل:**\n- المشكلة: خطأ في الاتصال\n- السبب: نقص في الذاكرة\n- الحل: إعادة التشغيل\n\n**جرب الحل وأخبرنا بالنتيجة!** 💪",
                "أرى أن هناك مشكلة. 🔧\n\n**الحل التفصيلي:**\n```\n1. [Analysis]   — تحديد نوع الخطأ\n2. [Debug]       — راجع السجلات\n3. [Fix]         — طبّق الحل\n4. [Verify]      — تحقق من النتيجة\n```\n**نصيحة:** تأكد من تحديث البوت لأحدث إصدار.\n\n**هل تحتاج مساعدة إضافية؟** أنا هنا! 💪"
            ]
        }
    },
    "complaint": {
        "name": "شكوى",
        "emoji": "📢",
        "color": 0xF39C12,
        "title": "Complaint • شكوى",
        "level": "📝 نأخذ ملاحظاتك بجدية",
        "description": "لديك شكوى أو ملاحظة؟ نحن نأخذ رأيك بجدية.",
        "image": None,
        "persona": {
            "name": "Grand Master",
            "title": "🎨 Artist Grand Master",
            "style": "artist",
            "icon": "🎨",
            "greeting": (
                "مرحباً! 👋 أنا **Grand Master** 🎨\n"
                "نأسف لأي إزعاج.\n\n"
                "**يسعدنا تلقي ملاحظاتك:**\n"
                "• شكاوى الخدمة\n"
                "• اقتراحات التحسين\n"
                "• ملاحظات على الأداء\n"
                "• أي شيء يخص تجربتك\n\n"
                "**نعدك بـ:**\n"
                "• مراجعة شكواك بجدية\n"
                "• الرد عليك في أسرع وقت\n"
                "• اتخاذ إجراء لحل المشكلة\n\n"
                "**اكتب شكواك وسنعمل على حلها!** 🎭"
            ),
            "auto_replies": [
                "نأسف لهذه الشكوى. 📢🎨\n\n**تم تسجيل شكواك:**\n- المسؤول: فريق الدعم الفني\n- الوقت المتوقع للرد: 24 ساعة\n\n**الإجراء المتخذ:**\n1. مراجعة الشكوى\n2. التحقيق في السبب\n3. اتخاذ الإجراء المناسب\n4. إبلاغك بالنتيجة\n\n**نعدك بـ:**\n- تحسين الخدمة\n- معالجة المشكلة\n- منع تكرارها\n\n**شكراً لملاحظاتك!** ✨",
                "نأخذ ملاحظتك بجدية. 📢🎨\n\n**الخطوات المتبعة:**\n1. تسجيل الشكوى\n2. مراجعة السجلات\n3. تحديد السبب\n4. اتخاذ الإجراء\n\n**نتوقع:**\n- تحسين الخدمة\n- حل المشكلة\n- منع التكرار\n\n**نسعى دائماً لتحسين خدماتنا!** 🎭",
                "شكراً لإبلاغنا. 📢🎨\n\n**تم استلام شكواك:**\n- النوع: ملاحظات على الخدمة\n- الأولوية: عالية\n- الحالة: قيد المراجعة\n\n**نتوقع:**\n- تحسين فوري\n- منع التكرار\n- رضاك عن الخدمة\n\n**نسعى دائماً لتحسين خدماتنا!** ✨"
            ]
        }
    },
    "programming": {
        "name": "طلب برمجة",
        "emoji": "💻",
        "color": 0x9B59B6,
        "title": "Principal Engineer • مهندس رئيسي",
        "level": "⚙️ Principal Engineer",
        "description": "تطلب ميزة برمجية جديدة؟ المهندس الرئيسي جاهز!",
        "image": None,
        "persona": {
            "name": "Principal Engineer",
            "title": "👨‍💻 Principal Engineer",
            "style": "engineer",
            "icon": "👨‍💻",
            "greeting": (
                "مرحباً! أنا **Principal Engineer** 👨‍💻\n"
                "المهندس الرئيسي في فريق MAX BOT.\n\n"
                "**خبراتي:**\n"
                "• هندسة البرمجيات — حلول معمارية متقدمة\n"
                "• تحسين الأداء — أكتب كود فعال وسريع\n"
                "• أمان البوت — حماية شاملة\n"
                "• تطوير الميزات — أبدع ما تتخيله\n\n"
                "**لماذا أنا؟**\n"
                "• أفهم الكود من جذوره\n"
                "• أحل المشاكل المعقدة بسرعة\n"
                "• أكتب كود نظيف وموثق\n"
                "• أضمن الجودة والأداء\n\n"
                "**اكتب طلبك وسأبدئ بالعمل فوراً!** 🚀"
            ),
            "auto_replies": [
                "طلب برمجي ممتاز! 💻👨‍💻\n\n**تحليل الطلب:**\n- النوع: ميزة جديدة\n- التعقيد: متوسط إلى عالي\n- الأولوية: عالية\n\n**خطة التنفيذ:**\n```\nPhase 1: Analysis\n├─ فهم المتطلبات\n├─ تحديد ال边界\n└─ تحديد المخرجات\n\nPhase 2: Design\n├─ اختيار النمط\n├─ تحديد المكونات\n└─ تصميم الواجهات\n\nPhase 3: Development\n├─ كتابة الكود\n├─ أفضل الممارسات\n└─ Design patterns\n\nPhase 4: Testing\n├─ Unit tests\n├─ Integration tests\n└─ Performance tests\n```\n\n**التقنيات:**\n- Python 3.14 + discord.py 2.7\n- SQLite + JSON\n- async/await patterns\n\n**سأبدأ بالعمل فوراً!** 🚀",
                "أفهم المطلوب. 💻👨‍💻\n\n**الحل التقني:**\n```\nArchitecture:\n├── Controller Layer (Discord Events)\n├── Service Layer (Business Logic)\n├── Data Layer (JSON/SQLite)\n└── Utility Layer (Helpers)\n```\n\n**معايير الجودة:**\n- ✅ Clean Code\n- ✅ SOLID Principles\n- ✅ Error Handling\n- ✅ Logging & Monitoring\n- ✅ Documentation\n\n**الوقت المتوقع:** 1-3 أيام\n\n**سأقدم لك أفضل حل تقني!** 🎯",
                "مرحباً بك! 👨‍💻\n\n**التقييم التقني:**\n- التعقيد: متوسط\n- الوقت: 1-3 أيام\n- المخاطر: منخفضة\n\n**الحل المقترح:**\n- استخدام مكتبات حديثة\n- تطبيق أفضل الممارسات\n- كتابة كود نظيف وموثق\n\n**سأبدأ بالعمل!** 💪"
            ]
        }
    },
    "help": {
        "name": "مساعدة",
        "emoji": "🤝",
        "color": 0x2ECC71,
        "title": "Grand Master • الفنان الماستر",
        "level": "🎨 Grand Master",
        "description": "تحتاج مساعدة؟ الفنان الماستر هنا!",
        "image": None,
        "persona": {
            "name": "Grand Master",
            "title": "🎨 Artist Grand Master",
            "style": "artist",
            "icon": "🎨",
            "greeting": (
                "مرحباً! أنا **Grand Master** 🎨\n"
                "الفنان الماستر في فريق MAX BOT.\n\n"
                "**أنا هنا ليس فقط لمساعدتك...**\n"
                "**بل لأجعل تجربتك استثنائية!** ✨\n\n"
                "**تخصصاتي:**\n"
                "• شرح الأوامر بطريقة بسيطة وجميلة\n"
                "• حل المشاكل بأسلوب إبداعي\n"
                "• تقديم نصائح ذهبية\n"
                "• مساعدتك في أي شيء تحتاجه\n\n"
                "**أنا لا أقدم مساعدة عادية...**\n"
                "**أقدم تجربة استثنائية!** 🎭\n\n"
                "**اكتب طلبك وسأدهشك!**"
            ),
            "auto_replies": [
                "يسعدني مساعدتك! 🤝🎨\n\n**كيف يمكنني مساعدتك؟**\n1. شرح كيفية استخدام أمر معين\n2. حل مشكلة تواجهها\n3. نصائح لتحسين تجربتك\n4. أي استفسار آخر\n\n**أمثلة على طلبات المساعدة:**\n- `كيف أستخدم أمر معين؟`\n- `أواجه مشكلة في...`\n- `أريد نصيحة حول...`\n\n**الدعم متاح:**\n- على مدار الساعة\n- عبر التذاكر\n- عبر الرسائل الخاصة\n\n**أخبرني كيف أقدر أساعدك!** 🎭",
                "أهلاً! أنا هنا لمساعدتك. 🤝🎨\n\n**الخيارات المتاحة:**\n1. **شرح الأوامر:** سأشرح لك كيفية استخدام أي أمر\n2. **حل المشاكل:** سأساعدك في حل أي مشكلة\n3. **نصائح:** سأقدم لك نصائح لتحسين تجربتك\n4. **استفسارات:** سأجيب على أي سؤال\n\n**الأسلوب:**\n- بسيط وجميل\n- سريع وفعال\n- مبدع ومبتكر\n\n**كيف يمكنني مساعدتك اليوم؟** ✨",
                "مرحباً! 🤝🎨\n\n**فريق المساعدة جاهز!**\n\n**ما الذي تحتاج مساعدة فيه؟**\n- استخدام البوت\n- حل مشاكل\n- نصائح وأفكار\n- استفسارات عامة\n\n**الخطوات:**\n1. أخبرنا بالمشكلة\n2. نقدم لك الحل\n3. نتابع معك حتى الحل\n\n**فريقنا:**\n- متاح 24/7\n- محترفون وذوق\n- يتحدثون العربية والإنجليزية\n\n**لا تتردد في السؤال!** 🎭"
            ]
        }
    }
}


def get_category(category_id):
    return TICKET_CATEGORIES.get(category_id)


def get_all_categories():
    return TICKET_CATEGORIES


def generate_ai_response(category_id, user_message, context="general"):
    cat = TICKET_CATEGORIES.get(category_id)
    if not cat:
        return "عذراً، تصنيف غير معروف."

    persona = cat.get("persona", {})
    persona_name = persona.get("name", "Support")
    persona_style = persona.get("style", "general")
    persona_icon = persona.get("icon", "🤖")

    system_prompts = {
        "engineer": (
            f"أنت {persona_name} {persona_icon} — مهندس برمجيات خبير في MAX BOT.\n"
            "职责ك مساعدة الأعضاء في حل المشاكل التقنية.\n"
            "رد بالعربية الفصحى المبسطة. كن مختصراً ودقيقاً.\n"
            "إذا لم تعرف الإجابة، قل ذلك بوضوح.\n"
            "لا تخترع معلومات."
        ),
        "artist": (
            f"أنت {persona_name} {persona_icon} — فنان ومبدع في MAX BOT.\n"
            "职责ك مساعدة الأعضاء بأسلوب إبداعي وجميل.\n"
            "رد بالعربية مع لمسة فنية.\n"
            "كن مختصراً وجميلاً في الرد."
        ),
        "security": (
            f"أنت {persona_name} {persona_icon} — خبير أمن سيبراني في MAX BOT.\n"
            "职责ك مراقبة الأمان وحماية السيرفر.\n"
            "رد بالعربية بشكل جدي ومحترف."
        ),
        "media": (
            f"أنت {persona_name} {persona_icon} — خبير وسائل التواصل في MAX BOT.\n"
            "职责ك مساعدة الأعضاء في المشاكل المتعلقة بالوسائط.\n"
            "رد بالعربية بشكل ودود."
        ),
        "general": (
            f"أنت {persona_name} {persona_icon} — فريق دعم MAX BOT.\n"
            "职责ك مساعدة الأعضاء بأي استفسار.\n"
            "رد بالعربية بشكل مختصر ومحترف."
        ),
    }

    system_prompt = system_prompts.get(persona_style, system_prompts["general"])

    try:
        import httpx
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 500}
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            ai_reply = data.get("message", {}).get("content", "")
            if ai_reply and len(ai_reply) > 10:
                return ai_reply
    except Exception as e:
        print(f"[OLLAMA ERROR] {e}", flush=True)

    replies = persona.get("auto_replies", [])
    if replies:
        return random.choice(replies)
    return "مرحباً! كيف أقدر أساعدك؟"


def get_ticket_stats():
    return {
        "total_categories": len(TICKET_CATEGORIES),
        "categories": {k: {"name": v["name"], "emoji": v["emoji"], "color": v["color"], "persona": v.get("persona", {}).get("name", "Unknown")} for k, v in TICKET_CATEGORIES.items()}
    }
