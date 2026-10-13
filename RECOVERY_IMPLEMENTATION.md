# Durable forwarding jobs and restart recovery

## What this changes

Forwarding progress is no longer kept only in Python process memory. Every confirmed forwarding task is saved in MongoDB before the send loop begins. The bot can therefore restart on Heroku or another container host and continue an interrupted job from the last confirmed source-message checkpoint.

## What is stored

`forward_jobs` contains one document per task, including:

- task owner, source chat, destination chat, and original message-ID limit
- status (`queued`, `running`, `interrupted`, `needs_attention`, `completed`, `completed_with_errors`, or `cancelled`)
- `last_processed_id`, the last source message ID whose outcome was committed
- scanned/forwarded/deleted/failed counters
- caption, forward mode, protection setting, and custom-button text captured at task start
- status-message reference, timestamps, retry attempt count, and a worker lease

`forward_job_failures` contains source message IDs that a copy attempt could not deliver. Failure records are separate from the job document so a large task does not grow one MongoDB document without bound.

Bot/userbot credentials are not copied into the job record; the saved account is looked up from the existing `bots` collection at resume time.

## Recovery lifecycle

1. The user confirms `/forward`; the bot creates a MongoDB job record before starting to send.
2. The bot claims the job using an atomic lease. Only the worker holding that lease can update its checkpoint.
3. Copy mode commits progress after each source message. Native-forward mode commits after each successfully returned batch. Missing/deleted/service messages are recorded as skipped and checkpointed when safe.
4. A heartbeat renews the lease while the task is alive. If the process/dyno dies, the lease expires.
5. The startup recovery worker polls MongoDB every 30 seconds, claims expired jobs, restores the stored counters and checkpoint, and resumes after `last_processed_id`.
6. Transient/unexpected failures are marked `interrupted` and retried automatically. After repeated execution errors, the task moves to `needs_attention` and presents a Retry button. Fix account/source access first, then press Retry to continue at the stored checkpoint.
7. `/fwdstatus` reports the latest task's state, progress, last confirmed source message ID, successful-forward count, and known failed message IDs.

## Delivery guarantee and edge cases

This is designed for **at-least-once recovery**, not exactly-once delivery. Telegram forwarding/copy APIs do not provide an idempotency key that this bot can use to make a send and a MongoDB write one atomic operation.

- In copy mode, a hard process crash after Telegram accepts a message but before its checkpoint is saved can cause that one message to be sent again after recovery.
- In native-forward mode, the current uncommitted batch can be replayed if the process dies after Telegram accepts the batch but before MongoDB commits the checkpoint. The current batch size is 35–75 source IDs.
- This approach deliberately prefers re-sending an uncertain item over advancing the cursor and permanently skipping an item that may not have been delivered.
- Individual copy failures are recorded and shown as `completed_with_errors`; those failure records are visible in `/fwdstatus` (up to 10 IDs are displayed). They are not silently counted as successful forwards.
- Tasks the user manually cancels are not resumed automatically. Tasks marked `needs_attention` wait for explicit Retry after the issue is fixed.

## Deploy notes

- Keep `DATABASE_URI` (or the supported `DATABASE` alias) pointed at persistent MongoDB. The recovery source of truth is MongoDB, not Heroku's ephemeral filesystem.
- Deploy the changed repository and make sure the worker process runs `python3 bot.py` as defined by `Procfile`.
- Only one worker dyno is configured by the existing `app.json`. MongoDB leases guard task ownership, but do not intentionally scale duplicate forwarding worker processes until multi-dyno behavior has been tested with live Telegram accounts.

## Validation performed

- Python files compile successfully.
- `app.json` parses as valid JSON.
- The custom message iterator was smoke-tested for offset/checkpoint resume, the final source message ID, page boundaries, and pagination.
- Durable job storage methods were smoke-tested against a fake MongoDB collection for create, claim, checkpoint, expired-lease recovery, reclaim, and failed-item tracking.
- No live Telegram forwarding or live MongoDB/Heroku integration test was run in this environment.
