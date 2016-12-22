from tornado import gen
from jupyterhub.auth import PAMAuthenticator, pamela


class CentosAuthenticator(PAMAuthenticator):
    # the centos adduser command is... different from the jupyterhub default command.
    #add_user_cmd = ['adduser']

    # there is a bug in pam/pamela where we cannot get the userid to match, so pam fails invariably
    # update: it may be an selinux thing.
    @gen.coroutine
    def authenticate(self, handler, data):
        """Authenticate with PAM, and return the username if login is successful.

        Return None otherwise.
        """
        
        username = data['username']
        try:
            print("\n")
            print(username, data['password'])
            print("\n")
            # pamela.authenticate(username, data['password'], service=self.service)
        except pamela.PAMError as e:
            if e.errno == 7:
                self.log.warning("PAM Authentication error 7, overriding. logging in as (%s@%s): %s", username,
                                 handler.request.remote_ip, e)
                return username
            
            if handler is not None:
                self.log.warning("PAM Authentication failed (%s@%s): %s", username, handler.request.remote_ip, e)
            else:
                self.log.warning("PAM Authentication failed: %s", e)
        else:
            return username