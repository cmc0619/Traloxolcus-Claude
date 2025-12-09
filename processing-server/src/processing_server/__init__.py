"""
Soccer Rig Processing Server.

GPU-accelerated video processing pipeline:
- Receives raw recordings from Pi nodes
- Stitches multi-camera footage into panorama
- Runs ML for event detection
- Pushes processed content to viewer server
"""

__version__ = "1.0.0"
