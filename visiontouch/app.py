"""Opens the stage in a fullscreen window and runs the engine beside it."""
import webview

from .server import Server


def run(main, port=8765, fullscreen=True):
    """Start the server, open the stage window, and call main(server) in a
    worker thread (the window toolkit needs the main thread)."""
    server = Server(port)
    server.start()
    window = webview.create_window("VisionTouch", f"http://127.0.0.1:{port}/", fullscreen=fullscreen)

    def body():
        try:
            main(server)
        finally:
            window.destroy()

    webview.start(body)
