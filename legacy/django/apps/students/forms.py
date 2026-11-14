from django import forms
from .models import Student, StudentDocument, DocumentType


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["university_number", "full_name", "gender", "date_of_birth", "phone", "governorate", "district", "address", "guardian_name", "guardian_phone", "emergency_name", "emergency_phone", "is_active"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


class DocumentForm(forms.ModelForm):
    class Meta:
        model = StudentDocument
        fields = ["document_type", "file"]
        labels = {"document_type": "نوع المستند"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_type"].queryset = DocumentType.objects.filter(is_active=True)
        self.fields["document_type"].label_from_instance = lambda item: item.name
