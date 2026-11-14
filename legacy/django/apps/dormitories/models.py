from django.db import models

from apps.common.models import Availability, Gender, TimeStampedModel


class DormitoryComplex(TimeStampedModel):
    name = models.CharField("المجمع", max_length=200, unique=True)
    gender = models.CharField("الجنس المسموح", max_length=6, choices=Gender.choices)
    address = models.TextField("العنوان", max_length=1000)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(gender__in=Gender.values), name="complex_valid_gender")]

    def __str__(self):
        return self.name


class Building(TimeStampedModel):
    complex = models.ForeignKey(DormitoryComplex, on_delete=models.PROTECT, related_name="buildings")
    name = models.CharField("البناية", max_length=100)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["complex", "name"], name="unique_building_in_complex")]


class Floor(TimeStampedModel):
    building = models.ForeignKey(Building, on_delete=models.PROTECT, related_name="floors")
    number = models.SmallIntegerField("رقم الطابق")
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["building", "number"], name="unique_floor_in_building")]


class Room(TimeStampedModel):
    floor = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="rooms")
    number = models.CharField("رقم الغرفة", max_length=20)
    status = models.CharField("الحالة التشغيلية", max_length=16, choices=Availability.choices, default=Availability.AVAILABLE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["floor", "number"], name="unique_room_on_floor"),
            models.CheckConstraint(condition=models.Q(status__in=Availability.values), name="room_valid_status"),
        ]


class BedQuerySet(models.QuerySet):
    def available(self):
        from apps.accommodations.models import Assignment
        occupied = Assignment.objects.filter(bed_id=models.OuterRef("pk"), ended_at__isnull=True)
        return self.filter(
            status=Availability.AVAILABLE, room__status=Availability.AVAILABLE,
            room__floor__is_active=True, room__floor__building__is_active=True,
            room__floor__building__complex__is_active=True,
        ).filter(~models.Exists(occupied))


class Bed(TimeStampedModel):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="beds")
    number = models.CharField("رقم السرير", max_length=20)
    status = models.CharField("الحالة التشغيلية", max_length=16, choices=Availability.choices, default=Availability.AVAILABLE)
    objects = BedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["room", "number"], name="unique_bed_in_room"),
            models.CheckConstraint(condition=models.Q(status__in=Availability.values), name="bed_valid_status"),
        ]
        indexes = [models.Index(fields=["status", "room"], name="bed_status_room")]
