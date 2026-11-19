"""Opens the stage in a fullscreen window and runs the engine beside it."""
import os
import sys

import webview

from .server import Server


def run(main, port=8765, fullscreen=True):
    """Start the server, open the stage window, and call main(server) in a
    worker thread (the window toolkit needs the main thread)."""
    server = Server(port)
    server.start()
    window = webview.create_window("VisionTouch", f"http://127.0.0.1:{port}/", fullscreen=fullscreen)
    server.view = window  # lets tests steer the page

    def body():
        try:
            main(server)
        finally:
            window.destroy()

    webview.start(body)
    # Leave without the interpreter's shutdown sequence: the window toolkit's
    # background threads can call back into Python while it is being torn
    # down, which crashes the process on exit.
    sys.stdout.flush()
    os._exit(0)
