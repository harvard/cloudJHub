import os
import sys
import socket

# Inserts location of local code into jupyterhub at runtime.
sys.path.insert(1, '/etc/jupyterhub')

# Configuration file for Jupyter Hub

c = get_config()
c.JupyterHub.cookie_secret_file = '/etc/jupyterhub/cookie_secret'
c.JupyterHub.db_url = '/etc/jupyterhub/jupyterhub.sqlite'

# For MySQL DB
#c.JupyterHub.db_url = "mysql://{}:{}@{}/{}".format(DB_USERNAME, DB_PASSWORD,DB_HOSTNAME,DB_NAME)
#c.JupyterHub.db_url = "mysql://{}:{}@{}/{}".format("jupyterhubdbuser", "jupyterhubdbuserpassword","jupyterhub-sql.com","jupyterhub_db")


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

with open("/etc/jupyterhub/api_token.txt", 'r') as f:
    # for culler script to work without modification we need to set this value in the machine environment.
    api_token = f.read().strip()
c.JupyterHub.api_tokens = {api_token:"__tokengeneratoradmin"}

c.Spawner.poll_interval = 10
# In seconds. Gives JupyterHub enough time to connect to the notebook.
c.Spawner.http_timeout = 300
c.Spawner.start_timeout = 300

# Setting options_form decouples logging in from spawning a notebook instance, which is useful to avoid error
# when there is already a spawn pending for a user
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
# Production authentication option with Github. Other custom authenticators can be swapped in here.
# c.JupyterHub.authenticator_class = 'oauthenticator.LocalGitHubOAuthenticator'
# c.GitHubOAuthenticator.oauth_callback_url = "https://{URL}/hub/oauth_callback"
# c.GitHubOAuthenticator.client_id = ""
# c.GitHubOAuthenticator.client_secret = ""

# Development authenticator
c.JupyterHub.authenticator_class = 'noauthenticator.NoAuthenticator'
c.LocalAuthenticator.add_user_cmd=['adduser', '-q', '--gecos', '""', '--disabled-password', '--force-badname']
c.LocalAuthenticator.create_system_users = True

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
