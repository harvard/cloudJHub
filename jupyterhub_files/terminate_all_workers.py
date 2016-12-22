import boto3
import json
from models import Server
from time import sleep
# To assist with deleting a Jupyterhub cluster, this script helps clean up AWS resources
# AWS resources this script deletes:
# - User EC2 instances
# - User EBS volumes
# AWS resources that need to be deleted manually:
# - Jupyterhub manager
# - Security groups
# - AMI
# - Subnets (in applicable)

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters

ec2 = boto3.resource("ec2", region_name=SERVER_PARAMS["REGION"])

servers = Server.select()
instance_ids = [server.server_id for server in servers]
# deletes user/worker instances
ec2.instances.filter(InstanceIds=instance_ids).terminate()
sleep(3)

# ebs_ids = [server.ebs_volume_id for server in servers]
# deletes user EBS volumes
# try:
#     for ebs_id in ebs_ids:
#         volume = ec2.Volume(ebs_id)
#         volume.delete()
# except boto3.ClientError:
#     print("Not all volumes deleted. Please run script again")

print("Deleting done")
# manager must be shut down before you can delete:
# 1) security groups, in this order: manager_security_group2, worker_security_group, manager_security_group
# 2) AMI, if is custom image and will no longer be used
# 3) public and private subnets, if will no longer be used

