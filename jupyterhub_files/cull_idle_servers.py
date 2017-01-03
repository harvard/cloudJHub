#!/usr/bin/python3 python3

# This is a heavily modified version of the jupyterhub cull-idle script, retrieved October 31st 2016 from
# https://github.com/jupyterhub/jupyterhub/blob/master/examples/cull-idle/cull_idle_servers.py
# Due to environment variable bugs we have changed the mechanism by which we attain the jupyterhub
# API key.
# Author: Eli <eli@zagaran.com>

import datetime
import json
import os
import sys
import boto3
import logging

sys.path.insert(1, '/etc/jupyterhub')
from models import Server

from dateutil.parser import parse as parse_date

from botocore.exceptions import ClientError, WaiterError
from concurrent.futures import ThreadPoolExecutor
from tornado.gen import coroutine, sleep
from tornado.log import app_log
from tornado.httpclient import AsyncHTTPClient, HTTPRequest, HTTPError
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.options import define, options, parse_command_line

with open("/etc/jupyterhub/server_config.json", "r") as f:
    SERVER_PARAMS = json.load(f) # load local server parameters

app_log.setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.ERROR)
logging.getLogger('botocore').setLevel(logging.ERROR)

thread_pool = ThreadPoolExecutor(10)

@coroutine
def retry(function, *args, **kwargs):
    """ Retries a function up to max_retries, waiting `timeout` seconds between tries.
        This function is designed to retry both boto3 and fabric calls.  In the
        case of boto3, it is necessary because sometimes aws calls return too
        early and a resource needed by the next call is not yet available. """
    max_retries = kwargs.pop("max_retries", 20)
    timeout = kwargs.pop("timeout", 0.25)
    for attempt in range(max_retries):
        try:
            ret = yield thread_pool.submit(function, *args, **kwargs)
            return ret
        except (ClientError, WaiterError) as e:
            app_log.warn("encountered %s, waiting for %s seconds before retrying..." % (type(e), timeout) )
            yield sleep(timeout)
    else:
        print("Failure in %s with args %s and kwargs %s" % (function.__name__, args, kwargs))
        raise e

@coroutine
def manually_kill_server(user_name):
    # Get our AWS server db's instance for the user
    try:
        server = Server.get_server(user_name)
        app_log.debug("Checking server for %s manually..." % user_name)
    except Server.DoesNotExist:
        # it is not necessarily the case that a server will exist, we return early if that is the case.
        app_log.warn("There is no matching, allocated server for user %s" % user_name)
        return
    # get server instance information
    resource = yield retry(boto3.resource, "ec2", region_name=SERVER_PARAMS["REGION"])
    instance = yield retry(resource.Instance, server.server_id)
    # instance object is lazy, run this to get full info...
    yield retry(instance.load)
    
    #stop server if state is running (possible states are stopped, stopping, pending, shutting-down, terminated, and running)
    if instance.state["Name"] == "running":
        retry(instance.stop)
        app_log.info("manually killed server for user %s" % user_name)
    else:
        app_log.debug("server state for user %s is %s, no action taken" % (user_name, instance.state["Name"]))

@coroutine
def cull_idle(url, api_token, timeout):
    #last valid activity timestame
    cull_limit = datetime.datetime.utcnow() - datetime.timedelta(seconds=timeout)
    
    #get user list
    hub_api_authorization_header = { 'Authorization': 'token %s' % api_token}
    users_request = HTTPRequest(url=url + '/users', headers=hub_api_authorization_header )
    
    #run request tornado-asynchronously, extract user list (contains more information)
    resp = yield AsyncHTTPClient().fetch(users_request)
    all_users = json.loads(resp.body.decode('utf8', 'replace'))
    
    #build a bunch of (asynchronous) HTTP request futures...
    stop_notebook_futures = []
    servers_to_check = []
    dont_cull_these = set()
    for user in all_users:

        #extract last activity time, determine cullability of the server.
        last_activity = parse_date(user['last_activity'])
        should_cull = last_activity < cull_limit
        user_name = user['name']
        app_log.debug("checking %s, last activity: %s, server: %s" % (user_name, last_activity, user['server']) )
        
        if not should_cull:
            dont_cull_these.add(user_name)
        
        #server should be culled:
        if user['server'] and should_cull:
            app_log.info("Culling %s (inactive since %s)", user_name, last_activity)
            stop_user_request = HTTPRequest(url=url + '/users/%s/server' % user_name,
                                            method='DELETE',
                                            headers=hub_api_authorization_header )
            stop_notebook_futures.append( (user_name, AsyncHTTPClient().fetch(stop_user_request)) )

        #Server status is None, which means actual status needs to be checked.
        if not user['server'] and should_cull:
            servers_to_check.append(user_name)

        #server should not be culled, just a log statement
        if user['server'] and not should_cull:
            app_log.info("Not culling %s (active since %s)", user['name'], last_activity)
            
    # Cull notebooks using normal API.
    for (user_name, cull_request) in stop_notebook_futures:
        try:
            yield cull_request #this line actually runs the api call to kill a server
        except HTTPError:
            #Due to a bug in Jupyterhub
            app_log.error("Something went wrong culling %s, will be manually killing it.", user_name)
            servers_to_check.append( user_name )
            continue
        app_log.info("Finished culling %s", user_name)
        
    for user_name in servers_to_check:
        if user_name not in dont_cull_these:
            yield manually_kill_server(user_name)


if __name__ == '__main__':
    define('url', default=os.environ.get('JUPYTERHUB_API_URL'), help="The JupyterHub API URL")
    define('timeout', default=SERVER_PARAMS["JUPYTER_NOTEBOOK_TIMEOUT"], help="The idle timeout (in seconds)")
    define('cull_every', default=300, help="The interval (in seconds) for checking for idle servers to cull")
    
    parse_command_line()
    if not options.cull_every:
        options.cull_every = options.timeout // 2

    # we were having significant issues with environment variables, we will just read from a file
    # api_token = os.environ['JUPYTERHUB_API_TOKEN']
    with open("/etc/jupyterhub/api_token.txt", 'r') as f:
        # for culler script to work without modification we need to set this value in the machine environment.
        api_token = f.read().strip()
    
    loop = IOLoop.current()
    cull = lambda: cull_idle(options.url, api_token, options.timeout)
    # run once before scheduling periodic call
    loop.run_sync(cull)
    # schedule periodic cull
    pc = PeriodicCallback(cull, 1e3 * options.cull_every)
    pc.start()
    try:
        loop.start()
    except KeyboardInterrupt:
        pass
