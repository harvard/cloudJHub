#!/bin/bash

MAC=$(curl --silent http://169.254.169.254/latest/meta-data/mac)

VPCID=$(curl --silent http://169.254.169.254/latest/meta-data/network/interfaces/macs/$MAC/vpc-id)
PUBSUBID=$(curl --silent http://169.254.169.254/latest/meta-data/network/interfaces/macs/$MAC/subnet-id)
PROFILEID=$(curl --silent http://169.254.169.254/latest/meta-data/iam/info  | grep InstanceProfileArn | awk '{split ($3,a,"\""); print (a[2])}')

SSHPATH="/home/`whoami`/.ssh"
KEYNAME="jupyter_key"

export PUBSUBID
export VPCID

for i in $(aws ec2 describe-subnets --filters "Name=vpc-id,Values=vpc-217db059" | grep SUBNET | awk '{print $9}'); do
	if [ "$i" != "$PUBSUBID" ]; then 
		PRVSUBID=$i
	fi
done

export PUBSUBID
export PRVSUBID


cat > launch_cluster/secure.py << EOF
AWS_ACCESS_KEY_ID = ""
AWS_SECRET_KEY = ""
KEY_NAME = "$KEYNAME"
KEY_PATH = "$SSHPATH/%s.pem" % KEY_NAME
MANAGER_IAM_ROLE = "$PROFILEID"
VPC_ID = "$VPCID"
EOF

echo "Public (Manager Subnets) is $PUBSUBID , exported as PUBSUBID"
echo "Private (Worker Subnets) is $PRVSUBID , exported as PRVSUBID"
echo ""
echo ""
echo " Help launching a cluster with the subnets variable : " 
echo ""
echo " launch_cluster/launch.py {CLUSTER-NAME} {AMI-ID}  $PRVSUBID $PUBSUBID"
echo ""

