#!/usr/bin/env python
"""
This sets up a JypyterHub cluster.  This script requires Python 2.7 due to Fabric
not being Python 3 compatible

  Author: Zagaran, Inc. <info@zagaran.com>
    --
      <kevin@zagaran.com>
      <eli@zagaran.com>
      <zags@zagaran.com>
"""
import json
import argparse
import boto3
import json
import logging
import os
import sys
from time import sleep
from botocore.exceptions import ClientError, WaiterError
from fabric.api import env, run, put, sudo
from fabric.exceptions import NetworkError

from secure import (AWS_ACCESS_KEY_ID, AWS_SECRET_KEY, KEY_NAME, KEY_PATH,
                    MANAGER_IAM_ROLE, VPC_ID)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# optional: make boto output less
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)

with open("launch_cluster/instance_config.json", "r") as f:
    CONFIG_DEFAULTS = json.load(f)

class RemoteCmdExecutionError(Exception): pass

#global fabric config
env.abort_exception = RemoteCmdExecutionError
env.abort_on_prompts = True


def launch_manager(config):
    """ Creates security groups, Jupyterhub manager, and worker AMI. Refer to README.md for details on what the
        launch script does. """
    
    logger.info("collecting AWS resources")
    public_subnet = subnet_connection(config.region, config.public_subnet_id)
    ec2 = ec2_connection(config.region)
    worker_security_group, manager_security_group, manager_security_group2 = create_server_security_groups()

    # Create worker AMI
    if not config.custom_worker_ami:
        logger.info("Creating worker AMI")
        # Run worker setup
        worker_ami_id = make_worker_ami(config, ec2, [manager_security_group.id, manager_security_group2.id])
    else:
        logger.info("Custom worker AMI id '%s' specified. Using custom AMI to launch worker user servers." % config.custom_worker_ami)
        worker_ami_id = config.custom_worker_ami

    # Launch the manager
    logger.info("Launching manager instance")
    instance = launch_server(config, ec2, [manager_security_group.id, manager_security_group2.id])

    # Add server tags
    availability_zone = public_subnet.availability_zone
    instance_name = "JUPYTER_HUB_%s_%s_MANAGER" % (availability_zone.split("-")[-1], config.cluster_name)
    tags = [
        {"Key": "Name", "Value": instance_name},
        {"Key": "Owner", "Value": config.server_owner},
        {"Key": "Creator", "Value": config.server_owner},
        {"Key": "Jupyter Cluster", "Value": config.cluster_name},
    ]
    instance.wait_until_exists()
    instance.wait_until_running()
    instance.create_tags(Tags=tags)
    
    # Configure fabric
    env.host_string = instance.public_ip_address
    env.key_filename = KEY_PATH
    env.user = config.server_username

    # Wait for server to finish booting (literally keep trying until you can
    # successfully run a command on the server via ssh)
    retry(run, "# waiting for ssh to be connectable...", max_retries=100)

    # These parameters will be used by the manager to launch a worker
    worker_server_name = "JUPYTER_HUB_%s_%s_WORKER" % (availability_zone.split("-")[-1], config.cluster_name)

    server_params = {
        "REGION": config.region,
        "AVAILABILITY_ZONE": str(availability_zone),
        "WORKER_SECURITY_GROUPS": [worker_security_group.id],
        "WORKER_AMI": worker_ami_id,
        "WORKER_SERVER_NAME": worker_server_name,
        "WORKER_SERVER_OWNER": config.server_owner,
        "SERVER_USERNAME": config.server_username,
        "KEY_NAME": KEY_NAME,
        "JUPYTER_CLUSTER": config.cluster_name,
        "INSTANCE_TYPE": config.worker_instance_type,
        "WORKER_EBS_SIZE": config.worker_ebs_size,
        "SUBNET_ID": config.private_subnet_id,
        "JUPYTER_NOTEBOOK_TIMEOUT": int(config.jupyter_notebook_timeout),
        "JUPYTER_MANAGER_IP": instance.public_ip_address,
        "MANAGER_IP_ADDRESS": str(instance.private_ip_address),
    }

    # Setup the common files and settings between manager and worker.
    setup_manager(server_params, config, instance.private_ip_address)

    # For security, close port 22 on manager security group to prevent SSH access to manager host
    # logger.info("Closing port 22 on manager")
    # manager_security_group.revoke_ingress(
    #         FromPort=22, ToPort=22, IpProtocol="TCP", CidrIp="0.0.0.0/0"
    # )
    print("Launch script done.")


def setup_manager(server_params,config, manager_ip_address):
    """ Sets up the files that are common to both workers and the manager,
        runs before worke and jupyterhub setup. """
    put("common_files", remote_path="/var/tmp/")
    # upload key to manager for usage of SSHing into worker servers
    put(KEY_PATH, remote_path="/home/%s/.ssh/%s" % (server_params["SERVER_USERNAME"], KEY_NAME))
    sudo("chmod 600 /home/%s/.ssh/%s" % (server_params["SERVER_USERNAME"], KEY_NAME))
    # bash environment configuration files (for devs and admins)worker_security_group
    run("cp /var/tmp/common_files/.inputrc ~/")
    run("cp /var/tmp/common_files/.bash_profile ~/")
    # Common installs: python 3
    sudo("apt-get -qq -y update")
    #sudo("apt-get -qq -y install -q python3.4 python3-pip sqlite sysv-rc-conf", quiet=True)
    sudo("apt-get -qq -y install -q python3-pip sqlite sysv-rc-conf", quiet=True)
    sudo ("pip3 install --force-reinstall --upgrade pip")
    #sudo("easy_install3 pip", quiet=True)
    sudo("pip3 --quiet install ipython nbgrader", quiet=True)
    # Sets up jupyterhub components
    put("jupyterhub_files", remote_path="/var/tmp/")
    sudo("cp -r /var/tmp/jupyterhub_files /etc/jupyterhub")
    # pip installs
    sudo("pip3 install --quiet -r /var/tmp/jupyterhub_files/requirements_jupyterhub.txt")
    # apt-get installs for jupyterhub
    sudo("apt-get -qq -y install -q nodejs-legacy npm")
    # npm installs for the jupyterhub proxy
    sudo("npm install -q -g configurable-http-proxy")
    # move init script into place so we can have jupyterhub run as a "service".
    sudo("cp /var/tmp/jupyterhub_files/jupyterhub_service.sh /etc/init.d/jupyterhub")
    sudo("chmod +x /etc/init.d/jupyterhub")
    sudo("systemctl daemon-reload")
    sudo("sysv-rc-conf --level 5 jupyterhub on")
    # Put the server_params dict into the environment
    sudo("echo '%s' > /etc/jupyterhub/server_config.json" % json.dumps(server_params))
    # Generate a token value for use in making authenticated calls to the jupyterhub api
    # Note: this value cannot be put into the server_params because the file is imported in our spawner
    sudo("/usr/local/bin/jupyterhub token -f /etc/jupyterhub/jupyterhub_config.py __tokengeneratoradmin > /etc/jupyterhub/api_token.txt")
    # start jupyterhub
    sudo("service jupyterhub start", pty=False)
    # move our cron script into place
    sudo("cp /etc/jupyterhub/jupyterhub_cron.txt /etc/cron.d/jupyterhub_cron")
    if not config.custom_worker_ami:
        logger.info("Manager server successfully launched. Please wait 15 minutes for the worker server AMI image to become available. No worker servers (and thus, no user sessions) can be launched until the AMI is available.")
    # TODO: generate ssl files and enable jupyterhub ssl


def make_worker_ami(config, ec2, security_group_list):
    """ Sets up worker components, runs before jupyterhub setup, after common setup. """
    instance = launch_server(config, ec2, security_group_list, size=int(config.worker_ebs_size))
    instance.wait_until_exists()
    instance.wait_until_running()

    # Configure fabric
    env.host_string = instance.public_ip_address
    env.key_filename = KEY_PATH
    env.user = config.server_username

    # Wait for server to finish booting (keep trying until you can successfully run a command on the server via ssh)
    retry(run, "# waiting for ssh to be connectable...", max_retries=100)

    sudo("apt-get -qq -y update")
    sudo("apt-get -qq -y install -q python python-setuptools python-dev")
    sudo("easy_install pip")
    sudo ("apt-get -qq -y install -q python3-pip sqlite sysv-rc-conf")
    sudo ("pip3 install --force-reinstall --upgrade pip")



    put("jupyterhub_files/requirements_jupyterhub.txt", remote_path="/var/tmp/")
    # pip installs
    sudo("pip3 install --quiet -r /var/tmp/requirements_jupyterhub.txt")
    # apt-get installs for jupyterhub


    sudo("pip3 --quiet install ipython jupyter ipykernel nbgrader")
    sudo("pip2 install ipykernel --upgrade")

    # register Python 3 and 2 kernel
    sudo("python3 -m ipykernel install")
    sudo("python2 -m ipykernel install")
    sudo("chmod 755 /mnt")
    sudo("chown ubuntu /mnt")

    # Create AMI for workers
    logger.info("Creating worker AMI")
    ami_name = "jupyter-hub-%s-worker-image" % config.cluster_name
    worker_ami = instance.create_image(Name=ami_name)

    # Wait until AMI is ready or 300 seconds have elapsed to allow for server restart
    for i in range(100):
        if get_resource(config.region).Image(worker_ami.id).state == "available":
            break
        logger.info("AMI not ready yet (running for ~%s seconds)" % (i * 3))
        sleep(3)

    instance.terminate()
    return worker_ami.id

######################################################################################################################
################################################## AWS HELPERS #######################################################
######################################################################################################################

def create_security_group(name):
    security_group = ec2_connection(config.region).create_security_group(
        VpcId=VPC_ID,
        GroupName=name,
        Description=name
    )
    return get_resource(config.region).SecurityGroup(security_group["GroupId"])


def ec2_connection(region):
    if AWS_ACCESS_KEY_ID:
        return boto3.client(
            "ec2", region_name=region,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_KEY,
        )
    else:
        return boto3.client("ec2", region_name=region)


def get_resource(region):
    if AWS_ACCESS_KEY_ID:
        return boto3.resource(
            "ec2", region_name=region,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_KEY,
        )
    else:
        return boto3.resource("ec2", region_name=region)


def subnet_connection(region, subnet_id):
    return get_resource(region).Subnet(subnet_id)


def create_server_security_groups():
    # Create a security group for the manager with ports 22, 80, and 443 open to the public
    logger.info("Creating security groups")
    manager_security_group_name = "jupyter-hub-%s-manager" % config.cluster_name
    manager_security_group = create_security_group(manager_security_group_name)
    manager_security_group.authorize_ingress(
            FromPort=22, ToPort=22, IpProtocol="TCP", CidrIp="0.0.0.0/0"
    )
    manager_security_group.authorize_ingress(
            FromPort=80, ToPort=80, IpProtocol="TCP", CidrIp="0.0.0.0/0"
    )
    manager_security_group.authorize_ingress(
            FromPort=443, ToPort=443, IpProtocol="TCP", CidrIp="0.0.0.0/0"
    )

    worker_security_group_name = "jupyter-hub-%s-worker" % config.cluster_name
    worker_security_group = create_security_group(worker_security_group_name)
    worker_security_group.authorize_ingress(IpPermissions=[{
        "IpProtocol": "-1", "ToPort": -1, "FromPort": -1,
        "UserIdGroupPairs": [{"GroupId": manager_security_group.id}]
    }])

    # Create a separate manager security group so that groups do not have cyclic
    # reference, in order to make deleting easier
    manager_security_group_name = "jupyter-hub-%s-manager2" % config.cluster_name
    manager_security_group2 = create_security_group(manager_security_group_name)
    manager_security_group2.authorize_ingress(IpPermissions=[
        {#Jupyterhub proxy
            "IpProtocol": "TCP", "ToPort": 8888, "FromPort": 8888,
            "UserIdGroupPairs": [{"GroupId": worker_security_group.id}]
        },
        {#jupyterhub API
            "IpProtocol": "TCP", "ToPort": 8081, "FromPort": 8081,
            "UserIdGroupPairs": [{"GroupId": worker_security_group.id}]
        },
    ])
    return worker_security_group, manager_security_group, manager_security_group2


def launch_server(config, ec2, security_groups_list, size=8):
    # if we need more storage, these are parameters for BlockDeviceMappings. AWS default for EBS-backed instances is 8GB.
    # Specifying a smaller volume size requires a custom AMI of that particular size, or AWS will throw an error.
    boot_drive = {'DeviceName': '/dev/sda1',  # this is to be the boot drive
                  'Ebs': {'VolumeSize': size,  # size in gigabytes
                          'DeleteOnTermination': True,
                          'VolumeType': 'gp2',  # This means General Purpose SSD
                          # 'Iops': 1000 }  # i/o speed for storage, default is 100, more is faster
                          }
                  }
    reservation = retry(
        ec2.run_instances,
        ImageId=config.base_ami,
        MinCount=1,
        MaxCount=1,
        KeyName=KEY_NAME,
        InstanceType=config.manager_instance_type,
        NetworkInterfaces=[{
            "DeviceIndex": 0,
            "AssociatePublicIpAddress": True,
            "SubnetId": config.public_subnet_id,
            "Groups": security_groups_list
        }],
        IamInstanceProfile={"Arn": MANAGER_IAM_ROLE},
        BlockDeviceMappings=[boot_drive]
    )
    instance_id = reservation["Instances"][0]["InstanceId"]
    instance = get_resource(config.region).Instance(instance_id)
    return instance


#####################################################################################################################
################################################# OTHER HELPERS #####################################################
#####################################################################################################################

def validate_config():
    """ Checks key file permissions """
    if config.ignore_permissions == "false":
        permissions = oct(os.stat(KEY_PATH).st_mode % 2 ** 9)
        if permissions[1:] != "600":
            print("Your key file permissions are %s, they need to be (0)600 "
                  "or else the configuration script will not be able to connect "
                  "to the server.\n"
                  '(You can override this check with "--ignore-permissions true")'
                  % permissions)
            exit()
    else:
        print("Ignoring ssh key permissions")
    
    if not isinstance( config.worker_ebs_size, int ):
        if not config.worker_ebs_size.isdigit():
            print ("EBS Volume size should be a positive integer number")
            exit()
        else:
            config.worker_ebs_size = int(config.worker_ebs_size)
            if config.worker_ebs_size <= 0 : 
                print ("EBS Volume size should be a positive integer number")
                exit()



def retry(function, *args, **kwargs):
    """ Retries a function up to max_retries, waiting `timeout` seconds between tries.
        This function is designed to retry both boto3 and fabric calls.  In the
        case of boto3, it is necessary because sometimes aws calls return too
        early and a resource needed by the next call is not yet available. """
    max_retries = kwargs.pop("max_retries", 10)
    timeout = kwargs.pop("timeout", 3)
    for i in range(max_retries):
        print ".",
        sys.stdout.flush()
        try:
            return function(*args, **kwargs)
        except (ClientError, NetworkError, WaiterError) as e:
            logger.debug("retrying %s, (~%s seconds elapsed)" % (function, i * 3))
            sleep(timeout)
    logger.error("hit max retries on %s" % function)
    raise e

#####################################################################################################################
#################################################### MAIN ###########################################################
#####################################################################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launches a JupyterHub cluster")
    parser.add_argument("cluster_name", help="the name of the cluster, used for tagging aws resources")
    parser.add_argument("base_ami", help="the AWS base AMI id used for user servers")
    parser.add_argument("private_subnet_id", help="the AWS id of the private subnet for user servers")
    parser.add_argument("public_subnet_id", help="the AWS id of the public subnet for manager server(s)")
    for item, default in CONFIG_DEFAULTS.items():
        flag = "--%s" % item.lower()
        parser.add_argument(flag, help="defaults to %s" % default, default=default)
    config = parser.parse_args()
    validate_config()
    launch_manager(config)
