# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

Example of a dumb, but interactive, Telegram Bot.

"""

import appdaemon.appapi as appapi


class TelegramBotEventListener(appapi.AppDaemon):
    """Event listener for Telegram bot events."""

    def initialize(self):
        """Listen to Telegram Bot events."""
        self.listen_event(self.receive_telegram_text, 'telegram_text')
        self.listen_event(self.receive_telegram_callback, 'telegram_callback')

    def receive_telegram_callback(self, event_id, payload_event, *args):
        """Event listener for Telegram callback queries."""
        assert event_id == 'telegram_callback'
        data_callback = payload_event['data']
        callback_id = payload_event['id']
        user_id = payload_event['user_id']

        if data_callback == '/edit':  # Message editor:
            # Answer callback query
            data = dict(callback_query=
                        dict(callback_query_id=callback_id, show_alert=True))
            self.call_service('notify/telegram_bot',
                              target=user_id,
                              message='Editing the message!',
                              data=data)

            # Edit the message origin of the callback query
            msg_id = payload_event['message']['message_id']
            user = payload_event['from_first']
            title = '*Message edit*'
            msg = 'Callback received from %s. Message id: %s. Data: ``` %s ```'
            keyboard = ['/edit,/NO', '/remove button']
            data = dict(edit_message=dict(message_id=msg_id),
                        disable_notification=True,
                        inline_keyboard=keyboard)
            self.call_service('notify/telegram_bot',
                              target=user_id,
                              title=title,
                              message=msg % (user, msg_id, data_callback),
                              data=data)

        elif data_callback == '/remove button':  # Keyboard editor:
            # Answer callback query
            data = dict(callback_query=
                        dict(callback_query_id=callback_id, show_alert=False))
            self.call_service('notify/telegram_bot',
                              target=user_id,
                              message='Callback received for editing the '
                                      'inline keyboard!',
                              data=data)

            # Edit the keyboard
            new_keyboard = ['/edit,/NO']
            data = dict(edit_replymarkup=dict(message_id='last'),
                        disable_notification=True,
                        inline_keyboard=new_keyboard)
            self.call_service('notify/telegram_bot',
                              target=user_id,
                              message='',
                              data=data)

        elif data_callback == '/NO':  # Only Answer to callback query
            data = dict(callback_query=
                        dict(callback_query_id=callback_id, show_alert=False))
            self.call_service('notify/telegram_bot',
                              target=user_id,
                              message='OK, you said no!',
                              data=data)

    def receive_telegram_text(self, event_id, payload_event, *args):
        """Text repeater."""
        assert event_id == 'telegram_text'
        user_id = payload_event['user_id']
        msg = 'You said: ``` %s ```' % payload_event['text']
        keyboard = ['/edit,/NO', '/remove button']
        self.call_service('notify/telegram_bot',
                          title='*Dumb automation*',
                          target=user_id,
                          message=msg,
                          data=dict(disable_notification=True,
                                    inline_keyboard=keyboard))
