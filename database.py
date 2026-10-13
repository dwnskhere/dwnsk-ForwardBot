
from os import environ
from datetime import datetime, timedelta
from config import Config
import motor.motor_asyncio
from pymongo import MongoClient, ReturnDocument

async def mongodb_version():
    x = MongoClient(Config.DATABASE_URI)
    mongodb_version = x.server_info()['version']
    return mongodb_version

class Database:
    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.bot = self.db.bots
        self.col = self.db.users
        self.nfy = self.db.notify
        self.chl = self.db.channels
        # Durable forwarding state: survives dyno/container restarts.
        self.forward_jobs = self.db.forward_jobs
        self.forward_job_failures = self.db.forward_job_failures
        
    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )
    
                
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)
    
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id':int(id)})
        return bool(user)
    
    async def total_users_bots_count(self):
        bcount = await self.bot.count_documents({})
        count = await self.col.count_documents({})
        return count, bcount

    async def total_channels(self):
        count = await self.chl.count_documents({})
        return count
    
    async def remove_ban(self, id):
        ban_status = dict(
            is_banned=False,
            ban_reason=''
        )
        await self.col.update_one({'id': id}, {'$set': {'ban_status': ban_status}})
    
    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(
            is_banned=True,
            ban_reason=ban_reason
        )
        await self.col.update_one({'id': user_id}, {'$set': {'ban_status': ban_status}})

    async def get_ban_status(self, id):
        default = dict(
            is_banned=False,
            ban_reason=''
        )
        user = await self.col.find_one({'id':int(id)})
        if not user:
            return default
        return user.get('ban_status', default)

    async def get_all_users(self):
        return self.col.find({})
    
    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})
 
    async def get_banned(self):
        users = self.col.find({'ban_status.is_banned': True})
        b_users = [user['id'] async for user in users]
        return b_users

    async def update_configs(self, id, configs):
        await self.col.update_one({'id': int(id)}, {'$set': {'configs': configs}})
         
    async def get_configs(self, id):
        default = {
            'caption': None,
            'duplicate': True,
            'forward_tag': False,
            'file_size': 0,
            'size_limit': None,
            'extension': None,
            'keywords': None,
            'protect': None,
            'button': None,
            'db_uri': None,
            'filters': {
               'poll': True,
               'text': True,
               'audio': True,
               'voice': True,
               'video': True,
               'photo': True,
               'document': True,
               'animation': True,
               'sticker': True
            }
        }
        user = await self.col.find_one({'id':int(id)})
        if user:
            return user.get('configs', default)
        return default 
       
    async def add_bot(self, datas):
       if not await self.is_bot_exist(datas['user_id']):
          await self.bot.insert_one(datas)
    
    async def remove_bot(self, user_id):
       await self.bot.delete_many({'user_id': int(user_id)})
      
    async def get_bot(self, user_id: int):
       bot = await self.bot.find_one({'user_id': user_id})
       return bot if bot else None
                                          
    async def is_bot_exist(self, user_id):
       bot = await self.bot.find_one({'user_id': user_id})
       return bool(bot)
                                          
    async def in_channel(self, user_id: int, chat_id: int) -> bool:
       channel = await self.chl.find_one({"user_id": int(user_id), "chat_id": int(chat_id)})
       return bool(channel)
    
    async def add_channel(self, user_id: int, chat_id: int, title, username):
       channel = await self.in_channel(user_id, chat_id)
       if channel:
         return False
       return await self.chl.insert_one({"user_id": user_id, "chat_id": chat_id, "title": title, "username": username})
    
    async def remove_channel(self, user_id: int, chat_id: int):
       channel = await self.in_channel(user_id, chat_id )
       if not channel:
         return False
       return await self.chl.delete_many({"user_id": int(user_id), "chat_id": int(chat_id)})
    
    async def get_channel_details(self, user_id: int, chat_id: int):
       return await self.chl.find_one({"user_id": int(user_id), "chat_id": int(chat_id)})
       
    async def get_user_channels(self, user_id: int):
       channels = self.chl.find({"user_id": int(user_id)})
       return [channel async for channel in channels]
     
    async def get_filters(self, user_id):
       filters = []
       filter = (await self.get_configs(user_id))['filters']
       for k, v in filter.items():
          if v == False:
            filters.append(str(k))
       return filters
              
    async def add_frwd(self, user_id):
       return await self.nfy.insert_one({'user_id': int(user_id)})
    
    async def rmve_frwd(self, user_id=0, all=False):
       data = {} if all else {'user_id': int(user_id)}
       return await self.nfy.delete_many(data)
    
    async def get_all_frwd(self):
       return self.nfy.find({})
       
    

    # ---------------- Durable forwarding jobs ----------------
    async def ensure_forward_job_indexes(self):
        await self.forward_jobs.create_index([("status", 1), ("lease_until", 1)])
        await self.forward_jobs.create_index([("user_id", 1), ("status", 1)])
        await self.forward_job_failures.create_index([("job_id", 1), ("source_message_id", 1)], unique=True)

    async def create_forward_job(self, job_id, data):
        """Create a durable task record before the first Telegram send."""
        now = datetime.utcnow()
        document = dict(data)
        # MongoDB creates the queried _id on an upsert; keep it out of the
        # $setOnInsert document to avoid update-path conflicts.
        document.pop("_id", None)
        document.update({
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "last_activity_at": now,
            "lease_until": now + timedelta(minutes=5),
            "worker_id": None,
            "last_processed_id": int(data.get("skip", 0)),
            "fetched": 0,
            "total_files": 0,
            "deleted": 0,
            "failed_count": 0,
        })
        await self.forward_jobs.update_one(
            {"_id": str(job_id)}, {"$setOnInsert": document}, upsert=True
        )
        return await self.forward_jobs.find_one({"_id": str(job_id)})

    async def get_forward_job(self, job_id):
        return await self.forward_jobs.find_one({"_id": str(job_id)})

    async def get_latest_forward_job(self, user_id):
        return await self.forward_jobs.find_one({"user_id": int(user_id)}, sort=[("created_at", -1)])

    async def requeue_forward_job(self, job_id):
        """Allow an explicitly retried needs-attention job to resume at its checkpoint."""
        now = datetime.utcnow()
        return await self.forward_jobs.find_one_and_update(
            {"_id": str(job_id), "status": "needs_attention"},
            {"$set": {
                "status": "queued",
                "worker_id": None,
                "lease_until": now + timedelta(minutes=5),
                "updated_at": now,
                "last_activity_at": now,
                "attempt_count": 0,
            }},
            return_document=ReturnDocument.AFTER,
        )

    async def claim_forward_job(self, job_id, worker_id, lease_seconds=180):
        """Atomically claim a queued job or a job whose previous lease expired."""
        now = datetime.utcnow()
        query = {
            "_id": str(job_id),
            "$or": [
                {"status": "queued"},
                {"status": {"$in": ["running", "interrupted"]}, "lease_until": {"$lte": now}},
            ],
        }
        return await self.forward_jobs.find_one_and_update(
            query,
            {"$set": {
                "status": "running",
                "worker_id": worker_id,
                "lease_until": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
                "last_activity_at": now,
                "started_at": now,
            }, "$inc": {"attempt_count": 1}},
            return_document=ReturnDocument.AFTER,
        )

    async def update_forward_job_progress(self, job_id, worker_id, fields, lease_seconds=180):
        now = datetime.utcnow()
        updates = dict(fields)
        updates.update({
            "updated_at": now,
            "last_activity_at": now,
            "lease_until": now + timedelta(seconds=lease_seconds),
        })
        result = await self.forward_jobs.update_one(
            {"_id": str(job_id), "worker_id": worker_id, "status": "running"},
            {"$set": updates},
        )
        return result.matched_count == 1

    async def heartbeat_forward_job(self, job_id, worker_id, lease_seconds=180):
        now = datetime.utcnow()
        result = await self.forward_jobs.update_one(
            {"_id": str(job_id), "worker_id": worker_id, "status": "running"},
            {"$set": {"lease_until": now + timedelta(seconds=lease_seconds), "last_activity_at": now}},
        )
        return result.matched_count == 1

    async def set_forward_job_status(self, job_id, status, worker_id=None, **fields):
        now = datetime.utcnow()
        updates = dict(fields)
        updates.update({"status": status, "updated_at": now, "last_activity_at": now})
        if status in ("completed", "completed_with_errors", "cancelled", "needs_attention"):
            updates["completed_at"] = now
        if status != "running":
            if status == "interrupted":
                updates.setdefault("lease_until", now - timedelta(seconds=1))
            else:
                updates["lease_until"] = now
            updates["worker_id"] = None
        query = {"_id": str(job_id)}
        if worker_id is not None:
            query["worker_id"] = worker_id
        return await self.forward_jobs.update_one(query, {"$set": updates})

    async def get_recoverable_forward_jobs(self, limit=20):
        now = datetime.utcnow()
        cursor = self.forward_jobs.find({
            "status": {"$in": ["running", "interrupted", "queued"]},
            "lease_until": {"$lte": now},
        }).sort("created_at", 1).limit(limit)
        return [job async for job in cursor]

    async def record_forward_job_failure(self, job_id, user_id, source_chat, destination_chat, source_message_id, error):
        now = datetime.utcnow()
        await self.forward_job_failures.update_one(
            {"job_id": str(job_id), "source_message_id": int(source_message_id)},
            {"$set": {
                "job_id": str(job_id),
                "user_id": int(user_id),
                "source_chat": source_chat,
                "destination_chat": destination_chat,
                "source_message_id": int(source_message_id),
                "error": str(error)[:1000],
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

    async def get_forward_job_failures_after(self, job_id, source_message_id, limit=1000):
        cursor = self.forward_job_failures.find({
            "job_id": str(job_id),
            "source_message_id": {"$gt": int(source_message_id)},
        }).sort("source_message_id", 1).limit(limit)
        return [item async for item in cursor]

    async def count_forward_job_failures(self, job_id):
        return await self.forward_job_failures.count_documents({"job_id": str(job_id)})

    async def get_retryable_forward_job_failures(self, job_id, limit=1000):
        cursor = self.forward_job_failures.find({"job_id": str(job_id)}).sort("source_message_id", 1).limit(limit)
        return [item async for item in cursor]

    async def resolve_forward_job_failure(self, job_id, source_message_id):
        await self.forward_job_failures.delete_one({"job_id": str(job_id), "source_message_id": int(source_message_id)})


db = Database(Config.DATABASE_URI, Config.DATABASE_NAME)
