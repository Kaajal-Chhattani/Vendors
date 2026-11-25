from django.db import models
from basics.models import BaseModel

COMPANY_TYPE_CHOICES = [
    ('vendor', 'Vendor'),
    ('supplier', 'Supplier'),
    ('manufacturer', 'Manufacturer'),
    ('distributor', 'Distributor'),
]

class Company(BaseModel):
    name=models.CharField(max_length=255)
    slug=models.SlugField(max_length=255,unique=True)
    company_type=models.CharField(max_length=255, choices=COMPANY_TYPE_CHOICES)

    class Meta:
        permissions = [
            ("view_all_companies", "Can see data of all companies"),
        ]

    def __str__(self):
        return self.name
    

# Create your models here.
