from flask import Blueprint

api = Blueprint('api', __name__)

from . import light_ctrl
