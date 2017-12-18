import datetime
from peewee import Model, MySQLDatabase, TextField, DateTimeField, IntegerField, CharField
from playhouse.sqlite_ext import SqliteExtDatabase

# To use SQLite Database
DB = SqliteExtDatabase('/etc/jupyterhub/server_tracking.sqlite3')

# To use MySQL DB
# DB = MySQLDatabase(DB_NAME, host = DB_HOST , user=DB_USERNAME, passwd=DB_USERPASSWORD)
# Replace:
#   DB_NAME with the database name in MySQL database 
#   DB_HOST the DNS or the IP of the MySQL host
#   DB_USERNAME and DB_USERPASSWORD with username and password of a privileged user.
# Example : 
#    DB = MySQLDatabase('jupyterhub_model', host = "54.0.0.99" , user='jupyterhub_user', passwd="Jupyter#ub_!")


class BaseModel(Model):
    class Meta:
        database = DB


class Server(BaseModel):
    server_id = CharField(unique=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    user_id = CharField(unique=True)
    # ebs_volume_id = TextField(unique=True)

    @classmethod
    def new_server(cls, server_id, user_id):
        cls.create(server_id=server_id, user_id=user_id)

    @classmethod
    def get_server(cls, user_id):
        return cls.get(user_id=user_id)

    @classmethod
    def get_server_count(cls):
        return cls.select().count()

    @classmethod
    def remove_server(cls, server_id):
        cls.delete().where(cls.server_id == server_id).execute()


DB.connect()
Server.create_table(True)
