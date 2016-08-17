# -*- coding: utf8 -*-
"""Extensions module for libcrowds-analyst."""

from libcrowds_analyst.zip_builder import ZipBuilder
from libcrowds_analyst.api_client import APIClient
from flask_wtf.csrf import CsrfProtect
from flask.ext.z3950 import Z3950Manager


__all__ = ['zip_builder', 'csrf', 'z3950_manager', 'api_client']


zip_builder = ZipBuilder()
csrf = CsrfProtect()
z3950_manager = Z3950Manager()
api_client = APIClient()