import sys
import math
import json
from worker_manager import launch_servers
from models import Server, PendingUser

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f)

def prelaunch_servers(num_users):
    """ Pre-emptively launch servers to avoid server spin-up time for class/lab for parameter num_users"""
    # create PendingUsers
    for user in range(num_users):
        PendingUser.new_user(user)
    # launcher servers
    servers_needed = math.ceil(num_users / SERVER_PARAMS["CONTAINERS_PER_WORKER"])
    if servers_needed > 0:
        servers_to_launch = servers_needed - Server.get_server_count()
        print("Launching %s servers now." % servers_to_launch)
        launch_servers(servers_to_launch)

if __name__ == '__main__':
    num_users = sys.argv[1]
    prelaunch_servers(num_users)
    print("Done prelaunching %s servers." % num_users)
