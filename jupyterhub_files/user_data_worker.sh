#!/bin/bash -ex
exec 1> >(logger -s -t $(basename $0)) 2>&1 # Redirect stdout/stderr to the syslog

# Disable SSH service so the spawner cannot connect during this process.
# If an error occurs or the script exits successfully, SSH should be restarted automatically.
trap "service ssh restart" EXIT
service ssh stop

# Setup mount point
mkdir -p /jupyteruser

# Mount EBS home volume if a device is specified
if [ -n "{device}" ]; then
    mkfs.xfs /dev/{device}
    echo "/dev/{device} /jupyteruser xfs defaults 1 1" >> /etc/fstab
    mount -a
fi

# Setup the user account and home directory
useradd -d /home/{user} {user} -s /bin/bash  &>/dev/null
cp -R /home/ubuntu /jupyteruser/{user}
ln -s /jupyteruser/{user} /home/{user}
echo " {user} ALL=(ALL) NOPASSWD:ALL " > /etc/sudoers.d/{user}
chown -R {user}.{user} /home/{user} /jupyteruser/{user}
echo "User setup completed for {user}"
