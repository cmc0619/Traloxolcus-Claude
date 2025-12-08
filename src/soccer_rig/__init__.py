"""
Soccer Rig - Multi-Camera Pi 5 Recording System

A three-camera synchronized 4K recording system for soccer matches.
"""

__version__ = "1.0.0"
__author__ = "Soccer Rig Team"

from soccer_rig.config import Config
from soccer_rig.app import SoccerRigApp

__all__ = ["Config", "SoccerRigApp", "__version__"]
