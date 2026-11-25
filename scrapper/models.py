from django.db import models
from basics.models import BaseModel
from company.models import Company

CHOICES = [
    ('pending', 'Pending'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
]

class ScrapperJob(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE,related_name='scrapper_jobs')
    source_url = models.URLField()
    status = models.CharField(max_length=50, choices=CHOICES,default='pending')
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

class ScrapperItem(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE,related_name='scrapper_items')
    job = models.ForeignKey(ScrapperJob, on_delete=models.CASCADE,related_name='items')
    parsed_data = models.JSONField(default=dict,blank=True)

# Create your models here.
