"""Frozen version-1 schema contract for validating backups and safe upgrades."""
from datetime import datetime, timezone

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
    __table_args__ = (CheckConstraint("gender IN ('male', 'female')", name="building_gender"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    building_number: Mapped[str] = mapped_column(String(100), unique=True)
    gender: Mapped[str] = mapped_column(String(6))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Room(Timestamps, Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("building_id", "room_number"), CheckConstraint("capacity > 0 AND capacity <= 1000", name="room_capacity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="RESTRICT"), index=True)
    room_number: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Student(Timestamps, Base):
    __tablename__ = "students"
    __table_args__ = (
        ForeignKeyConstraint(["district_id", "province_id"], ["districts.id", "districts.province_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["department_id", "college_id"], ["departments.id", "departments.college_id"], ondelete="RESTRICT"),
        CheckConstraint("gender IN ('male', 'female')", name="student_gender"),
        CheckConstraint("length(trim(full_name)) > 0", name="student_name"),
        CheckConstraint("length(trim(guardian_name)) > 0 AND length(trim(guardian_phone)) > 0", name="student_guardian"),
        Index("ix_student_search", "full_name", "phone"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable only for safely upgraded legacy records. INSERT trigger requires new IDs.
    university_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    full_name: Mapped[str] = mapped_column(String(250))
    phone: Mapped[str] = mapped_column(String(30), default="")
    gender: Mapped[str] = mapped_column(String(6))
    province_id: Mapped[int] = mapped_column(ForeignKey("provinces.id", ondelete="RESTRICT"), index=True)
    district_id: Mapped[int] = mapped_column(Integer, index=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="RESTRICT"), index=True)
    department_id: Mapped[int] = mapped_column(Integer, index=True)
    guardian_name: Mapped[str] = mapped_column(String(250))
    guardian_phone: Mapped[str] = mapped_column(String(30))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=True, index=True)


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

V1_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS native_student_identifier_insert BEFORE INSERT ON students
       WHEN NEW.university_id IS NULL OR length(trim(NEW.university_id))=0
       BEGIN SELECT RAISE(ABORT,'university_id_required'); END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_identifier_update BEFORE UPDATE OF university_id ON students
       WHEN (OLD.university_id IS NOT NULL AND length(trim(OLD.university_id))>0)
         AND (NEW.university_id IS NULL OR length(trim(NEW.university_id))=0)
       BEGIN SELECT RAISE(ABORT,'university_id_required'); END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_room_insert BEFORE INSERT ON students WHEN NEW.room_id IS NOT NULL
       BEGIN
       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id
          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)
          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;
       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)
          THEN RAISE(ABORT,'room_full') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_room_update BEFORE UPDATE OF room_id,gender ON students WHEN NEW.room_id IS NOT NULL
       BEGIN
       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id
          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)
          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;
       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id AND id<>OLD.id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)
          THEN RAISE(ABORT,'room_full') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_room_update BEFORE UPDATE OF capacity,is_active,building_id ON rooms
       BEGIN
       SELECT CASE WHEN NEW.capacity<(SELECT COUNT(*) FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'capacity_below_occupants') END;
       SELECT CASE WHEN NEW.is_active=0 AND EXISTS(SELECT 1 FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'occupied_room_deactivation') END;
       SELECT CASE WHEN EXISTS(SELECT 1 FROM students s JOIN buildings b ON b.id=NEW.building_id WHERE s.room_id=OLD.id AND (s.gender<>b.gender OR b.is_active=0))
          THEN RAISE(ABORT,'occupied_room_gender') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_building_update BEFORE UPDATE OF gender,is_active ON buildings
       WHEN EXISTS(SELECT 1 FROM students s JOIN rooms r ON s.room_id=r.id WHERE r.building_id=OLD.id AND (s.gender<>NEW.gender OR NEW.is_active=0))
       BEGIN SELECT RAISE(ABORT,'occupied_building_change'); END""",
]

