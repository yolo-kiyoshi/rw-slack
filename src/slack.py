import os
import slack_sdk
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import traceback
import time
import json
import os
import traceback


class SlackExtractor:
    def __init__(self, SLACK_TOKEN, CHANNEL_ID):
        self.SLACK_TOKEN = SLACK_TOKEN
        self.CHANNEL_ID = CHANNEL_ID
        self.client = slack_sdk.WebClient(token=SLACK_TOKEN)
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        # スレッドのtsを保持するリスト
        self.reply_thread_ts_list = []

    def _create_directories(self, output_dir_base, dirs):
        for dir in dirs:
            dir_path = os.path.join(output_dir_base, dir)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

    def _download_files(self, output_dir_file, messages):
        for message in messages:
            for file in message.get("files", []):
                # if externally-hosted master file or deleted
                if file.get("is_external", False) or file.get("mode", "") == "tombstone":
                    continue
            
                file_url = file["url_private"]
                file_name = file["id"] + "_" + file["name"]
                headers = {'Authorization': f'Bearer {self.SLACK_TOKEN}'}
                try:
                    time.sleep(0.5)
                    r = self.session.get(
                        url=file_url,
                        headers=headers,
                        timeout=(10.0, 30.0)
                    )
                    if r.status_code == 200:
                        with open(os.path.join(output_dir_file, file_name), "wb") as f:
                            f.write(r.content)
                    else:
                        print(f"downloading {file_name} failed.\nstatus code: {r.status_code}\nfile: {json.dumps(file, ensure_ascii=False)}")
                except Exception:
                    print(f"request failed.\n{traceback.format_exc()}\nfile: {json.dumps(file, ensure_ascii=False)}")

    def _save_messages(self, output_dir_message, texts):
        with open(os.path.join(output_dir_message, "messages.jsonl"), mode='w', encoding='utf-8') as f:
            for l in texts:
                f.write(json.dumps(l, ensure_ascii=False) + "\n")

    def extract_main_by_channel(self, output_dir_base, output_dir_file, output_dir_message):
        """
        download files that were uploaded on Slack.
        """
        self._create_directories(output_dir_base, [output_dir_file, output_dir_message])

        cursor = None
        texts = []

        while True:
            try:
                time.sleep(1)
                response = self.client.conversations_history(channel=self.CHANNEL_ID, cursor=cursor)
                messages = response.get("messages", [])
                texts.extend(messages)
                # reply_count が 1 以上なら、スレッドの ts をリストに追加
                for message in messages:
                    if message.get("reply_count", 0) > 0:
                        self.reply_thread_ts_list.append(message["ts"])
                self._download_files(output_dir_file, messages)

                if response['has_more']:
                    cursor = response['response_metadata']['next_cursor']
                else:
                    break
            except Exception:
                print(f"{traceback.format_exc()}")
                break

        self._save_messages(output_dir_message, texts)

    def extract_replys_by_channel(self, output_dir_base):
        """
        download files that were uploaded on Slack.
        """
        for ts in self.reply_thread_ts_list:
            reply_output_dir_base = os.path.join(output_dir_base, f"reply/ts={ts}")
            output_dir_file = os.path.join(reply_output_dir_base, "files")
            output_dir_message = os.path.join(reply_output_dir_base, "messages")
            self._create_directories(reply_output_dir_base, [output_dir_file, output_dir_message])

            cursor = None
            texts = []

            while True:
                try:
                    time.sleep(1)
                    response = self.client.conversations_replies(channel=self.CHANNEL_ID, cursor=cursor, ts=ts)
                    messages = response.get("messages", [])
                    texts.extend(messages)
                    self._download_files(output_dir_file, messages)

                    if response['has_more']:
                        cursor = response['response_metadata']['next_cursor']
                    else:
                        break
                except Exception:
                    print(f"{traceback.format_exc()}. CHANNEL_ID: {self.CHANNEL_ID} failed.")
                    break

            self._save_messages(output_dir_message, texts)
    
    def mention_app(self, app_member_id, message):
        """
        Mention the app in the specified channel and send a message.

        Args:
            app_member_id (str): The Slack member ID of the app.
            message (str): The message to send along with the mention.
        """
        try:
            mention_text = f"<@{app_member_id}> {message}"
            response = self.client.chat_postMessage(
                channel=self.CHANNEL_ID,
                text=mention_text
            )
            print(f"Message sent: {response['ts']}")
        except slack_sdk.errors.SlackApiError as e:
            print(f"Failed to send message: {e.response['error']}")
