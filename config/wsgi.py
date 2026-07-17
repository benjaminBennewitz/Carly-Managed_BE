# config/wsgi.py
"""WSGI-Einstiegspunkt für klassische HTTP-Server."""

from django.core.wsgi import get_wsgi_application

from config.environment import load_environment

load_environment()
application = get_wsgi_application()
