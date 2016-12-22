import os
import sys
import socket

def get_local_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip_address = s.getsockname()[0]
    s.close()
    return ip_address

# Inserts location of local code into jupyterhub at runtime.
sys.path.insert(1, '/etc/jupyterhub')

# Configuration file for Jupyter Hub

c = get_config()
c.JupyterHub.cookie_secret_file = '/etc/jupyterhub/cookie_secret'
c.JupyterHub.db_url = '/etc/jupyterhub/jupyterhub.sqlite'

############ Development Settings ###############
c.JupyterHub.log_level = "DEBUG"
c.JupyterHub.debug_proxy = False  # show debug output in configurable-http-proxy

################ Network Settings ################
# leave as-is
c.JupyterHub.proxy_api_ip = '0.0.0.0'
c.JupyterHub.hub_ip = '0.0.0.0'
# TODO-SSL: 443 is for HTTPS. Use 80 if just HTTP for development
c.JupyterHub.port = 80
# TODO-SSL: change me to False
c.JupyterHub.confirm_no_ssl = True
# TODO-SSL: uncomment me below and fill paths to SSL certificate file and key
# c.JupyterHub.ssl_cert = '/etc/jupyterhub/ssl/CHANGEME_TO_YOUR_CERT'
# c.JupyterHub.ssl_key = '/etc/jupyterhub/ssl/CHANGEME_TO_YOUR_CERT_KEY'
# TODO: find the config to disable ssl without a command line switch

with open("/etc/jupyterhub/api_token.txt", 'r') as f:
    # for culler script to work without modification we need to set this value in the machine environment.
    api_token = f.read().strip()
c.JupyterHub.api_tokens = {api_token:"__tokengeneratoradmin"}

c.Spawner.poll_interval = 10
# In seconds. Gives JupyterHub enough time to connect to the notebook. 10 seconds is not enough (sometimes).
c.Spawner.http_timeout = 300
c.Spawner.start_timeout = 300

c.Spawner.options_form = """
<center> You will be automatically redirected. Please hold on. Servers can take up to 2 minutes to boot up. </center>
<center> If you are not redirected within 2 minutes, click <a href="/hub/home">here</a></center>

<script>
document.getElementById("spawn_form").submit();
</script>
"""

################ Spawner Settings ################
c.JupyterHub.spawner_class = 'spawner.InstanceSpawner'
# The periodicity of checks for user activity. Value is in seconds.
c.JupyterHub.last_activity_interval = 15
# Change this to set the maximum time length between entering passwords
c.JupyterHub.cookie_max_age_days = 1
# Grant admin users permission to access all user notebook servers.
c.JupyterHub.admin_access = True
c.JupyterHub.extra_log_file = '/var/log/jupyterhub'

############# User Authenticator Settings ###############
# current Authentication is via Github
#Github
# c.JupyterHub.authenticator_class = 'oauthenticator.LocalGitHubOAuthenticator'
# c.GitHubOAuthenticator.oauth_callback_url = "https://{URL}/hub/oauth_callback"
# c.GitHubOAuthenticator.client_id = ""
# c.GitHubOAuthenticator.client_secret = ""
#this user command is only modified for ubuntu to include the --force-badname parameter due to the __tokengenerator user we have.
c.LocalAuthenticator.add_user_cmd=['adduser', '-q', '--gecos', '""', '--disabled-password', '--force-badname']
# c.GoogleOAuthenticator.client_id = os.environ['OAUTH_CLIENT_ID']
# c.GoogleOAuthenticator.client_secret = os.environ['OAUTH_CLIENT_SECRET']
# c.GoogleOAuthenticator.oauth_callback_url = os.environ['OAUTH_CALLBACK_URL']
# c.GoogleOAuthenticator.hosted_domain = 'mycollege.edu'
# c.GoogleOAuthenticator.login_service = 'My College'

# c.JupyterHub.logo_file = '/etc/jupyterhub/PHOTO.png'
c.LocalAuthenticator.create_system_users = True
# Development authenticator
c.JupyterHub.authenticator_class = 'centosauthenticator.CentosAuthenticator'

# Add users to the admin list, the whitelist, and also record their user ids
c.Authenticator.admin_users = admin = set()
c.Authenticator.whitelist = whitelist = set()
if os.path.isfile('/etc/jupyterhub/userlist'):
    with open('/etc/jupyterhub/userlist') as f:
        for line in f:
            if line.isspace():
                continue
            parts = line.split()
            name = parts[0]
            whitelist.add(name)
            if len(parts) > 1 and parts[1] == 'admin':
                admin.add(name)
