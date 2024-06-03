import sqlite3
import threading
import json


class DatabaseConnector:
    def __init__(self, db_file):
        self.conn = None
        self.db_file = db_file
        self.lock = threading.Lock()  # Create a lock for synchronization

    def connect(self):
        self.conn = sqlite3.connect(self.db_file, isolation_level=None, timeout=10, check_same_thread=False)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def create_schema(self):
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.execute('''
            CREATE TABLE IF NOT EXISTS obj_table (
                Obj_Detected TEXT,
                Obj_detection_flag TEXT,
                Threshold REAL,
                Sum REAL,
                Scene_Image TEXT
            )
            ''')
            conn.close()

    def insert_data(self, obj_dict):
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            scene_image_json = json.dumps(obj_dict['Scene_Image'])  # Serialize the matrix to JSON
            conn.execute('''
            INSERT INTO obj_table (Obj_Detected, Obj_detection_flag, Threshold, Sum, Scene_Image)
            VALUES (?, ?, ?, ?, ?)
            ''', (obj_dict['Obj_Detected'], obj_dict['Obj_detection_flag'], obj_dict['Threshold'], obj_dict['Sum'], scene_image_json))
            # Commit the transaction
            conn.commit()

            # Close the connection
            conn.close()

    def fetch_all_data(self):
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.execute('SELECT * FROM obj_table')
            rows = cursor.fetchall()
            conn.close()
            return rows

    def fetch_data(self, limit):
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.execute('SELECT * FROM obj_table ORDER BY rowid DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return rows

    def fetch_latest_data(self):
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.execute('SELECT * FROM obj_table ORDER BY rowid DESC LIMIT 1')
            row = cursor.fetchone()
            conn.close()
            if row:
                obj_dict = {
                    "Obj_Detected": row[0],
                    "Obj_detection_flag": row[1],
                    "Threshold": row[2],
                    "Sum": row[3],
                    "Scene_Image": json.loads(row[4])  # Deserialize the JSON string back into a Python list
                }
                return obj_dict
            else:
                return None
