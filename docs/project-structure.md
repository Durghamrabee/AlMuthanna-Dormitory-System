# هيكل المشروع

نُظّم المشروع يوم 14 تشرين الثاني 2026: حُذف نحو **2.61 GiB** من المخرجات المولّدة،
ونُقلت النسخة القديمة وأدلة الاستيراد إلى مجلدات مستقلة. تطابقت بصمات **11,131 ملفًا**
قبل النقل وبعده. بقيت ملفات تشغيل النسخة المكتبية وبيانات الطلبة محفوظة.

## التشغيل الحالي

- `start-native.cmd`: نقطة تشغيل النسخة المكتبية الحالية.
- `DormitoryManagement/app/`: الشاشات والخدمات وقاعدة البيانات.
- `DormitoryManagement/app/resources/`: الخطوط والأنماط والبيانات المرجعية.
- `DormitoryManagement/main.py`: تشغيل التطبيق من المصدر.
- `DormitoryManagement/tools/`: أدوات البناء والاستيراد وفحص التخطيط.
- `DormitoryManagement/tests/`: الاختبارات الآلية.
- `DormitoryManagement/docs/`: أدلة النسخة المكتبية.
- `DormitoryManagement/dist/AlMuthannaNative/`: ملفات التشغيل الجاهزة؛ تُحفظ كاملة.
- `DormitoryManagement/releases/`: حزم ZIP القابلة للتوزيع.

قاعدة التشغيل الحالية مستقلة عن المشروع في
`%LOCALAPPDATA%\AlMuthannaDormitoryNative\db.sqlite3`.
لم يشمل التنظيف هذا المجلد أو بياناته أو نسخه الاحتياطية.

## ملفات يجب الحفاظ عليها

- ملفات المصدر والاختبارات والأدلة والخطوط والموارد.
- `.git/` و`.vscode/` وإعدادات المستخدم.
- البيئة `DormitoryManagement/.venv/` ومفسرها المشترك `.tools/python313/`.
- البيئة القديمة `.venv/` وحزم أدوات التطوير؛ لا تُعد ملفات مؤقتة.
- قاعدة Django القديمة `legacy/django/db.sqlite3` وإعداداتها `legacy/django/.env`
  ونسخها الاحتياطية في `legacy/django/backups/`.
- أدلة ولقطات الاستيراد في `archives/student-import-2025-2026/`.

## الهيكل الحالي

```text
AlMuthanna-Dormitory-System/
├── start-native.cmd             تشغيل النسخة الحالية
├── start-local.cmd              مدخل متوافق للنسخة القديمة
├── README.md                    دليل مختصر ونقاط التشغيل
├── DormitoryManagement/         مصدر النسخة المكتبية وملفات تشغيلها
│   ├── app/
│   ├── docs/
│   ├── tests/
│   ├── tools/
│   ├── dist/
│   └── releases/                الإصدار الحالي وإصدار سابق للرجوع
├── legacy/
│   └── django/                 النسخة القديمة كاملة مع إعداداتها وبياناتها
├── archives/
│   ├── student-import-2025-2026/ أدلة الاستيراد المحفوظة
│   └── reference-materials/     مراجع إعداد البيانات المحلية
├── .tools/                     المفسر والحزم المساعدة
└── .venv/                      بيئة النسخة القديمة الموجودة
```

نُقلت ملفات النسخة القديمة كوحدة واحدة إلى `legacy/django/`:
`apps/`، `config/`، `desktop/`، `docs/`، `packaging/`، `scripts/`،
`static/`، `templates/`، `tests/`، `AlMuthannaDormitory.spec`،
`desktop_launcher.py`، `manage.py`، ملفات `requirements*.txt`،
ملف README القديم، `.env`، `.env.example`، `db.sqlite3`، `backups/`،
و`dist/` و`releases/` القديمان.

حُدّث مشغّل النسخة القديمة ومسارات أدواتها وروابط الأدلة. بقي `start-native.cmd`
كما هو، وأصبح `start-local.cmd` في الجذر يحيل إلى مشغّل `legacy/django/`.
قورنت بصمات قاعدة البيانات والإعدادات والنسخ الاحتياطية قبل النقل وبعده.
تفاصيل الشاشات والخدمات وأوامر التطوير في [دليل التطوير](development.md).

## ما حُذف وما احتُفظ به

حُذفت مخرجات البناء القابلة لإعادة الإنشاء، وذاكرة pytest المؤقتة،
ومجلدات الاختبارات المعزولة ولقطات التحقق، وحزم الإصدار المتكررة.
احتُفظ بحزمة النسخة المكتبية الحالية بتاريخ 2026-11-14 وحزمة سابقة بتاريخ
2026-11-09، وأحدث حزمة للنسخة القديمة بتاريخ 2026-11-06، مع ملفات بصماتها.
قواعد البيانات التي أزيلت كانت داخل مجلدات الاختبار المعزولة في القائمة المعتمدة.

قائمة المسارات والأحجام التفصيلية موجودة في
[جرد التنظيف المحلي](../.tools/cleanup-inventory.json).
أداة الجرد `.tools/inventory-cleanup.py` تقرأ فقط، ولا تحذف أو تنقل الملفات.

سجلا الحذف في `.tools/cleanup-result.json` و`.tools/cleanup-caches-result.json`،
وبصمات النقل في `.tools/relocation-proof.json`. السجلات محلية وغير متتبعة في Git.
لا تُحذف مجلدات الأدوات أو البيئات أو الأرشيف كاملًا عند إجراء تنظيف لاحق.
