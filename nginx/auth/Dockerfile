FROM python:3.12-alpine
WORKDIR /app
COPY app.py login.html ./
USER nobody
CMD ["python", "-u", "app.py"]
