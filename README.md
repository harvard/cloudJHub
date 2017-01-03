cloudJHub
=======================
An implementation of JupyterHub within the Amazon cloud (AWS), with automatic scaling up and down.

### Overview ###

This system launches online Jupyter notebook coding environments for users. Users can log in without any setup and
start using Jupyter Notebook. Users each get an EC2 instance that is created when the user first logs in. The instance
is stopped when the user is deemed inactive (to save on hosting costs) and started again when the user logs back in.

Deploying The System
-----------------------------------
### Launch Script ###
```
# install requirements
pip install -r launch_cluster/requirements.txt`
# create secure.py from secure.py.example and fill out with appropriate config
cp launch_cluster/secure.py.example launch_cluster/secure.py
nano launch_cluster/secure.py

# Launch command has to be run from the top-level directory.
# To launch, you must at a minimum specify a cluster name, an AWS ami id, an AWS private subnet id, and an AWS public subnet id.
# A NAT gateway must be configured in the public subnet, so that it can have a public IP. Public subnet needs to have
# its traffic routed towards an Internet Gateway. Private subnet needs to have its traffic routed towards the NAT gateway.
# The public subnet is for the manager (or managers, if there are separate clusters for multiple classes/departments/etc),
# and the private subnet is for worker (user) servers. The private subnet needs to be large because all workers will
# be launched in a single private subnet.
./launch_cluster/launch.py [CLUSTER_NAME] [BASE_AMI] [PRIVATE_SUBNET_ID] [PUBLIC_SUBNET_ID]

```

### What Happens ###
The launch script first creates these AWS resources:

* 3 Security Groups (manager, manager2, and worker)
* 1 EC2 Server with Manager IAM role
* 1 EC2 Server for creating 1 AMI and associated EBS snapshot (unless custom AMI specified) that will be immediately terminated

The Manager EC2 instance is the server responsible for running Jupyterhub.

### Launch Script Assumptions ###
1. The IAM role specified for the manager node has permission to launch and terminate EC2 instances
2. The VPC has a CIDR Block of the form e.g. `x.y.0.0/16` and contains subnets (`1/16` just an example)
with CIDR Blocks of the form e.g. `x.y.0.0/24`, `x.y.1.0/24`, `x.y.2.0/24`, etc. (`/24` is just an example,
you may use subnets of the size of your choice.)
3. The VPC has an attached internet gateway
4. The VPC has the route `0.0.0.0/0` pointed to the attached internet gateway
in its route table2.

Note there is a default limit to the number of EC2 servers one can have in a region (e.g. 20). A request can be made to AWS
to increase this limit for your AWS account [here](http://docs.aws.amazon.com/general/latest/gr/aws_service_limits.html).

### Running Cluster With HTTPS/SSL ###
To run the system with HTTPS, you must install the SSL certificate files in `/etc/jupyterhub/ssl/` on the manager server and
update your `jupyterhub_config.py`.

### Authentication ###
You can plug-in your own custom authenticator. Read more about Jupyterhub [authenticators here](http://jupyterhub.readthedocs.io/en/latest/authenticators.html)
For example, you have the option of authentication via user Github accounts. In order to do so,
you must create a [Github OAuth application](https://github.com/settings/applications/new>).
and update your `jupyterhub_config.py` with the generated OAuth callback URL and Github client ID and secret.
See more [Github OAuth documentation here](https://github.com/jupyterhub/oauthenticator/blob/master/README.md).
Admins can bulk add users (their Github usernames) through the Jupyterhub admin interface. 

### Configuring Your System ###
- jupterhub_config.py
Important Jupyterhub configuation lives here. You can set which authenticator you're using here.
- server_config.json
This file is created by the launch script. After a cluster has been launched, the configuration the system runs on is located here.
You can change the inactivity timeout (i.e. `JUPYTER_NOTEBOOK_TIMEOUT`, in seconds; default is 1 hour) that determines
when an notebook instance is automatically stopped here after a cluster has been launched.
- instance_config.json
This is where you can configure the EC2 instance type of notebook servers and your Jupyterhub manager. You can also
specify a custom AMI for notebook servers here (e.g. one previously created). Note that `WORKER_EBS_SIZE` is in GB
and that the default minimum EBS-backing root volume size for AWS base images (e.g. Ubuntu 16.04) is 8GB;
specifying anything lower will result in an AWS error. If you want an EBS size for worker instances that is less than
8GB, you must create a base AMI of that particular size and then provide that ami id as `base_ami` parameter for the
launch script.

### Deleting A Cluster ###
Deleting a cluster entails deleting the AWS resources created by the launch script. There exists a `terminate_all_workers.py` script to
help clean up user EC2 instances. Once the script is run, the manager, security groups, the AMI image, and the subnets can be
deleted (if appropriate).

Development Notes
-----------------------------------
A previous iteration of this project was based off running notebook servers inside Docker (v1.11) containers instead
of individual EC2 instances. When a user logged in, a Docker container would be created dynamically for a user and placed
on an available server ("worker") that had capacity for it. User files were persistently hosted on NFS (AWS EFS). After the user
became inactive, the container would be removed. Once a server was empty, the server would be spun down. A “worker manager”
service would monitor and manage servers to maintain the configured level of spare capacity and auto-scale up and down.
There were a few disadvantages that we discovered in implementation that motivated us to move away from Docker and NFS and release
this current version that runs notebook servers on small, individual EC2 instances. These disadvantages included:
- Instability/bugs that we encountered using [Docker's Python client](https://github.com/docker/docker-py) and
[dockerspawner.py](https://github.com/jupyterhub/dockerspawner)
- Increased user login time during usage surges
- The possibility of worse server failure cases (e.g. kernel attacks, privilege escalation attacks, etc.) that would
affect all users/containers on that server
- The possibility of the costly usage scenarios where the system can't appropriately scale down from many servers from surge
usage because there exists at least one active container on each server, forcing the system to keep and pay for all servers
but at a low utilization of just one active container per server.
- Unnecessary complexity added to development and maintenance from having a Docker layer
- Incompatibility issues that required custom resolution. For example: 
    - NFS is incompatible with SQLite (due to the way fcntl() file locking is implemented for NFS). Because both Jupyterhub and Jupyter Notebook dynamically create
many SQLite files as part of their general workflow, we had to create custom config files that instructed Jupyter and IPython Notebook processes to run using in-memory data structures
instead of SQLite in order to use NFS. 
    - Docker v1.11 had to be restarted in order to detect any new file system mounts (i.e. NFS). 
    - Active Docker development was also a concern for future compatibility. The latest version of Docker (v1.12) at the time left behind features (e.g. Swarm Mode didn't include a binpacking
strategy for container placement), and Docker's clients (e.g. Python client) lagged behind Docker releases.