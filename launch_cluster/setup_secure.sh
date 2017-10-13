#!/bin/bash

MAC=$(curl --silent http://169.254.169.254/latest/meta-data/mac)

VPCID=$(curl --silent http://169.254.169.254/latest/meta-data/network/interfaces/macs/$MAC/vpc-id)
SUBID=$(curl --silent http://169.254.169.254/latest/meta-data/network/interfaces/macs/$MAC/subnet-id)
PROFI=$(curl --silent http://169.254.169.254/latest/meta-data/iam/info  | grep InstanceProfileArn | awk '{split ($3,a,"\""); print (a[2])}')

SSHPATH="/home/`whoami`/.ssh"
KEYNAME="jupyter_key"

cat > launch_cluster/secure.py << EOF
AWS_ACCESS_KEY_ID = ""
AWS_SECRET_KEY = ""
KEY_NAME = "$KEYNAME"
KEY_PATH = "$SSHPATH/%s.pem" % KEY_NAME
MANAGER_IAM_ROLE = "$PROFI"
VPC_ID = "$VPCID"
EOF
