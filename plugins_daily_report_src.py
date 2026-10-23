#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_report — Отчёт за день (плагин меню «Статистика»). v1.1.8"""
__version__ = '1.0.0'
__description__ = 'Отчёт за день: KPI, отделы, сотрудники, лента отметок'
__author__ = 'reestr'
__enabled__ = True

from datetime import datetime, date
from flask import jsonify, request, Response, redirect

_CSS_VARS = '''
:root{--pg-bg:#0d1117;--pg-card-bg:#161b22;--pg-card-border:#232a33;--pg-text:#e6edf3;
--pg-desc:#9aa7b3;--pg-meta:#6e7c8a;--pg-accent:#00897b;--pg-accent-2:#26a69a;--pg-accent-bg:rgba(0,137,123,.14);
--pg-input-bg:#1a2027;--pg-red:#ec7063;--pg-yellow:#f5d76e;--pg-blue:#5dade2;--pg-green:#58d68d}
