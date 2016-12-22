import json
import logging
import socket
import boto3
from fabric.api import env, sudo as _sudo, run as _run
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

LONG_RETRY_COUNT = 120

HUB_MANAGER_IP_ADDRESS = get_local_ip_address()
NOTEBOOK_SERVER_PORT = 4444

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters

WORKER_TAGS = [ #These tags are set on every server created by the spawner
    {"Key": "Name", "Value": SERVER_PARAMS["WORKER_SERVER_NAME"]},
    {"Key": "Owner", "Value": SERVER_PARAMS["WORKER_SERVER_OWNER"]},
    {"Key": "Creator", "Value": SERVER_PARAMS["WORKER_SERVER_OWNER"]},
    {"Key": "Jupyter Cluster", "Value": SERVER_PARAMS["JUPYTER_CLUSTER"]},
]

thread_pool = ThreadPoolExecutor(100)

#Logging settings
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


#Global Fabric config
class RemoteCmdExecutionError(Exception): pass
env.abort_exception = RemoteCmdExecutionError
env.abort_on_prompts = True
FABRIC_DEFAULTS = {"user":SERVER_PARAMS["SERVER_USERNAME"],
                   "key_filename":"/home/%s/.ssh/%s" % (SERVER_PARAMS["SERVER_USERNAME"], SERVER_PARAMS["KEY_NAME"])}

FABRIC_QUIET = True
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
            #EOFError occurs as part of a complex bug in fabric...
            logger.error("Failure in %s with args %s and kwargs %s" % (function.__name__, args, kwargs))
            # if isinstance(e, RemoteCmdExecutionError):
            #     if "abort-on-prompts was set to True" in str(e):
            #         logger.error(str(e))
            #         yield gen.sleep(0.1)
            #         raise Exception("server is misconfigured, cannot recover, remove that server")
            logger.info("retrying %s, (~%s seconds elapsed)" % (function.__name__, attempt * 3))
            yield gen.sleep(timeout)
    else:
        logger.error("Failure in %s with args %s and kwargs %s" % (function.__name__, args, kwargs))
        yield gen.sleep(0.1) #this line exists to allow the logger time to print
        raise e

#################################################################################################
# WARNINGS:
# When debugging the InstanceSpawner the logger can be terminated (or something) before
# the content is printed.  If your stack traces do not match up with your log statements
# insert a sleep(0.5) into the code you are trying to investigate to allow the log time to flush.

class InstanceSpawner(Spawner):
    """ A Spawner that starts an EC2 instance for each user.
        self.user.server.ip and self.user.server.port are set multiple times to avoid encountered edge cases
        where they are not set in Jupyterhub v0.6.1, potentially due to a race condition.
        An improvement is made in currently unreleased Jupyterhub v0.7.0 where they are explicitly set.
        Warning:
            Because of db.commit() calls between yield calls in jupyterhub.user.spawn(), setting an attribute
            on self.user.server results in ORM calls and incomplete jupyterhub.sqlite Server entries. Be careful
            of setting self.user.server attributes too early in this spawner.start().
        """
    
    @gen.coroutine
    def start(self):
        """ When user logs in, start their instance.
            Must return a tuple of the ip and port for the server and Jupyterhub instance. """
        self.log.debug("function start for user %s" % self.user.name)
        self.user.last_activity = datetime.utcnow()
        try:
            instance = yield self.get_instance() #cannot be a thread pool...
            #comprehensive list of states: pending, running, shutting-down, terminated, stopping, stopped.
            if instance.state["Name"] == "running":
                #start_worker_server will handle starting notebook
                yield self.start_worker_server(instance, new_server=False)
                self.log.debug("start ip and port: %s , %s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
                self.ip = self.user.server.ip = instance.private_ip_address
                self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
                return instance.private_ip_address, NOTEBOOK_SERVER_PORT
            elif instance.state["Name"] in ["stopped", "stopping", "pending", "shutting-down"]:
                #Server needs to be booted, do so.
                self.log.info("Starting user %s instance " % self.user.name)
                yield retry(instance.start, max_retries=LONG_RETRY_COUNT)
                # blocking calls should be wrapped in a Future
                yield retry(instance.wait_until_running) #this call can occasionally fail, so we wrap it in a retry.
                yield self.start_worker_server(instance, new_server=False)
                self.log.debug("%s , %s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
                # a longer sleep duration reduces the chance of a 503 or infinite redirect error (which a user can
                # resolve with a page refresh). 10s seems to be a good inflection point of behavior
                yield gen.sleep(10)
                self.ip = self.user.server.ip = instance.private_ip_address
                self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
                return instance.private_ip_address, NOTEBOOK_SERVER_PORT
            elif instance.state["Name"] == "terminated":
                # We do not care about this state. The solution to this problem is to create a new server,
                # that cannot happen until the extant terminated server is actually deleted. (501 == not implemented)
                raise web.HTTPError(501,"Instance for user %s has been terminated, wait until it disappears." % self.user.name)
            else:
                # if instance is in pending, shutting-down, or rebooting state
                raise web.HTTPError(503, "Unknown server state for %s. Please try again in a few minutes" % self.user.name)
        except Server.DoesNotExist:
            self.log.info("\nserver DNE for user %s\n" % self.user.name)
            instance = yield self.create_new_instance()
            yield self.start_worker_server(instance, new_server=True)
            # self.notebook_should_be_running = False
            self.log.debug("%s , %s" % (instance.private_ip_address, NOTEBOOK_SERVER_PORT))
            # to reduce chance of 503 or infinite redirect
            yield gen.sleep(10)
            self.ip = self.user.server.ip = instance.private_ip_address
            self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
            return instance.private_ip_address, NOTEBOOK_SERVER_PORT

    @gen.coroutine
    def stop(self, now=False):
        """ When user session stops, stop user instance """
        self.log.debug("function stop")
        self.log.info("Stopping user %s instance " % self.user.name)
        try:
            instance = yield self.get_instance()
            retry(instance.stop)
            # self.notebook_should_be_running = False
        except Server.DoesNotExist:
            self.log.error("Couldn't stop server for user '%s' as it does not exist" % self.user.name)
            # self.notebook_should_be_running = False
        self.clear_state()

    @gen.coroutine
    def poll(self):
        """ Polls for whether process is running. If running, return None. If not running,
            return exit code """
        self.log.debug("function poll for user %s" % self.user.name)
        try:
            instance = yield self.get_instance()
            self.log.debug(instance.state)
            if instance.state['Name'] == 'running':
                self.log.debug("poll: server is running for user %s" % self.user.name)
                # We cannot have this be a long timeout because Jupyterhub uses poll to determine whether a user can log in.
                # If this has a long timeout, logging in without notebook running takes a long time.
                # attempts = 30 if self.notebook_should_be_running else 1
                notebook_running = yield self.is_notebook_running(instance.private_ip_address, attempts=1)
                if notebook_running:
                    self.log.debug("poll: notebook is running for user %s" % self.user.name)
                    return None #its up!
                else:
                    self.log.debug("Poll, notebook is not running for user %s" % self.user.name)
                    return "server up, no instance running for user %s" % self.user.name
            else:
                self.log.debug("instance waiting for user %s" % self.user.name)
                return "instance stopping, stopped, or pending for user %s" % self.user.name
        except Server.DoesNotExist:
            self.log.error("Couldn't poll server for user '%s' as it does not exist" % self.user.name)
            # self.notebook_should_be_running = False
            return "Instance not found/tracked"
    
    ################################################################################################################

    @gen.coroutine
    def is_notebook_running(self, ip_address_string, attempts=1):
        """ Checks if jupyterhub/notebook is running on the target machine, returns True if Yes, False if not.
            If an attempts count N is provided the check will be run N times or until the notebook is running, whichever
            comes first. """
        with settings(**FABRIC_DEFAULTS, host_string=ip_address_string):
            for i in range(attempts):
                self.log.debug("function check_notebook_running for user %s, attempt %s..." % (self.user.name, i+1))
                output = yield run("ps -ef | grep jupyterhub-singleuser")
                #Notes on the logic here, if we do...
                # ps -ef | grep [j]upyterhub-singleuser, grep can fail with a non-zero exit code if it finds no match.
                #   We could configure the fabric settings for this one to just warn, but that would interfere due to
                #   the global nature of fabric settings if the section that calls is_notebook running is right next
                #   to other fabric commmands.
                # ps -ef | grep -c jupyterhub-singleuser, we encounter the common case where is_notebook_running
                #   has been called frequently, the grep hangs around for a few moments, so we get false positives.
                #So,
                # ps -ef | grep jupyterhub-singleuser   <--  ensures we match against at least ourselves and then
                #   we look for another identifying value in the command line statement to start jupyternotebook.
                for line in output.splitlines(): #
                    if "jupyter-hub-token" in line and "jupyterhub-singleuser" in line:
                        self.log.debug("the following notebook is definitely running:")
                        self.log.debug(line)
                        return True
                self.log.debug("Notebook for user %s not running..." % self.user.name)
                yield gen.sleep(1)
            self.log.error("Notebook for user %s is not running." % self.user.name)
            return False
    
    @gen.coroutine
    def wait_until_SSHable(self, ip_address_string):
        """ Run a meaningless bash command (a comment) inside a retry statement. """
        self.log.debug("function wait_until_SSHable for user %s" % self.user.name)
        with settings(**FABRIC_DEFAULTS, host_string=ip_address_string):
            yield run("# waiting for ssh to be connectable for user %s..." % self.user.name, max_retries=LONG_RETRY_COUNT)
    
    @gen.coroutine
    def get_instance(self):
        """ This returns a boto Instance resource; if boto can't find the instance or if no entry for instance in database,
            it raises Server.DoesNotExist error and removes database entry if appropriate """
        self.log.debug("function get_instance for user %s" % self.user.name)
        server = Server.get_server(self.user.name)
        resource = yield retry(boto3.resource, "ec2", region_name=SERVER_PARAMS["REGION"])
        try:
            ret = yield retry(resource.Instance, server.server_id)
            self.log.debug("return for get_instance for user %s: %s" % (self.user.name, ret))
            # boto3.Instance is lazily loaded. Force with .load()
            yield retry(ret.load)
            if ret.meta.data is None:
                Server.remove_server(server.server_id)
                raise Server.DoesNotExist()
            return ret
        except ClientError as e:
            self.log.error("get_instance client error: %s" % e)
            if "InvalidInstanceID.NotFound" not in str(e):
                self.log.error("Couldn't find instance for user '%s'" % self.user.name)
                Server.remove_server(server.server_id)
                raise Server.DoesNotExist()
            raise e
    
    @gen.coroutine
    def start_worker_server(self, instance, new_server=False):
        """ Runs remote commands on worker server to mount user EBS and connect to Jupyterhub. If new_server=True,
            also create filesystem on newly created user EBS"""
        self.log.debug("function start_worker_server for user %s" % self.user.name)
        # redundant variable set for get_args()
        self.ip = self.user.server.ip = instance.private_ip_address
        self.port = self.user.server.port = NOTEBOOK_SERVER_PORT
        # self.user.server.port = NOTEBOOK_SERVER_PORT
        try:
            # Wait for server to finish booting...
            yield self.wait_until_SSHable(instance.private_ip_address)
            # with settings(**FABRIC_DEFAULTS, host_string=instance.private_ip_address):
            #     #TODO: extremely low priority - unhandled case - when the mnt volume is unformatted
            #     if new_server: # format filesystem on new EBS volume
            #         self.log.info("first run, creating ebs for user %s" % self.user.name)
            #         yield sudo("mkfs -t ext4 /dev/xvdf")
            #     self.log.debug("checking mounts for user %s" % self.user.name)
            #     # We need to check if the user EBS is already mounted
            #     # Note: do not make this "mount | grep /dev/xvdf", that causes
            #     # non-zero exit code problems when /dev/xvdf is not mounted.
            #     output = yield sudo("mount")
            #     if "/dev/xvdf on /mnt" not in output:
            #         yield sudo("mount -t ext4 /dev/xvdf /mnt")
            #start notebook
            self.log.error("\n\n\n\nabout to check if notebook is running before launching\n\n\n\n")
            notebook_running = yield self.is_notebook_running(instance.private_ip_address)
            if not notebook_running:
                yield self.remote_notebook_start(instance.private_ip_address)
        except RemoteCmdExecutionError:
            # terminate instance and create a new one
            raise web.HTTPError(500, "Instance unreachable")
    
    @gen.coroutine
    def remote_notebook_start(self, worker_ip_address_string):
        """ Do notebook start command on the remote server."""
        self.log.debug("function remote_server_start %s" % self.user.name)
        start_notebook_cmd = self.cmd + self.get_args()
        # get_args() is unreliable
        # incorrect hub-api-url parameter generated by get_args
        start_notebook_cmd = [arg for arg in start_notebook_cmd
                              if "--port=" not in arg
                              and "--ip=" not in arg
                              and "--hub-api-url=" not in arg ]

        # start_notebook_cmd.remove("--hub-api-url=http://127.0.0.1:8081/hub/api")
        start_notebook_cmd.append("--hub-api-url=http://%s:8081/hub/api" % HUB_MANAGER_IP_ADDRESS)
        start_notebook_cmd.append("--ip=%s" % worker_ip_address_string)
        start_notebook_cmd.append("--port=%s" % NOTEBOOK_SERVER_PORT)
        start_notebook_cmd = " ".join(start_notebook_cmd)
        # start notebook. provide runtime args
        self.log.info("Starting user %s jupyterhub" % self.user.name)
        with settings(**FABRIC_DEFAULTS, host_string=worker_ip_address_string):
            yield sudo("JPY_API_TOKEN=%s %s > jupyter.log 2>&1 &" % (self.user.new_api_token(), start_notebook_cmd), pty=False)
        self.log.debug("just started the notebook for user %s, waiting." % self.user.name)
        # self.notebook_should_be_running = True
        yield self.is_notebook_running(worker_ip_address_string, attempts=30)
        
    @gen.coroutine
    def create_new_instance(self):
        """ Creates and boots a new server to host the worker instance."""
        self.log.debug("function create_new_instance %s" % self.user.name)
        ec2 = boto3.client("ec2", region_name=SERVER_PARAMS["REGION"])
        resource = boto3.resource("ec2", region_name=SERVER_PARAMS["REGION"])
        boot_drive = {'DeviceName': '/dev/sda1',  # this is to be the boot drive
                      'Ebs': {'VolumeSize': 3,  # size in gigabytes
                              'DeleteOnTermination': True,
                              'VolumeType': 'gp2',  # This means General Purpose SSD
                              # 'Iops': 1000 }  # i/o speed for storage, default is 100, more is faster
                              }
                      }
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
                BlockDeviceMappings=[boot_drive],
        )
        instance_id = reservation["Instances"][0]["InstanceId"]
        instance = yield retry(resource.Instance, instance_id)
        # # create new ebs volume
        # reservation2 = yield retry(
        #         ec2.create_volume,
        #         Size=1,  # 3 GB storage for users, half of which is taken up by system files
        #         AvailabilityZone=SERVER_PARAMS["AVAILABILITY_ZONE"],
        #         VolumeType='gp2',
        # )
        # ebs_volume_id = reservation2["VolumeId"]
        # ebs_volume = resource.Volume(ebs_volume_id)
        # track new server
        # Server.new_server(instance_id, self.user.name, ebs_volume_id)
        Server.new_server(instance_id, self.user.name)
        yield retry(instance.wait_until_exists)
        # add server tags; tags cannot be added until server exists
        yield retry(instance.create_tags, Tags=WORKER_TAGS)
        yield retry(instance.create_tags, Tags=[{"Key": "User", "Value": self.user.name}])
        # start server
        # blocking calls should be wrapped in a Future
        yield retry(instance.wait_until_running)
        # attach ebs volume
        # yield retry(
        #         instance.attach_volume,
        #         VolumeId=ebs_volume_id,
        #         Device='/dev/sdf'
        # )
        # add tag to EBS volume
        # yield retry(ebs_volume.create_tags, Tags=[{"Key": "User", "Value": self.user.name}])
        return instance
