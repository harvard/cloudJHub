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

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters

ec2 = boto3.resource("ec2", region_name=SERVER_PARAMS["REGION"])

servers = Server.select()
instance_ids = [server.server_id for server in servers]
# deletes user/worker instances
ec2.instances.filter(InstanceIds=instance_ids).terminate()
print("Deleting done")


