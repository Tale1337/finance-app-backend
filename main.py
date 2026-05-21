import webview
import uvicorn
import threading
import time

from api import app

def run_server():
    """Эта функция запускает бэкенд-сервер"""
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

if __name__ == '__main__':
    print("Запуск...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    time.sleep(0.5)

    print("Открытие окна приложения...")

    webview.settings['ALLOW_DOWNLOADS'] = True

    window = webview.create_window(
        title='ProFinance - Личные финансы',
        url='http://127.0.0.1:8000/docs',
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600)
    )

    webview.start()