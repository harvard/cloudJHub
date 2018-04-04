# AWS Setup

### Requirements

	1. a VPC with two subnets, at least one of them have Internet access.
	2. a role with permission to manage EC2 instances and roles.
	3. a public/private key.

Below is a full example to setup AWS environment. Resources are tagged using the following convention : 
tag Key : Name 
tag Value : jupyter_{RESOURCENAME} 

You don't need to follow our resource tag convention since it used for illustration.

### VPC and Subnets

Create and configure the VPC, Subnets, Internet Gateway and routing tables

From AWS Console -> VPC -> VPC Dashboard -> Start VPC Wizard -> VPC with Public and Private Subnets -> Select 

	IP CIDR block:* 10.10.0.0/16
	VPC name:jupyter_vpc
	Public subnet:* 10.10.0.0/24
	Availability Zone:* us-east-1c
	Public subnet name: jupyter_manager_sub
	Private subnet:* 10.10.128.0/17
	Availability Zone:* us-east-1d
	Private subnet name: jupyter_worker_sub
	Elastic IP Allocation ID:* eipalloc-71722333 (need to generate an EIP beforehand)
	Enable DNS hostnames:* : yes
	Hardware tenancy:* : Default
	Create the required roles

You can also use the cloudFormation template,vpc-with-one-managers-and-one-workers-subnets-template.json, we provided to create the VPC and the required subnets. 
Write down the VPC ID, Managers SUBNET ID and the Workers SUBNET ID.For Example : 
VPC ID : vpc-92929292
Managers SUBNET ID : subnet-54502979
Workers SUBNET ID : subnet-fd9bb4b4
 

### Instance Roles and permissions

Roles are required by the : 
1. The machine that will launch the script to create the jupytehub mangers (If AWS Access/Secret keys is not used). 
This machine need to have permission to manage EC2 instances and roles.
2. The cluster managers to manage users ipython notebook instances. 
One role with EC2 management permission and role assignment permission will be sufficient, will call it "jupyter_role".

From IAM -> Policies -> Create Policy -> Create Your Own Policy -> Policy Name : jupyter_role -> Policy Document: 

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": "ec2:*",
            "Effect": "Allow",
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "cloudwatch:*",
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "iam:AddRoleToInstanceProfile",
                "iam:CreateInstanceProfile",
                "iam:ListInstanceProfiles",
                "iam:ListInstanceProfilesForRole",
                "iam:ListRoles",
                "iam:RemoveRoleFromInstanceProfile",
                "iam:GetInstanceProfile",
                "iam:PassRole"
            ],
            "Resource": "*"
        }
    ]
}
```

From IAM -> Roles -> Create New Role -> Select role type -> AWS Service Role: Amazon EC2 (Select) -> Attach Policy : jupyter_role ->
Role Name: jupyter_role -> Create Role

Write Down the ARN profile **arn:aws:iam::063463463463:instance-profile/jupyter_role** as it will be needed later to launch the cluster.


### SSH Keys

The ssh key will be used by the the machine that will launch the script to access and configure jupytehub manger(s).

It also will be used by the cluster managers to access the users ipython notebook instances. 

To create the key:

AWS Console -> EC2 Dashbord -> Key Pairs -> Create Key Pair -> Key pair name: **jupyter_key** 

Save the private key **jupyter_key.pem** and send it to the machine that will run the launch script to create jupyterhub manager(s).

change the permission of **jupyter_key.pem** to **0600**

```
chmod 0600 /PATH/TO/jupyter_key.pem 
```


### EC2 to launch Jupyterhub manager(s)

Create EC2 instance in the a public subnet with "jupyter_role" role. This instance will be used to create jupyterhub cluster manager.

User Amazon CentOS7 AMI or a recent ubuntu AMI.

Assume the instance IP is : **54.224.174.155**

Assume the user name to login to the instance is : ec2-user(default user on Amazon CentOS AMI)  or ubuntu(default user on ubuntu AMI )

Note that : CentOS AMI is not tested.

  

# Create the Cluster

### Move the SSH private key to the launcher machine
centos: scp jupyter_key.pem ec2-user@54.224.174.155:/home/ec2-user/.ssh

ubuntu: scp jupyter_key.pem ubuntu@54.224.174.155:/home/ubuntu/.ssh

Note: make sure the key have the right permission (0600)

  

### login to the launcher EC2 
CentOS: ``` ssh ec2-user@54.224.174.155 ```

Ubuntu: ``` ssh ubuntu@54.224.174.155 ```

  

### update the machine
CentOS: ``` sudo yum update -y ```

Ubuntu: ``` sudo apt-get update -y ```

  

### Install required packages
CentOS: ``` sudo yum install git python2-pip gcc python-devel openssl-devel -y ```

Ubuntu: ``` sudo apt-get install git python3-pip gcc python3-dev libssl-dev -y ```

  

### Clone CloudJHub repository and setup required packages
```
git clone https://github.com/harvard/cloudJHub.git

cd cloudJHub/

sudo pip3 install -r launch_cluster/requirements.txt
```

  

### Prepare the secure.py file. Require: 
* VPC ID of the VPC created above ,   
* key path and name : for **CentOS** the path we used **/home/ec2-user/.ssh** , for **ubuntu** user is should be **/home/ubuntu/.ssh**
* role profile of "jupyter_role" role 
```
cat > launch_cluster/secure.py << EOF
 AWS_ACCESS_KEY_ID = ""
 AWS_SECRET_KEY = ""
 KEY_NAME = "jupyter_key"
 KEY_PATH = "/home/ec2-user/.ssh/%s.pem" % KEY_NAME
 MANAGER_IAM_ROLE = "arn:aws:iam::063463463463:instance-profile/jupyter_role"
 VPC_ID = "vpc-92929292"
EOF
```

  

### Prepare the users and admins 
```
cat > jupyterhub_files/userlist  << EOF
__tokengeneratoradmin admin
youremail@domain admin
EOF
```

  

### SSL Certificate

If ssl certificates will be used (recomended) then you need to configure Jupyterhub cluster manager to use the certificate. 
The certificate can be added to the manager before the manager get launched by the launcher script, or after the launch.
To add the certificates and configure the manager to use them before the launch:  
copy the ssl certificate and key (say jupyterhub.cer , and jupyterhub.key) to the ssl folder, then
```
cp /PATH/TO/SSL_CERTS jupyterhub_files/ssl/
```
open jupyterhub_files/jupyterhub_config.py, and configure the port, certificates path.
```
c.JupyterHub.port = 443
c.JupyterHub.confirm_no_ssl = False
c.JupyterHub.ssl_cert = '/etc/jupyterhub/ssl/jupyterhub.cer'
c.JupyterHub.ssl_key = '/etc/jupyterhub/ssl/jupyterhub.key'
```

  

### Authentication 
Jupyterhub by default configured to use the development authentication with allow authentication with no password. Change the authentication
from jupyterhub_files/jupyterhub_config.py. You can change it later. For now we will leave it on the default. 


  

### Launch the cluster
```
launch_cluster/launch.py --help
launch_cluster/launch.py seas_jupyterhub_May1717 ami-41e0b93b subnet-fd9bb4b4 subnet-54502979

launch_cluster/launch.py --worker_instance_type t2.small --custom_worker_ami ami-f3fa8de5 --manager_instance_type t2.medium --ignore_permissions true seas_jupyterhub_May1717 ami-41e0b93b subnet-fd9bb4b4 subnet-54502979
# Use your AMIs and subnets
```


  

It might take between 10 to 20 minutes for the code to finish and the cluster to be ready.

Login to the new cluster manager 
In AWS EC2 dashboard, get the public IP of the manager you just created. The manager EC2 instance will have tag key "Name": and tag Value :"JUPYTER_HUB_[AZ]_seas_jupyterhub_May1717_MANAGER".
Browse to https://{MANAGER IP} (or http://{MANAGER IP} if you did not configure the SSL certificate),
login as user admin (youremail@domain) with empty password (unless you change the authentication before you launch the script).


