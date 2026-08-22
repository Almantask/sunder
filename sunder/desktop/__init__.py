"""Native window launcher for the Sunder desktop app."""

from __future__ import annotations


def launch(host: str = "127.0.0.1", port: int = 0, browser: bool = False) -> int:
    import threading
    import webbrowser

    from sunder.desktop.server import make_server

    httpd = make_server(host, port)
    bound_host, bound_port = httpd.server_address[:2]
    url = f"http://{bound_host}:{bound_port}/"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="sunder-http")
    thread.start()
    print(f"Sunder desktop at {url}", flush=True)
    try:
        if browser:
            webbrowser.open(url)
            print("Press Ctrl+C to stop the server.", flush=True)
            try:
                thread.join()
            except KeyboardInterrupt:
                print("Stopping.", flush=True)
            return 0
        try:
            import webview
        except ImportError:
            print("pywebview is not installed; opening the system browser instead.", flush=True)
            print("Install it with: pip install pywebview", flush=True)
            webbrowser.open(url)
            try:
                thread.join()
            except KeyboardInterrupt:
                print("Stopping.", flush=True)
            return 0
        webview.create_window(
            "Sunder",
            url,
            width=1380,
            height=860,
            min_size=(1024, 680),
            background_color="#08090c",
            text_select=True,
        )
        webview.start()
        return 0
    finally:
        httpd.shutdown()


__all__ = ["launch"]
