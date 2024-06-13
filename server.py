from flask import Flask, jsonify
from dependencies.database_class import DatabaseConnector

app = Flask(__name__)

db_connector = DatabaseConnector("database/radar_database.db")
db_connector.connect()


@app.route('/robot-data', methods=['GET'])
def robot_data():
    latest_data = db_connector.fetch_latest_data()
    # Dictionary with data
    obj_dict = {
        "Obj_Detected": latest_data['Obj_Detected'],
        "Obj_detection_flag": latest_data['Obj_detection_flag'],
        "Threshold": latest_data['Threshold'],
        "Sum": latest_data['Sum'],
        "Scene_Image": latest_data["Scene_Image"]
    }

    return jsonify(obj_dict)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)  # Run on all interfaces at port 5001
