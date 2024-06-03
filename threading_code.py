import threading
import os
import sys

python_executable_path = sys.executable
script_dir = os.path.dirname(os.path.abspath(__file__))


def web_server():
    os.system(f"{python_executable_path} {script_dir}/server.py")


def data_classifier():
    os.system(f"{python_executable_path} {script_dir}/read_radar_data.py")


thread1 = threading.Thread(target=data_classifier)
thread2 = threading.Thread(target=web_server)

thread1.start()
thread2.start()

thread1.join()
thread2.join()

print("Both threads have finished running")
