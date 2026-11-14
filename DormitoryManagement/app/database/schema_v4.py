"""Immutable version 4 schema for migration and backup verification."""
from datetime import datetime, timezone

from app.academic_year import current_academic_year

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Province(Timestamps, Base):
    __tablename__ = "provinces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_url: Mapped[str] = mapped_column(Text, default="")


class District(Timestamps, Base):
    __tablename__ = "districts"
    __table_args__ = (UniqueConstraint("province_id", "name"), UniqueConstraint("id", "province_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    province_id: Mapped[int] = mapped_column(ForeignKey("provinces.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_url: Mapped[str] = mapped_column(Text, default="")


class College(Timestamps, Base):
    __tablename__ = "colleges"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_url: Mapped[str] = mapped_column(Text, default="")


class Department(Timestamps, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("college_id", "name"), UniqueConstraint("id", "college_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_url: Mapped[str] = mapped_column(Text, default="")


class Building(Timestamps, Base):
    __tablename__ = "buildings"
    __table_args__ = (CheckConstraint("gender IN ('male', 'female')", name="building_gender"),
                      UniqueConstraint("gender", "building_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    building_number: Mapped[str] = mapped_column(String(100))
    gender: Mapped[str] = mapped_column(String(6))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Room(Timestamps, Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("building_id", "room_number"), UniqueConstraint("id", "building_id"),
                      CheckConstraint("(capacity IS NOT NULL AND capacity > 0 AND capacity <= 1000) OR (capacity IS NULL AND is_active=0)", name="room_capacity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="RESTRICT"), index=True)
    room_number: Mapped[str] = mapped_column(String(50))
    # Previous-year imports may identify a physical room without its capacity.
    # An unknown capacity is never assignable or included in available places.
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (CheckConstraint("length(source_sha256)=64", name="import_source_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    academic_year: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Student(Timestamps, Base):
    __tablename__ = "students"
    __table_args__ = (
        ForeignKeyConstraint(["district_id", "province_id"], ["districts.id", "districts.province_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["department_id", "college_id"], ["departments.id", "departments.college_id"], ondelete="RESTRICT"),
        CheckConstraint("gender IN ('male', 'female')", name="student_gender"),
        CheckConstraint("length(trim(full_name)) > 0", name="student_name"),
        CheckConstraint("import_batch_id IS NOT NULL OR (length(trim(guardian_name)) > 0 AND length(trim(guardian_phone)) > 0)", name="student_guardian"),
        CheckConstraint("import_batch_id IS NOT NULL OR (province_id IS NOT NULL AND district_id IS NOT NULL AND college_id IS NOT NULL AND department_id IS NOT NULL)", name="student_required_references"),
        CheckConstraint("district_id IS NULL OR province_id IS NOT NULL", name="student_district_parent"),
        CheckConstraint("department_id IS NULL OR college_id IS NOT NULL", name="student_department_parent"),
        CheckConstraint("room_id IS NULL OR import_batch_id IS NULL OR (university_id IS NOT NULL AND length(trim(university_id)) > 0 AND province_id IS NOT NULL AND district_id IS NOT NULL AND college_id IS NOT NULL AND department_id IS NOT NULL AND length(trim(guardian_name)) > 0 AND length(trim(guardian_phone)) > 0)", name="student_import_accommodation"),
        Index("ix_student_search", "full_name", "phone"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # Imports retain absent identifiers as NULL. New manual registrations stay strict.
    university_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    academic_year: Mapped[str] = mapped_column(String(20), default=current_academic_year, index=True)
    full_name: Mapped[str] = mapped_column(String(250))
    phone: Mapped[str] = mapped_column(String(30), default="")
    gender: Mapped[str] = mapped_column(String(6))
    province_id: Mapped[int | None] = mapped_column(ForeignKey("provinces.id", ondelete="RESTRICT"), nullable=True, index=True)
    district_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    college_id: Mapped[int | None] = mapped_column(ForeignKey("colleges.id", ondelete="RESTRICT"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    guardian_name: Mapped[str] = mapped_column(String(250), default="")
    guardian_phone: Mapped[str] = mapped_column(String(30), default="")
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=True, index=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=True, index=True)


class ImportRecord(Base):
    __tablename__ = "import_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "sheet_name", "row_number"),
        ForeignKeyConstraint(["source_room_id", "source_building_id"], ["rooms.id", "rooms.building_id"], ondelete="RESTRICT"),
        CheckConstraint("source_room_id IS NULL OR source_building_id IS NOT NULL", name="import_room_parent"),
        CheckConstraint("row_number > 0", name="import_row_number"),
        CheckConstraint("CASE WHEN json_valid(raw_json) THEN json_type(raw_json)='object' ELSE 0 END", name="import_raw_json"),
        CheckConstraint("CASE WHEN json_valid(warnings_json) THEN json_type(warnings_json)='array' ELSE 0 END", name="import_warnings_json"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(120))
    row_number: Mapped[int] = mapped_column(Integer)
    raw_json: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    source_building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_room_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class AccommodationHistory(Base):
    __tablename__ = "accommodation_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), index=True)
    previous_room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"))
    new_room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SchemaMeta(Base):
    __tablename__ = "native_schema"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    application: Mapped[str] = mapped_column(String(100))

V4_TRIGGERS = ["CREATE TRIGGER IF NOT EXISTS native_student_identifier_insert BEFORE INSERT ON students\n       WHEN (NEW.university_id IS NULL OR length(trim(NEW.university_id))=0) AND NEW.import_batch_id IS NULL\n       BEGIN SELECT RAISE(ABORT,'university_id_required'); END", "CREATE TRIGGER IF NOT EXISTS native_student_identifier_update BEFORE UPDATE OF university_id ON students\n       WHEN (OLD.university_id IS NOT NULL AND length(trim(OLD.university_id))>0)\n         AND (NEW.university_id IS NULL OR length(trim(NEW.university_id))=0)\n       BEGIN SELECT RAISE(ABORT,'university_id_required'); END", "CREATE TRIGGER IF NOT EXISTS native_student_room_insert BEFORE INSERT ON students WHEN NEW.room_id IS NOT NULL\n       BEGIN\n       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id\n          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)\n          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;\n       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)\n          THEN RAISE(ABORT,'room_full') END; END", "CREATE TRIGGER IF NOT EXISTS native_student_room_update BEFORE UPDATE OF room_id,gender ON students WHEN NEW.room_id IS NOT NULL\n       BEGIN\n       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id\n          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)\n          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;\n       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id AND id<>OLD.id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)\n          THEN RAISE(ABORT,'room_full') END; END", "CREATE TRIGGER IF NOT EXISTS native_room_update BEFORE UPDATE OF capacity,is_active,building_id ON rooms\n       BEGIN\n       SELECT CASE WHEN NEW.capacity<(SELECT COUNT(*) FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'capacity_below_occupants') END;\n       SELECT CASE WHEN NEW.is_active=0 AND EXISTS(SELECT 1 FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'occupied_room_deactivation') END;\n       SELECT CASE WHEN EXISTS(SELECT 1 FROM students s JOIN buildings b ON b.id=NEW.building_id WHERE s.room_id=OLD.id AND (s.gender<>b.gender OR b.is_active=0))\n          THEN RAISE(ABORT,'occupied_room_gender') END; END", "CREATE TRIGGER IF NOT EXISTS native_building_update BEFORE UPDATE OF gender,is_active ON buildings\n       WHEN EXISTS(SELECT 1 FROM students s JOIN rooms r ON s.room_id=r.id WHERE r.building_id=OLD.id AND (s.gender<>NEW.gender OR NEW.is_active=0))\n       BEGIN SELECT RAISE(ABORT,'occupied_building_change'); END", "CREATE TRIGGER IF NOT EXISTS native_student_year_insert BEFORE INSERT ON students\n       WHEN NEW.academic_year NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'\n         OR length(NEW.academic_year)<>9\n         OR CAST(substr(NEW.academic_year,1,4) AS INTEGER)<1900\n         OR CAST(substr(NEW.academic_year,6,4) AS INTEGER)<>CAST(substr(NEW.academic_year,1,4) AS INTEGER)+1\n       BEGIN SELECT RAISE(ABORT,'invalid_academic_year'); END", "CREATE TRIGGER IF NOT EXISTS native_student_year_update BEFORE UPDATE ON students\n       WHEN NEW.academic_year NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'\n         OR length(NEW.academic_year)<>9\n         OR CAST(substr(NEW.academic_year,1,4) AS INTEGER)<1900\n         OR CAST(substr(NEW.academic_year,6,4) AS INTEGER)<>CAST(substr(NEW.academic_year,1,4) AS INTEGER)+1\n       BEGIN SELECT RAISE(ABORT,'invalid_academic_year'); END"]
