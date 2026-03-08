import sys
import os
from pystray import Icon as icon, Menu as menu, MenuItem as item
from PIL import Image, ImageDraw
import psutil


def on_clicked(icon, _item):
    icon.stop()
    parent_pid = os.getpid()
    parent = psutil.Process(parent_pid)
    # or parent.children() for recursive=False
    for child in parent.children(recursive=True):
        child.kill()
    parent.kill()
    sys.exit(0)


def setup_tray_icon():
    icon('test', Image.open(os.path.dirname(__file__) + '/kao.png'), menu=menu(
        item(
            'Exit',
            on_clicked
        ))).run_detached()
