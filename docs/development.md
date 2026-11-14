# دليل تطوير النسخة المكتبية

التطوير الحالي داخل `DormitoryManagement/`. يحتوي `legacy/django/` النسخة السابقة
المحفوظة مستقلة؛ لا تخلط مكتباتها أو قواعد بياناتها مع النسخة المكتبية.

## التشغيل والتطوير

للتشغيل اليومي افتح `start-native.cmd` من جذر المشروع. يفضّل المشغّل ملف EXE المبني
إذا كان موجودًا. لرؤية تعديلات المصدر مباشرةً، افتح PowerShell داخل
`DormitoryManagement` ونفّذ:

```powershell
.\.venv\Scripts\python.exe main.py
```

دليل إنشاء بيئة جديدة ومتطلبات Python موجود في
[دليل النسخة المكتبية](../DormitoryManagement/README.md).
البيئة الحالية تعتمد على `.tools/python313/` في جذر المشروع؛ لا تنقل هذا المفسر
أو تحذف البيئة `.venv` اعتقادًا أنها ملفات بناء مؤقتة.

## أين تضيف التعديل؟

| نوع التعديل | الموقع |
| --- | --- |
| شاشة تسجيل الطلبة والقوائم والتصفية | `DormitoryManagement/app/ui/` |
| قواعد حفظ الطلبة والسكن والاستيراد والتقارير | `DormitoryManagement/app/services/` |
| نماذج البيانات والترحيلات وفحص سلامة القاعدة | `DormitoryManagement/app/database/` |
| حساب العام الدراسي والتحقق من صيغته | `DormitoryManagement/app/academic_year.py` |
| إرفاق مستمسكات الطالب ومعاينتها وحفظها | `DormitoryManagement/app/ui/student_documents.py` و`DormitoryManagement/app/services/document_service.py` |
| الألوان والأنماط والخطوط والبيانات المرجعية | `DormitoryManagement/app/resources/` |
| تحميل أوزان خط الواجهة محليًا | `DormitoryManagement/app/fonts.py` |
| تنسيق خلايا جداول الطلبة وارتفاع الصفوف واتجاه الأرقام | `DormitoryManagement/app/ui/student_table.py` |
| أدوات الاستيراد وبناء EXE وإعداد البيانات المرجعية | `DormitoryManagement/tools/` |
| الاختبارات | `DormitoryManagement/tests/` |
| أدلة الاستخدام والتثبيت والقرارات المعمارية | `DormitoryManagement/docs/` |

الشاشات تستدعي الخدمات، والخدمات تطبق قواعد العمل من خلال طبقة قاعدة البيانات.
حافظ على إصدارات المخطط القديمة `schema_v*.py`؛ تستخدم للتحقق من النسخ الاحتياطية
والترحيل، وليست ملفات مكررة قابلة للحذف.

## الاختبارات والبناء

من مجلد `DormitoryManagement`:

```powershell
New-Item -ItemType Directory -Path .tools\test-runs -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tools\test-runs\manual
.\.venv\Scripts\python.exe tools\build_windows.py
```

يُنتج البناء `dist/AlMuthannaNative/` وملف ZIP وبصمته في `releases/`.
يجب توزيع مجلد EXE كاملًا مع `_internal`، وعدم تضمين قواعد الطلبة أو `.env`.
للتأكد من الحزمة على بيانات اختبار منفصلة:

```powershell
& '.\dist\AlMuthannaNative\AlMuthannaNative.exe' --smoke-test --data-dir '.\.tools\validation\exe' --result '.\.tools\validation\exe-result.json'
```

## الملفات المؤقتة والبيانات

يمكن إعادة إنشاء `build/` و`__pycache__/` و`.pytest_cache/` ومخرجات الاختبارات
المعزولة. أما `dist/` فيستخدمه المشغّل، و`releases/` يحتوي حزم التوزيع المحتفظ بها.
لا يُحذف أي مجلد `.tools` كاملًا: بعض محتوياته مفسر Python أو مكتبات تطوير.

بيانات التشغيل الحالية ونسخها الاحتياطية في
`%LOCALAPPDATA%\AlMuthannaDormitoryNative\`، مستقلة عن ملفات المصدر والتوزيع.
أدلة الاستيراد التاريخية في `archives/` خاصة وغير متتبعة في Git.
