from pymongo import MongoClient

hostname = '192.168.1.64'
port = 27017

client = MongoClient(hostname, port)
db = client['robot_messaging']
robots_collection = db['robots']


def write_bunker_status(obstacle_exists):
    try:
        query = {'robot_name': 'spot_1'}
        robot_exist = robots_collection.find_one(query)
        if robot_exist:
            update = {"$set": {"obstacle": obstacle_exists}}
            result = robots_collection.update_one(query, update)
            if result.modified_count > 0:
                print("Updated DB\n")
            else:
                print("No changes made to the DB\n")
        else:
            return "Robot is not available in the database"
    except Exception as e:
        return f"Error: {e}"
