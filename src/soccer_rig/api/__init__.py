"""REST API module for Soccer Rig."""

from soccer_rig.api.routes import create_api_blueprint
from soccer_rig.api.server import APIServer

__all__ = ["create_api_blueprint", "APIServer"]
