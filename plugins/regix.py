import os
import sys 
import math
import time
import asyncio 
import logging
import random
import uuid
from datetime import datetime, timedelta
from .utils import STS
from database import db 
from .test import CLIENT, start_clone_bot, parse_buttons
from config import Config, temp
from translation import Translation
from pyrogram import Client, filters 
from pyrogram.errors import FloodWait, MessageNotModified, RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message 

CLIENT = CLIENT()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
TEXT = Translation.TEXT

#===================Public Start Function===================#

PROCESS_WORKER_ID = f"{os.environ.get('DYNO', 'local')}-{uuid.uuid4().hex}"
ACTIVE_USERS = set()
ACTIVE_JOB_IDS = set()
_RESERVATION_LOCK = asyncio.Lock()


@Client.on_callback_query(filters.regex(r'^start_public'))
async def pub_(bot, message):
    user_id = message.from_user.id
    temp.CANCEL[user_id] = False
    job_id = message.data.split("_")[2]

    if temp.lock.get(user_id):
        return await message.answer("Please wait until your previous task is completed.", show_alert=True)

    sts = STS(job_id)
    if not sts.verify():
        # A needs-attention task may be retried after a process restart. Restore
        # its source/destination and checkpoint from MongoDB for the Retry button.
        saved_job = await db.get_forward_job(job_id)
        if saved_job and saved_job.get("status") == "needs_attention":
            sts.restore(saved_job)
        else:
            await message.answer("This confirmation has expired. Please start /forward again.", show_alert=True)
            return await message.message.delete()

    i = sts.get(full=True)
    if i.TO in temp.IS_FRWD_CHAT:
        return await message.answer("A forwarding task is already using this destination.", show_alert=True)

    status_message = await msg_edit(message.message, "<i><b>Verifying your data. Please wait.</b></i>")
    if status_message is None:
        status_message = message.message
    try:
        account, caption, forward_tag, _data, protect, _button = await sts.get_data(user_id)
        if not account:
            saved_job = await db.get_forward_job(job_id)
            retry_markup = retry_btn(job_id) if saved_job and saved_job.get("status") == "needs_attention" else None
            return await msg_edit(
                status_message,
                "You have not added a bot/userbot yet. Add one in /settings, then press Retry to continue this saved task.",
                retry_markup,
                True,
            )
        configs = await db.get_configs(user_id)
        # The job is saved before any source message is forwarded. Credentials
        # stay in the existing bots collection and are never copied into jobs.
        job = await db.create_forward_job(job_id, {
            "user_id": int(user_id),
            "from_chat": i.FROM,
            "to_chat": i.TO,
            "source_title": str(i.FROM),
            "target_title": str(i.TO),
            "skip": int(i.skip),
            "limit": int(i.limit),
            "caption": caption,
            "forward_tag": bool(forward_tag),
            "protect": protect,
            "button_text": configs.get("button"),
            "status_message_chat_id": int(status_message.chat.id),
            "status_message_id": int(status_message.id),
        })
        # The source-access error screen exposes a Retry button. It should keep
        # the saved cursor, not create a fresh job starting from the beginning.
        if job and job.get("status") == "needs_attention":
            job = await db.requeue_forward_job(job_id) or job
    except Exception as e:
        logger.exception("Could not create durable forwarding job")
        return await msg_edit(status_message, f"<b>Could not save this task to the database:</b> <code>{e}</code>", wait=True)

    await execute_forward_job(bot, job, status_message, resumed=False)


async def execute_forward_job(bot, job, status_message=None, resumed=False):
    """Claim, execute, checkpoint and clean up one durable forwarding job."""
    job_id = str(job.get("_id"))
    user_id = int(job.get("user_id"))
    to_chat = job.get("to_chat")
    client = None
    counted_as_running = False
    claimed_ok = False
    heartbeat_task = None
    sts = STS(job_id)

    async with _RESERVATION_LOCK:
        if user_id in ACTIVE_USERS or job_id in ACTIVE_JOB_IDS:
            return
        if to_chat in temp.IS_FRWD_CHAT:
            return
        claimed = await db.claim_forward_job(job_id, PROCESS_WORKER_ID)
        if not claimed:
            return
        ACTIVE_USERS.add(user_id)
        ACTIVE_JOB_IDS.add(job_id)
        claimed_ok = True

    try:
        sts.restore(claimed)
        temp.CANCEL[user_id] = False

        async def lease_heartbeat():
            while True:
                await asyncio.sleep(30)
                if not await db.heartbeat_forward_job(job_id, PROCESS_WORKER_ID):
                    logger.warning("Lost durable lease for forwarding job %s", job_id)
                    return

        # Start heartbeating immediately after the claim, including while the
        # Telegram account starts or checks source access.
        heartbeat_task = asyncio.create_task(lease_heartbeat())

        if status_message is None:
            try:
                status_message = await bot.get_messages(
                    int(claimed.get("status_message_chat_id", user_id)),
                    int(claimed.get("status_message_id")),
                )
                if not status_message or getattr(status_message, "empty", False):
                    status_message = None
            except Exception:
                status_message = None
        if status_message is None:
            cursor = int(claimed.get("last_processed_id", claimed.get("skip", 0)))
            status_message = await bot.send_message(
                user_id,
                f"<b>Recovered forwarding task.</b> Resuming after source message ID <code>{cursor}</code>.",
            )
            await db.update_forward_job_progress(job_id, PROCESS_WORKER_ID, {
                "status_message_chat_id": int(status_message.chat.id),
                "status_message_id": int(status_message.id),
            })

        if resumed:
            cursor = int(claimed.get("last_processed_id", claimed.get("skip", 0)))
            await send(bot, user_id,
                       f"<b>♻️ Interrupted forwarding recovered.</b> Resuming after source message ID <code>{cursor}</code>.")

        account = await db.get_bot(user_id)
        if not account:
            await db.set_forward_job_status(job_id, "needs_attention", PROCESS_WORKER_ID,
                                            last_error="No configured bot/userbot was found.")
            await msg_edit(status_message, "<b>Cannot resume:</b> no bot/userbot is configured. Add one in /settings, then press Retry.", retry_btn(job_id), True)
            return

        try:
            client = await start_clone_bot(CLIENT.client(account))
        except Exception as e:
            logger.exception("Could not start Telegram client for job %s", job_id)
            attempts = int(claimed.get("attempt_count", 1))
            state = "needs_attention" if attempts >= 4 else "interrupted"
            status_fields = {"last_error": f"Telegram client startup failed: {e}"}
            if state == "interrupted":
                status_fields["lease_until"] = datetime.utcnow() + timedelta(seconds=90)
            await db.set_forward_job_status(job_id, state, PROCESS_WORKER_ID, **status_fields)
            text = ("<b>Could not start the forwarding account.</b> The saved job will retry automatically.\n"
                    if state == "interrupted" else
                    "<b>Automatic retry paused after repeated account startup failures.</b> Fix the account and press Retry.\n")
            await msg_edit(status_message, text + f"<code>{e}</code>", retry_btn(job_id) if state == "needs_attention" else None, True)
            return

        try:
            await client.get_messages(claimed.get("from_chat"), 1)
        except Exception as e:
            await db.set_forward_job_status(job_id, "needs_attention", PROCESS_WORKER_ID,
                                            last_error=f"Source chat access failed: {e}")
            await msg_edit(status_message,
                           "<b>Source chat access denied.</b> The task is saved, but recovery is paused until the account can access the source.",
                           retry_btn(job_id), True)
            return

        temp.forwardings += 1
        counted_as_running = True
        await db.add_frwd(user_id)
        await send(client, user_id, "<b>🚥 Forwarding started / resumed.</b>")
        sts.add(time=True)
        if to_chat not in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.append(to_chat)
        temp.lock[user_id] = True
        # Immediately restore the visible progress panel from MongoDB counters.
        await edit(status_message, "ʀᴇsᴜᴍɪɴɢ / ᴘʀᴏɢʀᴇssɪɴɢ", 10, sts)

        caption = claimed.get("caption")
        forward_tag = bool(claimed.get("forward_tag"))
        protect = claimed.get("protect")
        button = parse_buttons(claimed.get("button_text") or "")
        # A crash can happen after recording a failed item but before its
        # checkpoint. Retry only those failure records beyond the committed
        # cursor; this avoids a database delete request for every successful file.
        pending_failure_rows = await db.get_forward_job_failures_after(
            job_id, int(claimed.get("last_processed_id", claimed.get("skip", 0))), limit=1000
        )
        pending_failure_ids = {int(row["source_message_id"]) for row in pending_failure_rows}
        batch_sleep = 8.0 if account.get("is_bot") else 25.0
        base_sleep = 2.0 if account.get("is_bot") else 4.5
        milestone_counter = 0
        last_edit_time = time.time()

        async def checkpoint(source_message_id):
            # Keep the in-memory mirror aligned with the persisted checkpoint.
            # The dictionary is the source of truth used by STS.restore/get.
            sts.data[sts.id]["last_processed_id"] = int(source_message_id)
            snap = sts.get(full=True)
            snap.last_processed_id = int(source_message_id)
            ok = await db.update_forward_job_progress(job_id, PROCESS_WORKER_ID, {
                "last_processed_id": int(source_message_id),
                "fetched": int(snap.fetched),
                "total_files": int(snap.total_files),
                "deleted": int(snap.deleted),
                "failed_count": int(snap.failed),
                "filtered": int(snap.filtered),
                "duplicate": int(snap.duplicate),
                "last_error": None,
            })
            if not ok:
                raise RuntimeError("Lost the MongoDB job lease; stopping to avoid concurrent forwarding.")

        async def cancellation_requested():
            if not temp.CANCEL.get(user_id):
                return False
            # Keep only the last committed checkpoint. Items in the current
            # uncommitted native-forward batch are intentionally not counted.
            await db.set_forward_job_status(job_id, "cancelled", PROCESS_WORKER_ID)
            if to_chat in temp.IS_FRWD_CHAT:
                temp.IS_FRWD_CHAT.remove(to_chat)
            await edit(status_message, "ᴄᴀɴᴄᴇʟʟᴇᴅ", "ᴄᴀɴᴄᴇʟʟᴇᴅ", sts)
            return True

        batch_ids = []
        batch_cursor = None
        random_batch = random.randint(35, 75)

        async for source_message in client.iter_messages(
            chat_id=claimed.get("from_chat"),
            limit=int(claimed.get("limit", 0)),
            offset=int(sts.get("last_processed_id", claimed.get("skip", 0))),
        ):
            if await cancellation_requested():
                return

            source_id = getattr(source_message, "id", None)
            if source_id is None:
                raise RuntimeError("Telegram returned a source message without an ID; stopping to avoid skipping it.")
            source_id = int(source_id)
            sts.add("fetched")

            if source_message.empty or source_message.service:
                sts.add("deleted")
                if batch_ids:
                    # The empty IDs are part of the in-flight batch's scanned
                    # range and are committed only when that batch succeeds.
                    batch_cursor = source_id
                else:
                    await checkpoint(source_id)
                continue

            if forward_tag:
                batch_ids.append(source_id)
                batch_cursor = source_id
                if len(batch_ids) >= random_batch:
                    await forward(client, batch_ids, status_message, sts, protect)
                    sts.add("total_files", len(batch_ids))
                    milestone_counter += len(batch_ids)
                    await checkpoint(batch_cursor)
                    batch_ids = []
                    batch_cursor = None
                    random_batch = random.randint(35, 75)
                    await asyncio.sleep(batch_sleep + random.uniform(1.0, 5.0))
            else:
                details = {
                    "msg_id": source_id,
                    "media": media(source_message),
                    "caption": custom_caption(source_message, caption),
                    "button": button,
                    "protect": protect,
                }
                success = await copy(client, details, status_message, sts)
                if success:
                    if source_id in pending_failure_ids:
                        await db.resolve_forward_job_failure(job_id, source_id)
                        pending_failure_ids.discard(source_id)
                    sts.add("total_files")
                    milestone_counter += 1
                else:
                    sts.add("deleted")
                    sts.add("failed")
                    await db.record_forward_job_failure(
                        job_id, user_id, claimed.get("from_chat"), to_chat, source_id,
                        "Telegram copy failed; check account permissions, source availability, media type and logs.",
                    )
                await checkpoint(source_id)
                await asyncio.sleep(base_sleep + random.uniform(0.5, 2.5))

            if milestone_counter >= 10000:
                await edit(status_message, "ᴅᴇᴇᴘ sʟᴇᴇᴘ (15ᴍ)", 900, sts)
                await asyncio.sleep(900)
                milestone_counter = 0
                last_edit_time = time.time()
            if time.time() - last_edit_time > 60:
                await edit(status_message, "ᴘʀᴏɢʀᴇssɪɴɢ", 10, sts)
                last_edit_time = time.time()

        if batch_ids:
            await forward(client, batch_ids, status_message, sts, protect)
            sts.add("total_files", len(batch_ids))
            await checkpoint(batch_cursor)

        failures = await db.count_forward_job_failures(job_id)
        state = "completed_with_errors" if failures else "completed"
        current = sts.get(full=True)
        await db.set_forward_job_status(
            job_id, state, PROCESS_WORKER_ID,
            last_processed_id=int(current.last_processed_id),
            fetched=int(current.fetched), total_files=int(current.total_files),
            deleted=int(current.deleted), failed_count=int(failures), last_error=None,
        )
        if to_chat in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.remove(to_chat)
        if failures:
            await send(client, user_id,
                       f"<b>Forwarding scan completed with {failures} failed message(s).</b> Successful deliveries and failed source IDs are saved in MongoDB.")
            await edit(status_message, "ᴄᴏᴍᴘʟᴇᴛᴇᴅ ᴡɪᴛʜ ᴇʀʀᴏʀs", "ᴄᴏᴍᴘʟᴇᴛᴇᴅ", sts)
        else:
            await send(client, user_id, "<b>🎉 Mass forwarding completed successfully!</b>")
            await edit(status_message, "ᴄᴏᴍᴘʟᴇᴛᴇᴅ", "ᴄᴏᴍᴘʟᴇᴛᴇᴅ", sts)

    except Exception as e:
        logger.exception("Forwarding job %s interrupted", job_id)
        try:
            # Do not persist counters from an uncommitted/in-flight batch. The
            # last successful checkpoint already contains the consistent values.
            attempts = int(claimed.get("attempt_count", 1)) if claimed_ok else 1
            state = "needs_attention" if attempts >= 4 else "interrupted"
            fields = {"last_error": str(e)[:1000]}
            if state == "interrupted":
                fields["lease_until"] = datetime.utcnow() + timedelta(seconds=90)
            await db.set_forward_job_status(job_id, state, PROCESS_WORKER_ID, **fields)
        except Exception:
            logger.exception("Could not persist interrupted state for job %s", job_id)
            state = "interrupted"
        if status_message is not None:
            if state == "needs_attention":
                message_text = f"<b>Automatic recovery paused after repeated errors.</b> Fix the issue and press Retry.\n<code>{e}</code>"
                await msg_edit(status_message, message_text, retry_btn(job_id), True)
            else:
                await msg_edit(status_message,
                               f"<b>Forwarding paused safely.</b> The last confirmed checkpoint is saved; automatic recovery will retry.\n<code>{e}</code>",
                               wait=True)
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        if client is not None:
            try:
                await stop(client, user_id)
            except Exception:
                logger.exception("Cleanup failed for job %s", job_id)
        else:
            temp.lock[user_id] = False
            if counted_as_running:
                temp.forwardings = max(0, temp.forwardings - 1)
        if to_chat in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.remove(to_chat)
        if claimed_ok:
            ACTIVE_USERS.discard(user_id)
            ACTIVE_JOB_IDS.discard(job_id)


async def recovery_worker(bot):
    """Recover expired jobs on startup and keep watching for interrupted tasks."""
    indexes_ready = False
    while True:
        try:
            if not indexes_ready:
                await db.ensure_forward_job_indexes()
                indexes_ready = True
            jobs = await db.get_recoverable_forward_jobs(limit=20)
            for job in jobs:
                user_id = int(job.get("user_id", 0))
                if user_id in ACTIVE_USERS or str(job.get("_id")) in ACTIVE_JOB_IDS:
                    continue
                if job.get("to_chat") in temp.IS_FRWD_CHAT:
                    continue
                status_message = None
                try:
                    status_message = await bot.get_messages(
                        int(job.get("status_message_chat_id", user_id)),
                        int(job.get("status_message_id")),
                    )
                    if not status_message or getattr(status_message, "empty", False):
                        status_message = None
                except Exception:
                    status_message = None
                asyncio.create_task(execute_forward_job(bot, job, status_message, resumed=True))
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Durable forwarding recovery scan failed")
        await asyncio.sleep(30)


# --- PROTECTED NETWORK WRAPPERS ---

async def copy(bot, msg, m, sts):
    try:
        if msg.get("media") and msg.get("caption"):
            await bot.send_cached_media(
                chat_id=sts.get('TO'),
                file_id=msg.get("media"),
                caption=msg.get("caption"),
                reply_markup=msg.get('button'),
                protect_content=msg.get("protect"))
        else:
            await bot.copy_message(
                chat_id=sts.get('TO'),
                from_chat_id=sts.get('FROM'),
                caption=msg.get("caption"),
                message_id=msg.get("msg_id"),
                reply_markup=msg.get('button'),
                protect_content=msg.get("protect"))
        return True
    except FloodWait as e:
        wait_time = e.value + 30
        await edit(m, 'sʟᴇᴇᴘɪɴɢ', wait_time, sts)
        await asyncio.sleep(wait_time)
        return await copy(bot, msg, m, sts)
    except Exception as e:
        logger.warning("Copy failed for source message %s: %s", msg.get("msg_id"), e)
        return False


async def forward(bot, msg_ids, m, sts, protect):
    try:
        await bot.forward_messages(
            chat_id=sts.get('TO'),
            from_chat_id=sts.get('FROM'),
            protect_content=protect,
            message_ids=msg_ids)
    except FloodWait as e:
        wait_time = e.value + 40
        await edit(m, 'sʟᴇᴇᴘɪɴɢ', wait_time, sts)
        await asyncio.sleep(wait_time)
        return await forward(bot, msg_ids, m, sts, protect)

# --- UI & FORMATTING ---

async def edit(msg, title, status, sts):
    try:
        i = sts.get(full=True)
        status_text = 'sᴀғᴇ-ғᴏʀᴡᴀʀᴅɪɴɢ' if status == 10 else f"sʟᴇᴇᴘɪɴɢ {status} s" if str(status).isnumeric() else status
        
        total = i.total if i.total > 0 else 1
        percentage = "{:.1f}".format(float(i.fetched)*100/float(total))
        
        p_val = math.floor(float(percentage) / 10)
        bar = "▰" * p_val + "▱" * (10 - p_val)
        
        text = TEXT.format(i.total, i.fetched, i.total_files, i.duplicate, i.deleted, i.skip, i.filtered, status_text, percentage, title)
        
        kb = [[InlineKeyboardButton(f"{bar} {percentage}%", "status_info")]]
        if status in ["ᴄᴀɴᴄᴇʟʟᴇᴅ", "ᴄᴏᴍᴘʟᴇᴛᴇᴅ"]:
            kb.append([InlineKeyboardButton('🗑️ ᴄʟᴏsᴇ', 'close_btn')])
        else:
            kb.append([InlineKeyboardButton('🛑 sᴛᴏᴘ ᴘʀᴏᴄᴇss', 'terminate_frwd')])
            
        await msg_edit(msg, text, InlineKeyboardMarkup(kb))
    except:
        pass

async def is_cancelled(client, user, msg, sts):
    if temp.CANCEL.get(user):
        if sts.TO in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.remove(sts.TO)
        await edit(msg, "ᴄᴀɴᴄᴇʟʟᴇᴅ", "ᴄᴀɴᴄᴇʟʟᴇᴅ", sts)
        await stop(client, user)
        return True
    return False

async def stop(client, user):
    try: await client.stop()
    except: pass 
    await db.rmve_frwd(user)
    temp.forwardings = max(0, temp.forwardings - 1)
    temp.lock[user] = False 

def custom_caption(msg, caption):
    if msg.media:
        media_obj = getattr(msg, msg.media.value, None)
        if media_obj:
            fcap = getattr(msg, 'caption', '')
            if fcap: fcap = fcap.html
            if caption:
                return caption.format(filename=getattr(media_obj, 'file_name', ''), 
                                    size=get_size(getattr(media_obj, 'file_size', 0)), 
                                    caption=fcap)
            return fcap
    return None

def get_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

def media(msg):
    if msg.media:
        media_obj = getattr(msg, msg.media.value, None)
        if media_obj: return getattr(media_obj, 'file_id', None)
    return None 

async def msg_edit(msg, text, button=None, wait=None):
    try: return await msg.edit(text, reply_markup=button)
    except MessageNotModified: pass 
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await msg_edit(msg, text, button, wait)

async def send(bot, user, text):
    try: await bot.send_message(user, text=text)
    except: pass 

def retry_btn(id):
    return InlineKeyboardMarkup([[InlineKeyboardButton('♻️ ʀᴇᴛʀʏ ♻️', f"start_public_{id}")]])

@Client.on_callback_query(filters.regex(r'^terminate_frwd$'))
async def terminate_frwding(bot, m):
    temp.CANCEL[m.from_user.id] = True 
    await m.answer("🛑 ʜᴀʟᴛɪɴɢ ᴘʀᴏᴄᴇss...", show_alert=True)

@Client.on_callback_query(filters.regex(r'^close_btn$'))
async def close(bot, update):
    await update.message.delete()


@Client.on_message(filters.private & filters.command(["fwdstatus", "forwardstatus"]))
async def forward_status_command(bot, message):
    """Show the user's latest durable job and any source message failures."""
    user_id = int(message.from_user.id)
    job = await db.get_latest_forward_job(user_id)
    if not job:
        return await message.reply_text("No saved forwarding tasks were found.")

    status = str(job.get("status", "unknown"))
    last_id = int(job.get("last_processed_id", job.get("skip", 0)))
    fetched = int(job.get("fetched", 0))
    forwarded = int(job.get("total_files", 0))
    failed = int(job.get("failed_count", await db.count_forward_job_failures(job.get("_id"))))
    limit = int(job.get("limit", 0))
    pct = min(100.0, (fetched * 100.0 / max(limit - int(job.get("skip", 0)), 1)))
    text = (
        "<b>Latest forwarding task</b>\n\n"
        f"Status: <code>{status}</code>\n"
        f"Progress: <code>{pct:.2f}%</code>\n"
        f"Scanned: <code>{fetched}</code>\n"
        f"Successfully forwarded: <code>{forwarded}</code>\n"
        f"Known failed messages: <code>{failed}</code>\n"
        f"Last confirmed source message ID: <code>{last_id}</code>\n"
        f"Source: <code>{job.get('from_chat')}</code>\n"
        f"Destination: <code>{job.get('to_chat')}</code>"
    )
    failures = await db.get_retryable_forward_job_failures(job.get("_id"), limit=10)
    if failures:
        ids = ", ".join(str(item.get("source_message_id")) for item in failures)
        text += f"\n\n<b>Known failed source message IDs (up to 10):</b>\n<code>{ids}</code>"
    last_error = job.get("last_error")
    if last_error:
        # Telegram HTML should not interpret error content as tags.
        import html
        text += f"\n\n<b>Last error:</b>\n<code>{html.escape(str(last_error)[:700])}</code>"
    return await message.reply_text(text, disable_web_page_preview=True)
