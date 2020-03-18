import json
import logging
import socket
import boto3
from fabric.api import env, sudo as _sudo, run as _run
from fabric.operations import put as _put
from fabric.context_managers import settings
from fabric.exceptions import NetworkError
from paramiko.ssh_exception import SSHException, ChannelException
from botocore.exceptions import ClientError, WaiterError
from datetime import datetime
from tornado import gen, web
from jupyterhub.spawner import Spawner
from concurrent.futures import ThreadPoolExecutor

from models import Server

def get_local_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip_address = s.getsockname()[0]
    s.close()
    return ip_address

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters

LONG_RETRY_COUNT = 120
REMOTE_NOTEBOOK_START_RETRY_MAX = 5
HUB_MANAGER_IP_ADDRESS = get_local_ip_address()
NOTEBOOK_SERVER_PORT = 4444
WORKER_USERNAME  = SERVER_PARAMS["WORKER_USERNAME"]


WORKER_TAGS = [ #These tags are set on every server created by the spawner
    {"Key": "Name", "Value": SERVER_PARAMS["WORKER_SERVER_NAME"]},
    {"Key": "Creator", "Value": SERVER_PARAMS["WORKER_SERVER_OWNER"]},
    {"Key": "Jupyter Cluster", "Value": SERVER_PARAMS["JUPYTER_CLUSTER"]},
    {"Key": "environment", "Value": SERVER_PARAMS["ENVIRONMENT"]},
    {"Key": "platform", "Value": SERVER_PARAMS["PLATFORM"]},
    {"Key": "product", "Value": SERVER_PARAMS["JUPYTER_CLUSTER"]}
]

#User data script to be executed on every worker created by the spawner
WORKER_USER_DATA = None
with open("/etc/jupyterhub/user_data_worker.sh", "r") as f:
    WORKER_USER_DATA = f.read()

thread_pool = ThreadPoolExecutor(100)

#Logging settings
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


#Global Fabric config
class RemoteCmdExecutionError(Exception): pass
env.abort_exception = RemoteCmdExecutionError
env.abort_on_prompts = True
FABRIC_DEFAULTS = {"user":SERVER_PARAMS["WORKER_USERNAME"],
                   "key_filename":"/home/%s/.ssh/%s" % (SERVER_PARAMS["SERVER_USERNAME"], SERVER_PARAMS["KEY_NAME"])}

FABRIC_QUIET = True
#FABRIC_QUIET = False
# Make Fabric only print output of commands when logging level is greater than warning.

@gen.coroutine
def sudo(*args, **kwargs):
    ret = yield retry(_sudo, *args, **kwargs, quiet=FABRIC_QUIET)
    return ret

@gen.coroutine
def run(*args, **kwargs):
    ret = yield retry(_run, *args, **kwargs, quiet=FABRIC_QUIET)
    return ret

@gen.coroutine
def put(*args, **kwargs):
    ret = yield retry(_put, *args, **kwargs)
    return ret

@gen.coroutine
def retry(function, *args, **kwargs):
    """ Retries a function up to max_retries, waiting `timeout` seconds between tries.
        This function is designed to retry both boto3 and fabric calls.  In the
        case of boto3, it is necessary because sometimes aws calls return too
        early and a resource needed by the next call is not yet available. """
    max_retries = kwargs.pop("max_retries", 10)
    timeout = kwargs.pop("timeout", 1)
    for attempt in range(max_retries):
        try:
            ret = yield thread_pool.submit(function, *args, **kwargs)
            return ret
        except (ClientError, WaiterError, NetworkError, RemoteCmdExecutionError, EOFError, SSHException, ChannelException) as e:
            #EOFError can occur in fabric
            logger.error("Failure in %s with args %s and kwargs %s" % (function.__name__, args, kwargs))
            logger.info("retrying %s, (~%s seconds elapsed)" % (function.__name__, attempt * 3))
            yield gen.sleep(timeout)
    else:
        logger.error("Failure in %s with args %s and kwargs %s" % (function.__name__, args, kwargs))
        yield gen.sleep(0.1) #this line exists to allow the logger time to print
        return ("RETRY_FAILED")

#########################################################################################################
#########################################################################################################

class InstanceSpawner(Spawner):
    """ A Spawner that starts an EC2 instance for each user.

        Warnings:
            - Because of db.commit() calls within Jupyterhub's code between yield calls in jupyterhub.user.spawn(),
            setting an attribute on self.user.server results in ORM calls and incomplete jupyterhub.sqlite Server
            entries. Be careful of setting self.user.server attributes too early in this spawner.start().

            In this spawner's start(), self.user.server.ip and self.user.server.port are set immediately before the
            return statement to alleviate the edge case where they are not always set in Jupyterhub v0.6.1. An
            improvement is made in developmental version Jupyterhub v0.7.0 where they are explicitly set.

            - It's possible for the logger to be terminated before log is printed. If your stack traces do not match up
            with your log statements, insert a brief sleep into the code where your are logging to allow time for log to
            flush.
        """

    def log_user(self, message='', level=logging.INFO):
        user = self.user.name if self.user else None
        log_message = "[user:%s] %s" % (user, message)
        self.log.log(level, log_message)

    @gen.coroutine
    def start(self):
        """ When user logs in, start their instance.
            Must return a tuple of the ip and port for the server and Jupyterhub instance. """
        self.log_user("start()")
        last_activity = self.user.last_activity
        self.user.last_activity = datetime.utcnow()
        self.log_user("start: user last activity updated from %s to %s" % (last_activity, self.user.last_activity))
        try:
            instance = yield self.get_instance() #cannot be a thread pool...
            self.log_user("start: instance_id: %s state: %s" % (instance.instance_id, instance.state["Name"]))
            #comprehensive list of states: pending, running, shutting-down, terminated, stopping, stopped.
            if instance.state["Name"] == "running":
                ec2_run_status = yield self.check_for_hanged_ec2(instance)
                if ec2_run_status == "SSH_CONNECTION_FAILED":
                    self.log_user("start: cannot start because hanged")
                    #yield self.poll()
                    #yield self.kill_instance(instance)
                    #yield retry(instance.start, max_retries=(LONG_RETRY_COUNT*2))
                    #yield retry(instance.wait_until_running, max_retries=(LONG_RETRY_COUNT*2)) #this call can occasionally fail, so we wrap it in a retry.
                    #return instance.private_ip_address, NOTEBOOK_SERVER_PORT
                    return None
                #start_worker_server will handle starting notebook
                yield self.start_worker_server(instance, new_server=False)
                self.log_user("start: started %s:%s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
                self.ip = self.user.server.ip = instance.private_ip_address
                self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
                return instance.private_ip_address, NOTEBOOK_SERVER_PORT
            elif instance.state["Name"] in ["stopped", "stopping", "pending", "shutting-down"]:
                #Server needs to be booted, do so.
                self.log_user("starting EC2 instance")
                yield retry(instance.start, max_retries=LONG_RETRY_COUNT)
                #yield retry(instance.start)
                # blocking calls should be wrapped in a Future
                yield retry(instance.wait_until_running) #this call can occasionally fail, so we wrap it in a retry.
                yield self.start_worker_server(instance, new_server=False)
                self.log_user("start: started %s:%s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
                # a longer sleep duration reduces the chance of a 503 or infinite redirect error (which a user can
                # resolve with a page refresh). 10s seems to be a good inflection point of behavior
                yield gen.sleep(10)
                self.ip = self.user.server.ip = instance.private_ip_address
                self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
                return instance.private_ip_address, NOTEBOOK_SERVER_PORT
            elif instance.state["Name"] == "terminated":
                # We do not care about this state. The solution to this problem is to create a new server,
                # that cannot happen until the extant terminated server is actually deleted. (501 == not implemented)
                self.log_user("start: instance is terminated, wait until it disappears")
                raise web.HTTPError(501,"Instance for user %s has been terminated, wait until it disappears." % self.user.name)
            else:
                # if instance is in pending, shutting-down, or rebooting state
                raise web.HTTPError(503, "Unknown server state for %s. Please try again in a few minutes" % self.user.name)
        except Server.DoesNotExist:
            self.log_user("server DNE, attempting to create new instance and start worker")
            instance = yield self.create_new_instance()
            yield self.start_worker_server(instance, new_server=True)
            # self.notebook_should_be_running = False
            self.log_user("server DNE, started with %s:%s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
            # to reduce chance of 503 or infinite redirect
            yield gen.sleep(10)
            self.ip = self.user.server.ip = instance.private_ip_address
            self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
            return instance.private_ip_address, NOTEBOOK_SERVER_PORT

    def clear_state(self):
        """Clear stored state about this spawner """
        super(InstanceSpawner, self).clear_state()

    @gen.coroutine
    def stop(self, now=False):
        """ When user session stops, stop user instance """
        self.log_user("stop()")
        try:
            instance = yield self.get_instance()
            retry(instance.stop)
            self.log_user("stop: stopped")
            # self.notebook_should_be_running = False
        except Server.DoesNotExist:
            self.log_user("stop: DNE - could not stop because server does not exist", level=logging.ERROR)
            # self.notebook_should_be_running = False
        self.clear_state()

    @gen.coroutine
    def kill_instance(self,instance):
        self.log_user("kill_instance(): %s" % instance.id)
        yield self.stop(now=True)


    # Check if the machine is hanged
    @gen.coroutine
    def check_for_hanged_ec2(self, instance):
        timerightnow    = datetime.utcnow().replace(tzinfo=None)
        ec2launchtime   = instance.launch_time.replace(tzinfo=None)
        ec2uptimeSecond = (timerightnow - ec2launchtime).seconds
        #conn_health = None
        conn_health = ""
        if ec2uptimeSecond > 180:
            # wait_until_SSHable return : 1) "some object" if SSH is established;  2) "SSH_CONNECTION_FAILED" otherwise
            conn_health  = yield self.wait_until_SSHable(instance.private_ip_address,max_retries=5)
        return(conn_health)


    @gen.coroutine
    def poll(self):
        """ Polls for whether process is running. If running, return None. If not running,
            return exit code """
        self.log_user("poll()")
        try:
            instance = yield self.get_instance()
            self.log_user("poll: instance state is %s" % instance.state)
            if instance.state['Name'] == 'running':
                self.log_user("poll: instance is running, checking...")
                # We cannot have this be a long timeout because Jupyterhub uses poll to determine whether a user can log in.
                # If this has a long timeout, logging in without notebook running takes a long time.
                # attempts = 30 if self.notebook_should_be_running else 1
                # check if the machine is hanged
                ec2_run_status = yield self.check_for_hanged_ec2(instance)
                if ec2_run_status == "SSH_CONNECTION_FAILED":
                    self.log_user("poll: instance is hanging: %s" % ec2_run_status)
                    yield self.kill_instance(instance)
                    return "Instance Hang"
                else:
                    notebook_running = yield self.is_notebook_running(instance.private_ip_address, attempts=1)
                    if notebook_running:
                        self.log_user("poll: notebook is running")
                        return None #its up!
                    else:
                        self.log_user("poll: notebook is NOT running") 
                        return "server up, no instance running for user %s" % self.user.name
            else:
                self.log_user("poll: instance is NOT running")
                return "instance stopping, stopped, or pending for user %s" % self.user.name
        except Server.DoesNotExist:
            self.log_user("poll: DNE - could not poll because server does not exist") 
            # self.notebook_should_be_running = False
            return "Instance not found/tracked"

    ################################################################################################################
    ### helpers ###

    @gen.coroutine
    def is_notebook_running(self, ip_address_string, attempts=1):
        """ Checks if jupyterhub/notebook is running on the target machine, returns True if Yes, False if not.
            If an attempts count N is provided the check will be run N times or until the notebook is running, whichever
            comes first. """
        with settings(**FABRIC_DEFAULTS, host_string=ip_address_string):
            for i in range(attempts):
                log_msg = "is_notebook_running(%s) attempt: %s/%s" % (ip_address_string, i+1, attempts)
                self.log_user(log_msg, level=logging.DEBUG)
                output = yield run("nice -5 pgrep -a -f jupyterhub-singleuser") # replaces: ps -ef | grep jupyterhub-singleuser
                self.log_user("%s output: %s" % (log_msg, output), level=logging.DEBUG)
                for line in output.splitlines(): #
                    #if "jupyterhub-singleuser" and NOTEBOOK_SERVER_PORT in line:
                    if "jupyterhub-singleuser" and str(NOTEBOOK_SERVER_PORT)  and str(self.user.name) and ip_address_string in line:
                        self.log_user("%s check completed, is running" % log_msg, level=logging.DEBUG)
                        return True
                self.log_user("%s check in progress, not running" % log_msg, level=logging.DEBUG)
                yield gen.sleep(3)
            self.log_user("%s check completed, not running" % log_msg, level=logging.DEBUG)
            return False

    ###  Retun SSH_CONNECTION_FAILED if ssh connection failed
    @gen.coroutine
    def wait_until_SSHable(self, ip_address_string, max_retries=1):
        """ Run a meaningless bash command (a comment) inside a retry statement. """
        self.log_user("wait_until_SSHable()")
        with settings(**FABRIC_DEFAULTS, host_string=ip_address_string):
            self.log_user("wait_until_SSHable max_retries:%s" % max_retries, level=logging.DEBUG)
            ret = yield run("# waiting for ssh to be connectable for user %s..." % self.user.name, max_retries=max_retries)
        self.log_user("wait_until_SSHable completed return: %s" % ret, level=logging.DEBUG)
        if ret == "RETRY_FAILED":
           ret = "SSH_CONNECTION_FAILED"
        return (ret)


    @gen.coroutine
    def get_instance(self):
        #""" This returns a boto Instance resource; if boto can't find the instance or if no entry for instance in database,
        #    it raises Server.DoesNotExist error and removes database entry if appropriate """
        """ This returns a boto Instance resource; if no entry for the instance in database,then 
            it raises Server.DoesNotExist error. If the instance in the database but 
            boto can't find the instance, it raise 500 http error """

        self.log_user("get_instance()")
        server = Server.get_server(self.user.name)
        resource = yield retry(boto3.resource, "ec2", region_name=SERVER_PARAMS["REGION"])
        try:
            ret = yield retry(resource.Instance, server.server_id)
            self.log_user("get_instance: returned: %s" % ret)
            # boto3.Instance is lazily loaded. Force with .load()
            yield retry(ret.load)
            if ret.meta.data is None:
                self.log_user("get_instance: could not access instance", level=logging.ERROR)
                raise web.HTTPError(500, "Couldn't access instance for user '%s'. Please try again in a few minutes" % self.user.name)
                #Server.remove_server(server.server_id)
                #raise Server.DoesNotExist()
            return ret
        except ClientError as e:
            self.log_user("get_instance client error: %s" % e)
            if "InvalidInstanceID.NotFound" not in str(e):
                self.log_user("get_instance: could not find instance for user", level=logging.ERROR)
                raise web.HTTPError(500, "Couldn't access instance for user '%s'. Please try again in a few minutes" % self.user.name)
                #Server.remove_server(server.server_id)
                #raise Server.DoesNotExist()
            raise e

    @gen.coroutine
    def start_worker_server(self, instance, new_server=False):
        """ Runs remote commands on worker server to mount user EBS and connect to Jupyterhub. If new_server=True,
            also create filesystem on newly created user EBS"""
        self.log_user("start_worker_server()")
        # redundant variable set for get_args()
        self.ip = self.user.server.ip = instance.private_ip_address
        self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
        # self.user.server.port = NOTEBOOK_SERVER_PORT
        try:
            # Wait for server to finish booting...
            wait_result = yield self.wait_until_SSHable(instance.private_ip_address,max_retries=LONG_RETRY_COUNT)
            self.log_user("start_worker_server wait_result: %s" % wait_result)
            if wait_result == "SSH_CONNECTION_FAILED":
                raise Exception("Server start failed. Please retry by clicking on 'Home' then 'Start My Server'.")
            #start notebook
            self.log_user("start_worker_server starting remote notebook: %s" % instance.private_ip_address)
            yield self.remote_notebook_start(instance)
        except RemoteCmdExecutionError as e:
            # terminate instance and create a new one
            self.log.exception(e)
            raise web.HTTPError(500, "Instance unreachable")

    def user_env(self, env):
        """Augment environment of spawned process with user specific env variables."""
        import pwd
        # set HOME and SHELL for the Jupyter process
        env['HOME'] = '/home/' + self.user.name
        env['SHELL'] = '/bin/bash'
        return env


    def get_env(self):
        """Get the complete set of environment variables to be set in the spawned process."""
        env = super().get_env()
        env = self.user_env(env)
        return env


    @gen.coroutine
    def remote_notebook_start(self, instance):
        """ Do notebook start command on the remote server."""
        self.log_user("remote_notebook_start()")

        # Setup environments
        env = self.get_env()
        lenv=''
        for key in env:
            lenv = lenv + key + "=" + env[key] + " "
        # End setup environment
        worker_ip_address_string = instance.private_ip_address
        start_notebook_cmd = self.cmd + self.get_args()
        start_notebook_cmd = " ".join(start_notebook_cmd)
        self.log_user("remote_notebook_start private ip: %s" % worker_ip_address_string)
        with settings(user = self.user.name, key_filename = FABRIC_DEFAULTS["key_filename"],  host_string=worker_ip_address_string):
            yield sudo("%s %s --user=%s --notebook-dir=/home/%s/ --allow-root > /tmp/jupyter.log 2>&1 &" % (lenv, start_notebook_cmd,self.user.name,self.user.name),  pty=False)
            self.log_user("remote_notebook_start private ip: %s, waiting." % worker_ip_address_string)
            notebook_running = yield self.is_notebook_running(worker_ip_address_string, attempts=10)
            self.log_user("remote_notebook_start private ip: %s, running: %s" % (worker_ip_address_string, notebook_running))
            num_remote_notebook_start_retries = 0
            while not notebook_running and num_remote_notebook_start_retries < REMOTE_NOTEBOOK_START_RETRY_MAX:
                yield sudo("%s %s --user=%s --notebook-dir=/home/%s/ --allow-root > /tmp/jupyter.log 2>&1 &" % (lenv, start_notebook_cmd,self.user.name,self.user.name),  pty=False)
                self.log_user("remote_notebook_start private ip: %s, retry attempt %s/%s. waiting..." % (worker_ip_address_string, num_remote_notebook_start_retries + 1, REMOTE_NOTEBOOK_START_RETRY_MAX))
                yield gen.sleep(3) # Wait for 3 seconds before checking whether the notebook server started
                notebook_running = yield self.is_notebook_running(worker_ip_address_string, attempts=10)
                self.log_user("remote_notebook_start private ip: %s, running: %s" % (worker_ip_address_string, notebook_running))
                if notebook_running:
                    break # break loop
                num_remote_notebook_start_retries += 1
        # self.notebook_should_be_running = True

    @gen.coroutine
    def create_new_instance(self):
        """ Creates and boots a new server to host the worker instance."""
        self.log_user("create_new_instance()")
        ec2 = boto3.client("ec2", region_name=SERVER_PARAMS["REGION"])
        resource = boto3.resource("ec2", region_name=SERVER_PARAMS["REGION"])
        BDM = []
        boot_drive = {'DeviceName': '/dev/sda1',  # this is to be the boot drive
                      'Ebs': {'VolumeSize': SERVER_PARAMS["WORKER_EBS_SIZE"],  # size in gigabytes
                              'DeleteOnTermination': True,
                              'VolumeType': 'gp2',  # This means General Purpose SSD
                              # 'Iops': 1000 }  # i/o speed for storage, default is 100, more is faster
                              }
                     }
        BDM = [boot_drive]
        if SERVER_PARAMS["USER_HOME_EBS_SIZE"] > 0:
            user_drive = {'DeviceName': '/dev/sdf',  # this is to be the user data drive
                          'Ebs': {'VolumeSize': SERVER_PARAMS["USER_HOME_EBS_SIZE"],  # size in gigabytes
                                  'DeleteOnTermination': False,
                                  'VolumeType': 'gp2',  # General Purpose SSD
                                  }
                         }
            BDM = [boot_drive, user_drive]

        # prepare userdata script to execute on the worker instance
        user_home_device = "xvdf" if SERVER_PARAMS["USER_HOME_EBS_SIZE"] > 0 else ""
        user_data_script = WORKER_USER_DATA.format(user=self.user.name, device=user_home_device)

        # create new instance
        reservation = yield retry(
                ec2.run_instances,
                ImageId=SERVER_PARAMS["WORKER_AMI"],
                MinCount=1,
                MaxCount=1,
                KeyName=SERVER_PARAMS["KEY_NAME"],
                InstanceType=SERVER_PARAMS["INSTANCE_TYPE"],
                SubnetId=SERVER_PARAMS["SUBNET_ID"],
                SecurityGroupIds=SERVER_PARAMS["WORKER_SECURITY_GROUPS"],
                BlockDeviceMappings=BDM,
                UserData=user_data_script,
        )
        instance_id = reservation["Instances"][0]["InstanceId"]
        instance = yield retry(resource.Instance, instance_id)
        Server.new_server(instance_id, self.user.name)
        yield retry(instance.wait_until_exists)
        # add server tags; tags cannot be added until server exists
        yield retry(instance.create_tags, Tags=WORKER_TAGS)
        yield retry(instance.create_tags, Tags=[{"Key": "owner", "Value": self.user.name}])
        # start server
        # blocking calls should be wrapped in a Future
        yield retry(instance.wait_until_running)
        return instance
