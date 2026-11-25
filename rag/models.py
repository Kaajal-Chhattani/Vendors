from django.db import models
from pgvector.django import VectorField
from basics.models import BaseModel
from company.models import Company

SOURCE_TYPE_CHOICES = [
    ('pdf', 'PDF'),
    ('scrape', 'Scraped'),
    ('upload', 'Upload'),
]

STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('started', 'Started'),
    ('processed', 'Processed'),
    ('error', 'Error'),
]

class Document(BaseModel):
    company = models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='documents')
    source_type=models.CharField(max_length=20,choices=SOURCE_TYPE_CHOICES)
    file=models.FileField(upload_to='documents/',blank=True,null=True)
    raw_text=models.TextField(blank=True)
    status=models.CharField(max_length=20,choices=STATUS_CHOICES,default='pending')
    processed_via=models.CharField(max_length=20,blank=True,default='')

    def __str__(self):
        return f"Document {self.id} ({self.source_type})"

class DocumentChunk(BaseModel):
    company = models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='documents_chunks')
    document=models.ForeignKey(Document,on_delete=models.CASCADE,related_name='chunks')
    content=models.TextField()
    embedding=VectorField(dimensions=384,null=True,blank=True)#all-MiniLM-L6-v2 outputs 384-dim vectors
    chunk_index=models.IntegerField()

    def __str__(self):
        return f"Chunk {self.chunk_index} of Document {self.document.id}"

# Create your models here.
