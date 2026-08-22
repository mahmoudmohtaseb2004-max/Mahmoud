# Admin Inbox Bot v2 — نسخة Render

بوت إنبوكس إداري async كامل، معدّل للعمل على **خطة Render المجانية** عبر
حيلة "keep-alive": سيرفر ويب بسيط يخلي Render يصنّف البوت كـ Web Service
(المسموح مجاناً)، مع خدمة مجانية (UptimeRobot) تبعتله طلب كل كام دقيقة
عشان يفضل صاحي وما ينامش بعد 15 دقيقة من عدم النشاط.

## المتطلبات قبل البدء
1. حساب **GitHub** (مجاني)
2. حساب **Render** (مجاني) — https://render.com
3. حساب **Upstash** (مجاني، بديل Redis سحابي) — https://upstash.com
4. حساب **UptimeRobot** (مجاني) — https://uptimerobot.com

---

## الخطوة 1: إنشاء قاعدة بيانات Upstash (بديل Redis)

1. سجّل في https://upstash.com
2. **Create Database** → اختار اسم، والمنطقة الأقرب لك
3. بعد الإنشاء، انسخ الرابط اللي يبدأ بـ **`rediss://`** (مو `redis://` العادي — مهم جداً لأن Upstash بيستخدم TLS)
4. احتفظ بيه، هتحطه في متغير `REDIS_URL` بـ Render لاحقاً

## الخطوة 2: رفع الكود على GitHub

1. أنشئ مستودع (Repository) جديد على GitHub، خليه **Private** (بما إن فيه بيانات حساسة لو نسيت تشيل .env)
2. من جهازك، جوه مجلد المشروع:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO_NAME.git
git push -u origin main
```
**تأكد إن ملف `.env` ما اترفعش** (موجود في `.gitignore` أصلاً، بس تأكد بعد الرفع من صفحة GitHub إنه مش ظاهر).

## الخطوة 3: إنشاء Web Service على Render

1. سجّل دخول Render، اضغط **New → Web Service**
2. اربطه بمستودع GitHub اللي عملته
3. اختار:
   - **Environment**: Docker
   - **Plan**: Free
4. تحت **Environment Variables**، ضيف:
   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | التوكن بتاعك من BotFather |
   | `ADMIN_GROUP_ID` | معرف مجموعة الإدارة (بيبدأ بـ `-100...`) |
   | `REDIS_URL` | رابط Upstash اللي نسخته (`rediss://...`) |
5. اضغط **Create Web Service**

Render هيبني الـ Docker image ويشغّله تلقائياً. راقب الـ **Logs** لحد ما تشوف:
```
🚀 البوت @اسمك_bot يعمل الآن ومستعد لاستقبال الرسائل...
🌐 سيرفر keep-alive شغال على المنفذ ...
```

## الخطوة 4: منع الـ "نوم" عبر UptimeRobot

1. من صفحة الـ Web Service في Render، انسخ الرابط العام (شكله `https://admin-inbox-bot-xxxx.onrender.com`)
2. سجّل في https://uptimerobot.com
3. **Add New Monitor**:
   - Monitor Type: **HTTP(s)**
   - URL: الرابط اللي نسخته من Render
   - Monitoring Interval: **5 minutes**
4. احفظ

هذا هيخلي UptimeRobot يبعت طلب كل 5 دقائق، فـ Render ما يعتبرش البوت "خامل" وما يدخلش في وضع النوم (اللي بيصير بعد 15 دقيقة عدم نشاط).

---

## ملاحظات مهمة

- **البوت هيفضل شغال 24/7** طالما UptimeRobot شغال وبيبعت الطلبات بانتظام.
- أي تحديث على الكود: `git push` لنفس المستودع، وRender هيعيد النشر تلقائياً (Auto-Deploy مفعّل افتراضياً).
- خطة Render المجانية عندها حد شهري لساعات التشغيل (750 ساعة/شهر تقريباً) — كافي لخدمة واحدة تشتغل 24/7 طول الشهر.
- لو حبيت تتابع اللوج: من لوحة Render، تبويب **Logs** مباشرة.

## هيكل المشروع

```
bot_v2/
├── main.py              # التشغيل + سيرفر keep-alive
├── config.py             # الإعدادات (بما فيها PORT لـ Render)
├── storage.py             # التفاعل مع Redis/Upstash
├── permissions.py          # التحقق من صلاحيات الأدمن
├── utils.py                # تنظيف HTML + مجمّع الألبومات
├── logging_setup.py         # إعداد الـ logging
├── handlers/
│   ├── user.py               # هاندلرز المستخدم
│   └── admin.py                # هاندلرز الأدمن
├── requirements.txt
├── Dockerfile
├── render.yaml             # Blueprint اختياري لنشر بضغطة واحدة
├── .env.example
└── .gitignore
```
