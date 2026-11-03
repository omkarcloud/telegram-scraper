"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See README.md → "Endpoints" for the full function list
(telegram/api.py: channel_messages, channel_details, messages_search,
message_details, message_comments, invite_details, gift_details).
"""
import json
import os

from telegram.api import channel_details, channel_messages, message_comments

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a username, @username or any t.me link; 20 newest posts with views,
    # reactions, media and link previews (pass cursor=next_cursor for older ones)
    save("messages_durov.json", channel_messages("durov"))

    # the entity page: exact subscriber count, verified tick, id, counters
    save("channel_durov.json", channel_details("https://t.me/durov"))

    # the discussion under a post, 50 comments a page
    save("comments_tginfo_4430.json", message_comments("https://t.me/tginfo/4430"))
