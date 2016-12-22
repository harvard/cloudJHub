Harvard JupyterHub
=======================
Auto-scaling Jupyterhub cluster system for educational use.

Deploy The System
-----------------------------------
### Launch Script ###
```
#install requirements
pip install -r launch_cluster/requirements.txt`
#create secure.py from secure.py.example and fill out the config
cp launch_cluster/secure.py.example launch_cluster/secure.py
nano launch_cluster/secure.py
#launch command has to be run from the top-level directory. See available options with --help.
./launch_cluster/launch.py --help

# To launch, you must at a minimum specify a cluster name, an AWS ami id, an AWS private subnet id, and an AWS public subnet id.
# A NAT gateway must be configured in the public subnet, so that it can have a public IP. Public needs to have
# its traffic routed towards an Internet Gateway. Private needs to have its traffic routed towards the NAT gateway.
# The public subnet is for the manager (or managers, if there are separate clusters for multiple classes/departments),
# and the private subnet is for worker (user) servers. The private subnet needs to be large because all workers will
# be launched in a single private subnet.
./launch_cluster/launch.py [CLUSTER_NAME] [BASE_AMI] [PRIVATE_SUBNET_ID] [PUBLIC_SUBNET_ID]

```

### What Happens ###
The launch script first creates these AWS resources:

* 3 Security Groups (manager, manager2, and worker)
* 1 EC2 Server with Manager IAM role
* 1 EC2 Server for creating 1 AMI and associated EBS snapshot (unless custom AMI specified) that will be immediately terminated

The Manager EC2 Server created in `setup_manager()` is the server responsible for running Jupyterhub. An AMI snapshot
is made `make_worker_ami()`

### Launch Script Assumptions ###
1. The VPC has a CIDR Block of the form `x.y.0.0/16` and contains subnets (/16 just an example)
with CIDR Blocks of the form `x.y.0.0/24`, `x.y.1.0/24`, `x.y.2.0/24`, etc. (/24 is just an example, you may use subnets of the size of your choice.)
2. The VPC has an attached internet gateway
3. The VPC has the route `0.0.0.0/0` pointed to the attached internet gateway
in its route table
4. The IAM role specified for the manager node has permission to launch and terminate EC2 instances

### Other Important Notes ###
* To run this, you need full permissions to the EC2, EFS, and VPC services, as well as the `iam:PassRole` permission
* There is a default limit to the number of EC2 servers one can have in a region (e.g. 20). A request can be made to AWS
  to increase this limit: http://docs.aws.amazon.com/general/latest/gr/aws_service_limits.html
  An API endpoint to view the limit: http://docs.aws.amazon.com/gamelift/latest/apireference/API_DescribeEC2InstanceLimits.html
* There is also a default limit to the number of EFS allowed (e.g. 10).

### Deleting A Cluster ###
To assist with deleting a Jupyterhub cluster, the `terminate_all_workers.py` script helps clean up created AWS resources
The script is located on the manager, and is meant to be run from the manager as the manager tracks servers. Once the
script is run, the manager should be deleted. Once the manager is deleted, security groups can be deleted (but should
be deleted in the order of creation). Finally, and only if applicable, you may delete the relevant AMI image and the subnets.

In summary, the AWS resources this script deletes:
- User EC2 instances
- User EBS volumes
AWS resources that need to be deleted manually:
- Jupyterhub manager
- Security groups
- AMI (if applicable)
- Subnets (if applicable)

### Running Cluster With HTTPS/SSL ###
You must SSH into the manager server to install the SSL certificate/key files in `/etc/jupyterhub/ssl/`. Remember to update
your `jupyterhub_config` to point to these new files.

### Cluster Authentication ###
Currently using Github via OAuth. You must create a [Github OAuth application here](https://github.com/settings/applications/new>).
and update your `jupyterhub_config` with the Oauth callback url and github client ID and secret.
See more [documentation here](https://github.com/jupyterhub/oauthenticator/blob/master/README.md)
Course instructors should have a Github account so that a current admin can add them as admins.
Admins can bulk add users through the interface.


Configuring Your System
------------------------------------
#### jupterhub_config ####
Important Jupyterhub and system configuation lives here. <documentation pending>

#### server_config.json ####
After a cluster has been launched, the configuration the system runs on is located here. <documentation pending>

