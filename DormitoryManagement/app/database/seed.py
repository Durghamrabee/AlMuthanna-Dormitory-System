"""Install verified bundled reference labels once; never overwrite local edits."""
import json
from pathlib import Path
from sqlalchemy import select
from .models import Province, District, College, Department


def reference_path():
    folder = Path(__file__).resolve().parent.parent / "resources" / "reference_data"
    preferred = folder / "iraq_university.json"
    return preferred if preferred.is_file() else folder / "reference_data.json"


def reference_metadata():
    path = reference_path()
    if not path.is_file():
        return {"limitations": ["لم يُعثر على ملف البيانات المرجعية. أضف المراجع المتحقق منها من الإعدادات قبل تسجيل الطلبة."]}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_reference_data(db):
    data = reference_metadata()
    with db.session(write=True) as session:
        # A nonempty reference table belongs to the local operator. Seeding never
        # recreates renamed rows or silently reactivates disabled local records.
        for key, parent_model, child_model, child_key, parent_fk in (
            ("provinces", Province, District, "districts", "province_id"),
            ("colleges", College, Department, "departments", "college_id"),
        ):
            if session.scalar(select(parent_model.id).limit(1)) is not None:
                continue
            for item in data.get(key, []):
                parent = parent_model(name=item["name"], source_url=item.get("source_url", ""))
                session.add(parent)
                session.flush()
                for child in item.get(child_key, []):
                    if isinstance(child, str):
                        child = {"name": child}
                    session.add(child_model(**{parent_fk: parent.id}, name=child["name"], source_url=child.get("source_url", "")))
