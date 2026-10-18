FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app && mkdir /data && chown app:app /data
COPY --chown=app:app . .
RUN python -c "import os,runpy,secrets,sys; os.environ['DJANGO_DEBUG']='0'; os.environ['DJANGO_SECRET_KEY']=secrets.token_urlsafe(64); sys.argv=['manage.py','collectstatic','--noinput']; runpy.run_path('manage.py',run_name='__main__')"
USER app
ENV DJANGO_DEBUG=0 DATABASE_PATH=/data/examroom.sqlite3 DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 30 --access-logfile -"]
