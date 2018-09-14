#!/bin/bash
# This script is for setting up a jupyter notebook user on a worker.
#
# Usage:
#
#   JUPYTERUSER=jharvard JUPYTERDEVICE=xvdf ./setup_jupyteruser.sh
#

# Redirect stdout and stderr to the syslog
exec 1> >(logger -s -t $(basename $0)) 2>&1

# Ensure this script is run as root
if [[ $EUID -ne 0 ]]; then
	echo "This script must be run as root" 
	exit 1
fi

# Ensure that a username is specified
if [ -z "$JUPYTERUSER" ]; then
	echo "JUPYTERUSER is a required parameter (e.g. 12345678). Aborting!"
	exit 1
else
	echo "JUPYTERUSER is $JUPYTERUSER"
fi

### --------------------------------------------------
### Mount EBS home volume if a device is specified

if [ -n "$JUPYTERDEVICE" ]; then
    echo "JUPYTERDEVICE is $JUPYTERDEVICE"
    if lsblk --noheadings --fs /dev/$JUPYTERDEVICE | grep xfs &>/dev/null; then
        echo "Skip: already created filesystem"
    else
        echo "Creating filesystem..."
        mkfs.xfs /dev/$JUPYTERDEVICE
    fi

    if [ -e "/jupyteruser" ]; then
        echo "Skip: already created jupyteruser directory to mount device"
    else
        echo "Creating jupyteruser directory as mount point for device"
        mkdir -p /jupyteruser
    fi

    if grep -q "/dev/$JUPYTERDEVICE" /etc/fstab; then
        echo "Skip: already added device to /etc/fstab"
    else
        echo "Adding device to /etc/fstab..."
        echo "/dev/$JUPYTERDEVICE /jupyteruser xfs defaults 1 1" >> /etc/fstab
    fi

    if grep -q "/dev/$JUPYTERDEVICE" /proc/mounts; then
        echo "Skip: already mounted"
    else
        echo "Mounting volume..."
        mount -a
    fi
else
	echo "JUPYTERDEVICE not specified for the user home volume. Skipping associated setup."
fi

### --------------------------------------------------
### Setup the user account and home directory

if id -u $JUPYTERUSER &>/dev/null; then
	echo "Skip: user account already exists"
else
	echo "Adding new user account..."
	useradd -d /home/$JUPYTERUSER $JUPYTERUSER -s /bin/bash  &>/dev/null
fi

if [ -d "/jupyteruser/$JUPYTERUSER" ]; then
	echo "Skip: contents of ubuntu home directory already copied"
else
	echo "Copying ubuntu home directory to new user home directory..."
	cp -R /home/ubuntu /jupyteruser/$JUPYTERUSER
fi

if [ -L "/home/$JUPYTERUSER" ]; then
	echo "Skip: home directory already symlinked to mount point"
else
	echo "Symlinking home directory to mount point..."
	ln -s /jupyteruser/$JUPYTERUSER /home/$JUPYTERUSER
fi

if [ -e "/etc/sudoers.d/$JUPYTERUSER" ]; then 
	echo "Skip: sudo privilege already setup"
else
	echo "Granting sudo privileges to user without requiring a password..."
	echo " $JUPYTERUSER ALL=(ALL) NOPASSWD:ALL " > /etc/sudoers.d/$JUPYTERUSER
fi

echo "Setting permissions on user home directory..."
chown -R $JUPYTERUSER.$JUPYTERUSER /home/$JUPYTERUSER /jupyteruser/$JUPYTERUSER
exit 0