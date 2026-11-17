"""Kleine Fakes für Telegram-Objekte."""
from types import SimpleNamespace


class FakeBot:
    username = "werki_bot"

    def __init__(self, fail_on=None):
        self.sent = []
        self.attempts = 0
        self.fail_on = fail_on or {}  # Versuch-Nr. → Exception

    async def send_message(self, chat_id, text, **kwargs):
        attempt = self.attempts
        self.attempts += 1
        exc = self.fail_on.pop(attempt, None)
        if exc:
            raise exc
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text, **kwargs))
        return SimpleNamespace(message_id=len(self.sent))

    async def send_document(self, chat_id, document, **kwargs):
        self.documents = getattr(self, "documents", [])
        self.documents.append(SimpleNamespace(chat_id=chat_id, document=document, **kwargs))


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.deleted = False
        self.replies = []

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answers = []
        self.edited_markup = None
        self.edited_text = None

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edited_markup = reply_markup

    async def edit_message_text(self, text, **kwargs):
        self.edited_text = text
        self.edited_texts = getattr(self, "edited_texts", []) + [text]


def make_update(user_id, data=None, text=None):
    query = FakeQuery(data, user_id) if data is not None else None
    message = FakeMessage(text) if text is not None else None
    return SimpleNamespace(
        callback_query=query,
        message=message,
        effective_message=message or (query.message if query else None),
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
    )


def make_context(deps, bot=None):
    return SimpleNamespace(bot_data={"deps": deps}, user_data={}, bot=bot or FakeBot(), args=[])
