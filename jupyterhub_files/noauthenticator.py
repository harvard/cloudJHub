from tornado import gen
from jupyterhub.auth import PAMAuthenticator, pamela


class NoAuthenticator(PAMAuthenticator):
    """ For development only purposes. This authenticator disables password checks."""

    @gen.coroutine
    def authenticate(self, handler, data):
        """ Authenticate with PAM, and return the username if login is successful.
            Return None otherwise. """
        
        username = data['username']
        try:
            print("\n")
            print(username, data['password'])
            # pamela.authenticate(username, data['password'], service=self.service)
            print("\n")
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