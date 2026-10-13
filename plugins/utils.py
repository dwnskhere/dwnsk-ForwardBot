import time as tm
from database import db 
from .test import parse_buttons

STATUS = {}

class STS:
    def __init__(self, id):
        self.id = id
        self.data = STATUS
        
    
    def verify(self):
        return self.data.get(self.id)
    
    def store(self, From, to, skip, limit):
        self.data[self.id] = {
            "FROM": From, "TO": to, "total_files": 0, "skip": int(skip), "limit": int(limit),
            "fetched": 0, "filtered": 0, "deleted": 0, "duplicate": 0,
            "failed": 0, "total": max(int(limit) - int(skip), 1), "start": 0,
            "last_processed_id": int(skip),
        }
        self.get(full=True)
        return STS(self.id)

    def restore(self, job):
        """Rebuild in-memory status from the durable MongoDB checkpoint."""
        skip = int(job.get("skip", 0))
        limit = int(job.get("limit", 0))
        self.data[self.id] = {
            "FROM": job.get("from_chat"),
            "TO": job.get("to_chat"),
            "total_files": int(job.get("total_files", 0)),
            "skip": skip,
            "limit": limit,
            "fetched": int(job.get("fetched", 0)),
            "filtered": int(job.get("filtered", 0)),
            "deleted": int(job.get("deleted", 0)),
            "duplicate": int(job.get("duplicate", 0)),
            "failed": int(job.get("failed_count", 0)),
            "total": max(limit - skip, 1),
            "start": 0,
            "last_processed_id": int(job.get("last_processed_id", skip)),
        }
        self.get(full=True)
        return STS(self.id)
        
    def get(self, value=None, full=False):
        values = self.data.get(self.id)
        if not full:
           return values.get(value)
        for k, v in values.items():
            setattr(self, k, v)
        return self

    def add(self, key=None, value=1, time=False):
        if time:
          return self.data[self.id].update({'start': tm.time()})
        self.data[self.id].update({key: self.get(key) + value}) 
    
    def divide(self, no, by):
       by = 1 if int(by) == 0 else by 
       return int(no) / by 
    
    async def get_data(self, user_id):
        bot = await db.get_bot(user_id)
        k, filters = self, await db.get_filters(user_id)
        size, configs = None, await db.get_configs(user_id)
        if configs['duplicate']:
           duplicate = [configs['db_uri'], self.TO]
        else:
           duplicate = False
        button = parse_buttons(configs['button'] if configs['button'] else '')
        if configs['file_size'] != 0:
            size = [configs['file_size'], configs['size_limit']]
        return bot, configs['caption'], configs['forward_tag'], {'chat_id': k.FROM, 'limit': k.limit, 'offset': k.skip, 'filters': filters,
                'keywords': configs['keywords'], 'media_size': size, 'extensions': configs['extension'], 'skip_duplicate': duplicate}, configs['protect'], button
