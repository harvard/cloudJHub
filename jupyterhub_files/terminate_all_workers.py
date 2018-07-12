import boto3
import json
from models import Server
from time import sleep

#######################################################################################
# To assist with deleting a Jupyterhub cluster, this script helps clean up AWS resources
# AWS resources this script deletes:
# - User EC2 instances
# AWS resources that need to be deleted manually:
# - Jupyterhub manager
# - Security groups
# - AMI
# - Subnets
#
# Note the manager must be shut down before you can delete these resources:
# 1) Security groups. However, as they are dependent on one another, they must be deleted in order (e.g. manager_security_group2, worker_security_group, manager_security_group)
# 2) AMI (if will no longer be used)
# 3) Public and private subnets (if will no longer be used)

#################################################################################################

# Note: DO NOT USE THIS SCRIPT UNLESS YOU KNOW WHAT YOU ARE DOING

#################################################################################################


with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters
ec2 = boto3.resource("ec2", region_name=SERVER_PARAMS["REGION"])

def delete_user_ec2(userid):
    try:
        server = Server.get_server(userid)
        server_id = server.server_id
        server.remove_server(server_id)
        user_instance = ec2.Instance(server_id)
        user_instance.terminate()
    except:
        print("no such user or server")
        return 1
    return 0

def check_user_ec2(userid):
    try:
        server = Server.get_server(userid)
        server_id = server.server_id
        user_instance = ec2.Instance(server_id)
        print("user %s , ec2= %s" %(userid, user_instance))
    except:
        print("no such user or server")
        return 1
    return 0

def delete_all_users_ec2s():
    servers = Server.select()
    instance_ids = [server.server_id for server in servers]
    # if instance_ids is empty (i.e no single ec2 instance yet created for a user), 
    # then the functionec2.instances.filter below will 
    # return all the EC2 instances in your environment and apply
    # the termination on them. Therefore it is important to check that the
    # instance_ids have value before calling the terminate function.
    if instance_ids:
        # deletes user/worker instances
        ec2.instances.filter(InstanceIds=instance_ids).terminate()
    else:
        print ("No instance IDs provided")
    print("Deleting done")


#uncomment the line below to call the function
#delete_all_users_ec2s()

