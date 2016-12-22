import datetime
from peewee import Model, TextField, DateTimeField, IntegerField
from playhouse.sqlite_ext import SqliteExtDatabase

DB = SqliteExtDatabase('/etc/jupyterhub/server_tracking.sqlite3')

class BaseModel(Model):
    class Meta:
        database = DB


class Server(BaseModel):
    server_id = TextField(unique=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    username = TextField(unique=True)
    # ebs_volume_id = TextField(unique=True)

    @classmethod
    def new_server(cls, server_id, username):
        cls.create(server_id=server_id, username=username)

    @classmethod
    def get_server(cls, username):
        return cls.get(username=username)

    @classmethod
    def get_server_count(cls):
        return cls.select().count()

    @classmethod
    def remove_server(cls, server_id):
        cls.delete().where(cls.server_id == server_id).execute()


DB.connect()
Server.create_table(True)
